"""Immutable capture, input identity, source binding and replay counterexamples."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import date
import hashlib
import json
import os
import subprocess

import pytest
import yaml

from drift_gate.adapters import inspection
from drift_gate.adapters.docs.content import attach_env_documents, local_document_reader
from drift_gate.adapters.policy_loader import read_policy
from drift_gate.adapters.snapshot import InspectionSnapshot, capture_inspection, read_bounded_text
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.evaluation_context import EvaluationContext
from drift_gate.core.models.input_manifest import ArtifactState, InputManifest, SourceArtifact, canonical_bytes
from drift_gate.core.models.result import DriftIgnoreDirective
from drift_gate.core.policy.loader import load_policy_from_text


POLICY_DATA = {'rules': [{'id': 'api', 'when': {'any_changed': ['src/**']},
    'require': {'groups': [{'name': 'contract', 'any_changed': ['docs/api.md'],
                          'content': 'api-routes'}]}, 'severity': 'blocker'}]}
POLICY_TEXT = yaml.safe_dump(POLICY_DATA)
CONTEXT = EvaluationContext(date(2026, 10, 7))
BEFORE = "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/old')\ndef api(): return {}\n"
AFTER = BEFORE.replace('/old', '/new')


def files():
    return [ChangedFile('src/api.py', 'modified', patch='@@ -3 +3 @@\n-@app.get("/old")\n+@app.get("/new")\n',
                        before_source=BEFORE, after_source=AFTER),
            ChangedFile('docs/api.md', 'unchanged', after_source='GET /old\n',
                        document_input_state='available', documented_env_keys=[])]


def capture(**kwargs):
    return capture_inspection(**{'changed_files': files(), 'policy': load_policy_from_text(POLICY_TEXT),
                               'policy_source': POLICY_TEXT, 'context': CONTEXT, **kwargs})


def decisions(result):
    data = result.to_dict()
    return {k: data[k] for k in ('result', 'verification', 'summary', 'rule_decisions')}


def artifact(snapshot, path, role):
    return next(a for a in snapshot.manifest.artifacts if a.identity == (path, role))


def test_mutating_caller_inputs_during_analysis_does_not_change_sealed_decision(monkeypatch):
    originals, policy = files(), load_policy_from_text(POLICY_TEXT)
    original_enrich = inspection.enrich_semantic_signals
    def mutate_callers(inputs):
        originals[0].after_source = BEFORE
        originals[1].after_source = 'GET /new\n'
        originals[0].semantic_signals.append('caller-forgery')
        policy.rules.clear()
        return original_enrich(inputs)
    monkeypatch.setattr(inspection, 'enrich_semantic_signals', mutate_callers)
    result = inspection.inspect(changed_files=originals, policy=policy,
                                policy_source=POLICY_TEXT, context=CONTEXT)
    assert result.result == 'fail'
    assert result.input_snapshot.materialize()['changed_files'][0].after_source == AFTER
    assert result.input_snapshot.materialize()['policy'].rules
    assert 'caller-forgery' not in result.inspected_files[0].semantic_signals


def test_replay_after_checkout_deleted_and_result_mutated_uses_captured_inputs(tmp_path, monkeypatch):
    source = tmp_path / 'api.py'; source.write_text(AFTER)
    snapshot = capture(policy_path=tmp_path / '.drift-gate.yml')
    result = inspection.inspect_snapshot(snapshot)
    expected = decisions(result)
    source.unlink()
    result.inspected_files[0].after_source = BEFORE
    result.input_snapshot.materialize()['policy'].rules.clear()
    monkeypatch.setattr(subprocess, 'check_output', lambda *a, **k: pytest.fail('replay must not read Git'))
    replay = inspection.inspect_snapshot(snapshot)
    assert decisions(replay) == expected
    assert result.execution['input_capture'] == replay.execution['input_capture']
    assert result.execution['run_id'] != replay.execution['run_id']


def test_materialized_lists_routes_policy_and_approval_evidence_are_private_copies():
    original = files(); original[0].before_routes = [('GET', '/old')]
    ignored = DriftIgnoreDirective('api', 'approved fixture', approval_verified=True, approval_commit='fixed')
    snapshot = capture(changed_files=original, drift_ignores=[ignored])
    ignored.approval_verified = False
    one = snapshot.materialize(); two = snapshot.materialize()
    one['changed_files'][0].before_routes.append(('GET', '/forged'))
    one['policy'].rules[0].when.any_changed.append('evil/**')
    one['drift_ignores'][0].approval_verified = False
    assert two['changed_files'][0].before_routes == [('GET', '/old')]
    assert two['policy'].rules[0].when.any_changed == ['src/**']
    assert two['drift_ignores'][0].approval_verified


@pytest.mark.parametrize('mutation', ['source', 'patch', 'policy', 'date', 'ignore', 'options'])
def test_meaningful_input_changes_change_capture_digest(mutation):
    baseline = capture()
    values = {}
    if mutation in {'source', 'patch'}:
        values['changed_files'] = files()
        setattr(values['changed_files'][0], 'after_source' if mutation == 'source' else 'patch', 'different')
    elif mutation == 'policy':
        data = deepcopy(POLICY_DATA); data['rules'][0]['severity'] = 'minor'
        values.update(policy_source=yaml.safe_dump(data), policy=load_policy_from_text(yaml.safe_dump(data)))
    elif mutation == 'date': values['context'] = EvaluationContext(date(2026, 10, 8))
    elif mutation == 'ignore': values['drift_ignores'] = [DriftIgnoreDirective('api', 'exception')]
    else: values['contract_proofs'] = True
    changed = capture(**values)
    assert baseline.manifest.input_sha256 != changed.manifest.input_sha256
    assert baseline.manifest.digest != changed.manifest.digest
    assert baseline.manifest.input_sha256 == capture().manifest.input_sha256


def test_present_empty_missing_unavailable_and_not_collected_are_distinct():
    captured = capture(changed_files=[
        ChangedFile('empty.md', 'unchanged', after_source='', document_input_state='available'),
        ChangedFile('missing.md', 'unchanged', document_input_state='missing'),
        ChangedFile('denied.md', 'unchanged', document_input_state='unavailable'),
        ChangedFile('uncaptured.go', 'modified'),
    ])
    states = {a.path: a for a in captured.manifest.artifacts if a.role == 'after-source'}
    assert states['empty.md'].state == ArtifactState.PRESENT
    assert states['empty.md'].to_dict()['observed_text_sha256'] == hashlib.sha256(b'').hexdigest()
    assert states['empty.md'].to_dict()['observed_text_bytes'] == 0
    assert states['missing.md'].state == ArtifactState.ABSENT
    assert states['denied.md'].state == ArtifactState.UNAVAILABLE
    assert states['uncaptured.go'].state == ArtifactState.NOT_COLLECTED
    assert all(states[p].content is None for p in ('missing.md', 'denied.md', 'uncaptured.go'))


def test_rename_and_deletion_preserve_before_identity():
    captured = capture(changed_files=[
        ChangedFile('new.py', 'renamed', previous_path='old.py', before_source=BEFORE, after_source=AFTER),
        ChangedFile('removed.py', 'deleted', before_source=BEFORE),
        ChangedFile('added.py', 'added', after_source=''),
    ])
    assert artifact(captured, 'old.py', 'before-source').content == BEFORE.encode()
    assert artifact(captured, 'new.py', 'after-source').content == AFTER.encode()
    assert artifact(captured, 'removed.py', 'after-source').state == ArtifactState.ABSENT
    assert artifact(captured, 'added.py', 'before-source').state == ArtifactState.ABSENT
    assert artifact(captured, 'added.py', 'after-source').state == ArtifactState.PRESENT


@pytest.mark.parametrize('marker,state', [('[large file skipped]', ArtifactState.LIMITED),
                                         ('[binary file skipped]', ArtifactState.UNSUPPORTED)])
def test_skipped_patch_markers_never_certify_source_bytes(marker, state):
    captured = capture(changed_files=[ChangedFile('data.txt', 'modified', patch=marker)])
    assert artifact(captured, 'data.txt', 'patch').state == state
    assert artifact(captured, 'data.txt', 'after-source').state == state
    assert artifact(captured, 'data.txt', 'patch').content is None


@pytest.mark.parametrize('kind', ['added-before', 'deleted-after', 'missing-after'])
def test_contradictory_absence_and_content_rejected(kind):
    file = ChangedFile('file.py', 'modified')
    if kind == 'added-before': file.status, file.before_source = 'added', 'nonempty'
    elif kind == 'deleted-after': file.status, file.after_source = 'deleted', 'nonempty'
    else: file.document_input_state, file.after_source = 'missing', ''
    with pytest.raises(ValueError, match='contradicts'): capture(changed_files=[file])


def test_relabeling_source_or_manifest_content_rejected():
    snapshot = capture()
    changed = json.loads(snapshot.payload); changed['files'][0]['after_source'] = BEFORE
    with pytest.raises(ValueError, match='mismatch'):
        replace(snapshot, payload=canonical_bytes(changed))
    entries = list(snapshot.manifest.artifacts)
    position = next(i for i, a in enumerate(entries) if a.role == 'after-source')
    entries[position] = replace(entries[position], content=b'forged')
    with pytest.raises(ValueError, match='mismatch'):
        replace(snapshot, manifest=replace(snapshot.manifest, artifacts=tuple(entries)))
    with pytest.raises(FrozenInstanceError): snapshot.payload = b'{}'


def test_legacy_empty_nonexistent_side_is_absent_but_existing_empty_file_is_present():
    snapshot = capture(changed_files=[ChangedFile('added.py', 'added', before_source='', after_source=''),
                                    ChangedFile('deleted.py', 'deleted', before_source='', after_source='')])
    assert artifact(snapshot, 'added.py', 'before-source').state == ArtifactState.ABSENT
    assert artifact(snapshot, 'added.py', 'after-source').state == ArtifactState.PRESENT
    assert artifact(snapshot, 'deleted.py', 'before-source').state == ArtifactState.PRESENT
    assert artifact(snapshot, 'deleted.py', 'after-source').state == ArtifactState.ABSENT


def test_policy_source_cannot_be_bound_to_different_semantics():
    altered = deepcopy(POLICY_DATA); altered['rules'][0]['severity'] = 'minor'
    with pytest.raises(ValueError, match='policy source'):
        capture(policy=load_policy_from_text(yaml.safe_dump(altered)))


@pytest.mark.parametrize('path', ['/outside.py', '../outside.py', 'src/../a.py', 'C:/a.py',
                                  'src//a.py', './a.py', 'src\\a.py', '\x00.py', '\ud800.py'])
def test_unsafe_or_unsupported_path_identity_is_never_normalized_to_another_file(path):
    with pytest.raises(ValueError): capture(changed_files=[ChangedFile(path, 'modified')])


def test_duplicate_path_and_invalid_status_rejected():
    with pytest.raises(ValueError, match='duplicate'): capture(changed_files=[files()[0], files()[0]])
    with pytest.raises(ValueError, match='status'): capture(changed_files=[ChangedFile('a.py', 'mystery')])


def test_manifest_order_does_not_sort_semantically_ordered_policy_groups_or_input_files():
    forward = capture(); reverse = capture(changed_files=list(reversed(files())))
    assert forward.manifest.artifacts == reverse.manifest.artifacts
    assert forward.manifest.input_sha256 != reverse.manifest.input_sha256
    assert reverse.materialize()['changed_files'][0].path == 'docs/api.md'


def test_relative_and_absolute_policy_locations_have_same_capture_identity(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    one = capture(policy_path='.drift-gate.yml', provenance={'source': 'local-git'})
    two = capture(policy_path=tmp_path / '.drift-gate.yml', provenance={'source': 'local-git'})
    assert one.to_dict() == two.to_dict()


def test_public_manifest_contains_no_source_values_and_never_claims_authenticity():
    secret = 'fixture-sensitive-value'
    snapshot = capture(changed_files=[ChangedFile('settings.py', 'modified', after_source=secret)],
                       provenance={'source': 'local-git', 'head': 'caller-head'})
    public = json.dumps(snapshot.to_dict())
    assert secret not in public and 'caller-head' not in public
    data = snapshot.to_dict()
    assert data['collection_mode'] == 'captured-working-tree'
    assert not data['original_bytes_certified'] and not data['revision_certified'] and not data['selection_complete']
    assert data['policy_authority'] == 'unverified-caller-input'
    assert data['retention'] == 'process-memory-only'


@pytest.mark.parametrize('value,encoded', [
    ({'b': 2, 'a': 1}, b'{"a":1,"b":2}'),
    ({'a': [2, 1]}, b'{"a":[2,1]}'),
    ('\u00e9', b'"\\u00e9"'), ('e\u0301', b'"e\\u0301"'),
])
def test_digest_protocol_vectors_preserve_codepoints_and_array_order(value, encoded):
    assert canonical_bytes(value) == encoded


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_metadata_cannot_enter_digest(value):
    with pytest.raises(ValueError): capture(provenance={'unexpected': value})


def test_env_document_raw_observation_is_bound_privately_without_serializing_values(tmp_path):
    text = 'TOKEN=fixture-sensitive-value\r\n'
    (tmp_path / '.env.example').write_bytes(text.encode())
    data = deepcopy(POLICY_DATA)
    data['rules'][0]['require']['groups'][0].update(any_changed=['.env.example'], content='env-keys')
    policy = load_policy_from_text(yaml.safe_dump(data))
    attached = attach_env_documents([], policy, local_document_reader(tmp_path))
    assert attached[0].after_source == text and attached[0].documented_env_keys == ['TOKEN']
    snapshot = capture(changed_files=attached, policy=policy, policy_source=yaml.safe_dump(data))
    assert artifact(snapshot, '.env.example', 'after-source').content == text.encode()
    assert 'fixture-sensitive-value' not in json.dumps(snapshot.to_dict())
    assert 'fixture-sensitive-value' not in json.dumps(attached[0].to_dict())


def test_bounded_reads_preserve_newlines_and_reject_growth_invalid_utf8_and_symlink(tmp_path):
    path = tmp_path / 'input'; path.write_bytes(b'line\r\n')
    assert read_bounded_text(path) == 'line\r\n'
    with pytest.raises(ValueError, match='limit'): read_bounded_text(path, max_bytes=2)
    path.write_bytes(b'\xff')
    with pytest.raises(UnicodeDecodeError): read_bounded_text(path)
    link = tmp_path / 'link'
    try: link.symlink_to(path)
    except OSError: pytest.skip('symlink creation not available')
    with pytest.raises(ValueError, match='symlink'): read_bounded_text(link)


def test_file_replaced_between_read_and_final_stat_is_rejected(tmp_path, monkeypatch):
    import drift_gate.adapters.snapshot as module
    path = tmp_path / 'input'; path.write_text('first')
    real = module.Path.stat
    def replace_after_read(target, *args, **kwargs):
        # Final path stat is after the stream closes, including on Windows.
        if target == path:
            newer = tmp_path / 'newer'; newer.write_text('second'); os.replace(newer, path)
        return real(target, *args, **kwargs)
    monkeypatch.setattr(module.Path, 'stat', replace_after_read)
    with pytest.raises(ValueError, match='snapshot_unstable'): read_bounded_text(path)


def test_policy_reader_and_manifest_bind_same_crlf_source(tmp_path):
    path = tmp_path / '.drift-gate.yml'; path.write_bytes(POLICY_TEXT.replace('\n', '\r\n').encode())
    source, policy = read_policy(path)
    assert '\r\n' in source
    snapshot = capture(policy=policy, policy_source=source)
    assert artifact(snapshot, '@policy', 'policy-source').content == path.read_bytes()


def test_readable_invalid_yaml_retains_raw_text_but_not_verified_document_semantics(tmp_path):
    (tmp_path / 'docs').mkdir()
    text = 'paths: [invalid\n'; (tmp_path / 'docs/api.yaml').write_text(text)
    data = deepcopy(POLICY_DATA)
    data['rules'][0]['require']['groups'][0]['any_changed'] = ['docs/api.yaml']
    source = yaml.safe_dump(data); policy = load_policy_from_text(source)
    attached = attach_env_documents(files()[:1], policy, local_document_reader(tmp_path))
    assert attached[-1].document_input_state == 'unavailable'
    result = inspection.inspect(changed_files=attached, policy=policy, policy_source=source, context=CONTEXT)
    assert result.verification == 'unverified'
    snapshot = result.input_snapshot
    assert artifact(snapshot, 'docs/api.yaml', 'after-source').content == text.encode()
    assert artifact(snapshot, 'docs/api.yaml', 'document-json').state == ArtifactState.UNAVAILABLE


def test_compact_manifest_preserves_identity_and_declares_omitted_entries():
    from drift_gate.adapters.mcp.tools import _render_for_agent
    result = inspection.inspect_snapshot(capture())
    full = _render_for_agent(result, changed_files=result.inspected_files, mode='full', token_budget=1200)
    compact = _render_for_agent(result, changed_files=result.inspected_files, mode='compact', token_budget=1200)
    a, b = full['execution']['input_capture'], compact['execution']['input_capture']
    assert a['manifest_sha256'] == b['manifest_sha256']
    assert b['manifest_entries_omitted'] and b['artifact_count'] == len(a['artifacts'])
    assert 'artifacts' not in b and 'manifest_entries_omitted' not in a


def test_malformed_manifest_and_snapshot_types_rejected():
    with pytest.raises(ValueError): InputManifest((), 'bad', 'captured-adapter-input')
    with pytest.raises(ValueError): SourceArtifact('a.py', 'after-source', ArtifactState.ABSENT)
    with pytest.raises(ValueError): SourceArtifact('a.py', 'after-source', ArtifactState.PRESENT, content=bytearray())
    with pytest.raises(ValueError): InspectionSnapshot(capture().manifest, bytearray())
    with pytest.raises(ValueError): inspection.inspect_snapshot({})
