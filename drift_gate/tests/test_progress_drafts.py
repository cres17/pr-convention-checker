"""Recovery copies preserve incomplete edits without confirming implementation."""
import json

import pytest

from drift_gate.desktop.progress_drafts import cache_draft, discard_draft, discard_recovery, draft_file, recovery_copy
from drift_gate.desktop.progress_service import extract_requirements, save_baseline
from drift_gate.tests.test_progress_service import project


def test_restart_recovers_incomplete_fields_without_changing_baseline(tmp_path):
    root = project(tmp_path)
    data = tmp_path / 'data'
    baseline = save_baseline(root, data, extract_requirements(root, ['README.md']))
    draft = json.loads(json.dumps(baseline))
    draft['requirements'][0].update(title='저장 전 수정', criterion='', evidence={'path': '', 'line': 0, 'note': ''})
    cache_draft(root, data, draft)
    recovered = recovery_copy(root, data, baseline)
    assert recovered['recovery']['requirements'][0]['title'] == '저장 전 수정'
    assert recovered['recovery']['requirements'][0]['criterion'] == ''
    assert baseline['requirements'][0]['title'] != '저장 전 수정'
    assert recovered['recovery_warning'] == ''


def test_drafts_are_separate_for_worktrees_and_survive_conflicting_confirmed_version(tmp_path):
    root = project(tmp_path)
    data = tmp_path / 'data'
    draft = extract_requirements(root, ['README.md'])
    draft['version'] = 1
    cache_draft(root, data, draft)
    assert '달라졌습니다' in recovery_copy(root, data, {'version': 2})['recovery_warning']
    other = tmp_path / 'other'
    other.mkdir()
    assert recovery_copy(other, data, None) == {}
    assert draft_file(root, data) != draft_file(other, data)


@pytest.mark.parametrize('corrupt', ['{', '{"schema":1,"draft":{}}'])
def test_corrupt_recovery_does_not_replace_the_confirmed_baseline_or_destroy_copy(tmp_path, corrupt):
    root = project(tmp_path)
    data = tmp_path / 'data'
    target = draft_file(root, data)
    target.parent.mkdir(parents=True)
    target.write_text(corrupt, encoding='utf-8')
    result = recovery_copy(root, data, {'version': 1})
    assert 'recovery' not in result and result['recovery_warning']
    assert target.read_text(encoding='utf-8') == corrupt
    discard_draft(root, data)
    assert recovery_copy(root, data, None) == {}


def test_invalid_or_oversized_write_keeps_the_last_valid_copy(tmp_path):
    root = project(tmp_path)
    data = tmp_path / 'data'
    draft = extract_requirements(root, ['README.md'])
    cache_draft(root, data, draft)
    original = draft_file(root, data).read_bytes()
    with pytest.raises(ValueError):
        cache_draft(root, data, {'documents': {}})
    draft['requirements'][0]['title'] = '가' * 800_000
    with pytest.raises(ValueError, match='2MB'):
        cache_draft(root, data, draft)
    assert draft_file(root, data).read_bytes() == original


@pytest.mark.parametrize('line', [1.5, None, -3, 0])
def test_unfinished_numeric_input_survives_recovery_but_cannot_confirm_implementation(tmp_path, line):
    root = project(tmp_path)
    data = tmp_path / 'data'
    draft = extract_requirements(root, ['README.md'])
    draft['requirements'][0].update(implementation_status='implemented', evidence={'path': 'src/login.py', 'line': line, 'note': ''})
    cache_draft(root, data, draft)
    assert recovery_copy(root, data, None)['recovery']['requirements'][0]['evidence']['line'] == line
    with pytest.raises(ValueError):
        save_baseline(root, data, draft)


def test_old_draft_survives_temporarily_missing_repository(tmp_path):
    root = project(tmp_path)
    data = tmp_path / 'data'
    draft = extract_requirements(root, ['README.md'])
    cache_draft(root, data, draft)
    current = draft_file(root, data)
    payload = json.loads(current.read_text(encoding='utf-8'))
    payload['updated_at'] = '2020-01-01T00:00:00+00:00'
    current.write_text(json.dumps(payload), encoding='utf-8')
    original = current.read_bytes()
    offline = tmp_path / 'offline-repository'
    root.rename(offline)
    other = tmp_path / 'other'
    other.mkdir()
    cache_draft(other, data, {**draft, 'repository': str(other.resolve())})
    offline.rename(root)
    assert current.read_bytes() == original
    assert recovery_copy(root, data, None)['recovery']['requirements'] == draft['requirements']


def test_recovery_keeps_edit_ancestry_for_a_safe_merge_after_restart(tmp_path):
    from copy import deepcopy
    root = project(tmp_path)
    data = tmp_path / 'data'
    baseline = save_baseline(root, data, extract_requirements(root, ['README.md']))
    draft = deepcopy(baseline)
    draft['requirements'][0]['title'] = '내 편집'
    draft['edit_base'] = baseline
    cache_draft(root, data, draft)
    baseline = deepcopy(baseline)
    baseline['requirements'][1]['title'] = '다른 창의 편집'
    latest = save_baseline(root, data, baseline)
    recovered = recovery_copy(root, data, latest)
    assert recovered['recovery']['edit_base']['version'] == 1
    assert recovered['recovery']['edit_base']['requirements'][0]['title'] != '내 편집'
    assert recovered['recovery_warning']


def test_multiple_copies_are_selectable_and_changed_copies_cannot_be_deleted(tmp_path):
    from copy import deepcopy
    root = project(tmp_path)
    data = tmp_path / 'data'
    first = extract_requirements(root, ['README.md'])
    second = deepcopy(first)
    second['requirements'][0]['title'] = '두 번째 창의 편집'
    cache_draft(root, data, first, 'a' * 32)
    cache_draft(root, data, second, 'b' * 32)
    selected = draft_file(root, data, 'a' * 32)
    result = recovery_copy(root, data, None, selected.name)
    assert len(result['recovery_options']) == 2 and result['recovery'] == first
    first['requirements'][0]['title'] = '목록을 읽은 뒤 수정한 새 제목'
    cache_draft(root, data, first, 'a' * 32)
    with pytest.raises(ValueError, match='새 편집'):
        discard_recovery(root, data, selected.name, result['recovery_revision'])
    assert selected.is_file() and draft_file(root, data, 'b' * 32).is_file()
    refreshed = recovery_copy(root, data, None, selected.name)
    discard_recovery(root, data, selected.name, refreshed['recovery_revision'])
    assert recovery_copy(root, data, None)['recovery'] == second
    with pytest.raises(ValueError):
        discard_recovery(root, data, '../outside.json')


@pytest.mark.parametrize('revision', ['', None])
def test_recovery_deletion_requires_revision_even_for_an_existing_copy(tmp_path, revision):
    root = project(tmp_path)
    data = tmp_path / 'data'
    cache_draft(root, data, extract_requirements(root, ['README.md']))
    target = draft_file(root, data)
    original = target.read_bytes()
    with pytest.raises(ValueError, match='수정 버전'):
        discard_recovery(root, data, target.name, revision)
    assert target.read_bytes() == original


def test_all_owner_copies_share_one_persistent_transaction_gate(tmp_path):
    root = project(tmp_path)
    data = tmp_path / 'data'
    draft = extract_requirements(root, ['README.md'])
    for number in range(40):
        cache_draft(root, data, draft, f'{number:032x}')
    assert len(recovery_copy(root, data, None)['recovery_options']) == 40
    for number in range(40):
        discard_draft(root, data, f'{number:032x}')
    discard_draft(root, data, 'f' * 32)
    assert [lock.name for lock in (data / 'drafts').glob('*.lock')] == [draft_file(root, data).name + '.lock']


def test_bulk_cleanup_rechecks_every_revision_before_deleting_any_copy(tmp_path):
    from drift_gate.desktop.progress_drafts import discard_recoveries
    root = project(tmp_path)
    data = tmp_path / 'data'
    draft = extract_requirements(root, ['README.md'])
    for owner in ('a' * 32, 'b' * 32, 'c' * 32):
        cache_draft(root, data, draft, owner)
    options = recovery_copy(root, data, None)['recovery_options']
    draft['requirements'][0]['title'] = '새 편집'
    cache_draft(root, data, draft, 'a' * 32)
    with pytest.raises(ValueError, match='새 편집'):
        discard_recoveries(root, data, options)
    assert all(draft_file(root, data, owner).is_file() for owner in ('a' * 32, 'b' * 32, 'c' * 32))
    refreshed = recovery_copy(root, data, None)['recovery_options']
    discard_recoveries(root, data, refreshed[:2])
    assert len(recovery_copy(root, data, None)['recovery_options']) == 1


def test_session_lease_protects_a_copy_even_if_its_revision_has_not_changed(tmp_path):
    from drift_gate.desktop.progress_drafts import DraftSession, discard_recoveries
    from drift_gate.desktop.store_lock import store_lock
    root = project(tmp_path)
    data = tmp_path / 'data'
    draft = extract_requirements(root, ['README.md'])
    owner = 'a' * 32
    cache_draft(root, data, draft, owner)
    option = recovery_copy(root, data, None)['recovery_options'][0]
    session = DraftSession(root, data, owner)
    try:
        with store_lock(draft_file(root, data)):
            session.start_locked()
        with pytest.raises(ValueError, match='편집 중'):
            discard_recoveries(root, data, [option])
        assert recovery_copy(root, data, None)['recovery_options'][0]['active']
    finally:
        session.close()
    assert not recovery_copy(root, data, None)['recovery_options'][0]['active']
    discard_recoveries(root, data, [option])


def test_export_preserves_incomplete_inputs_and_original_edit_ancestry(tmp_path):
    from copy import deepcopy
    from drift_gate.desktop.progress_drafts import export_draft
    root = project(tmp_path)
    draft = extract_requirements(root, ['README.md'])
    draft['edit_base'] = deepcopy(draft)
    draft['requirements'][0].update(title='내 편집', evidence={'path': '', 'line': None, 'note': ''})
    target = tmp_path / 'export.json'
    export_draft(root, draft, target)
    payload = json.loads(target.read_text(encoding='utf-8'))
    assert payload['draft'] == draft
    assert payload['draft']['edit_base']['requirements'][0]['title'] != '내 편집'


def test_exported_file_import_is_a_separate_copy_and_preserves_baseline_and_ancestry(tmp_path):
    from copy import deepcopy
    from drift_gate.desktop.progress_drafts import export_draft, import_draft
    from drift_gate.desktop.progress_service import load_baseline
    root = project(tmp_path)
    data = tmp_path / 'data'
    baseline = save_baseline(root, data, extract_requirements(root, ['README.md']))
    draft = deepcopy(baseline)
    draft['edit_base'] = deepcopy(baseline)
    draft.update(recovery_key='external.json', recovery_revision='external:1')
    draft['requirements'][0].update(title='파일 편집', evidence={'path': '', 'line': 1.5, 'note': ''})
    cache_draft(root, data, baseline, 'a' * 32)
    existing = draft_file(root, data, 'a' * 32).read_bytes()
    source = tmp_path / 'export.json'
    export_draft(root, draft, source)
    original = source.read_bytes()
    key = import_draft(root, data, source)
    result = recovery_copy(root, data, baseline, key)
    assert len(result['recovery_options']) == 2
    assert result['recovery']['requirements'][0]['title'] == '파일 편집'
    assert result['recovery']['requirements'][0]['evidence']['line'] == 1.5
    assert result['recovery']['edit_base'] == baseline
    assert 'recovery_key' not in result['recovery'] and 'recovery_revision' not in result['recovery']
    assert source.read_bytes() == original and draft_file(root, data, 'a' * 32).read_bytes() == existing
    assert load_baseline(root, data) == baseline
    assert import_draft(root, data, source) != key


@pytest.mark.parametrize('mutation', [
    'schema', 'repository', 'inner_repository', 'base_repository', 'duplicate_ids', 'version',
    'status', 'test_patterns', 'kinds', 'empty_id', 'invalid_base_line',
])
def test_invalid_import_keeps_all_existing_files_unchanged(tmp_path, mutation):
    from copy import deepcopy
    from drift_gate.desktop.progress_drafts import import_draft
    root = project(tmp_path)
    data = tmp_path / 'data'
    draft = extract_requirements(root, ['README.md'])
    payload = {'schema': 1, 'repository': str(root.resolve()), 'draft': deepcopy(draft)}
    modified = payload['draft']
    if mutation == 'schema': payload['schema'] = True
    elif mutation == 'repository': payload['repository'] = '/another/project'
    elif mutation == 'inner_repository': modified['repository'] = '/another/project'
    elif mutation == 'base_repository': modified['edit_base'] = {**deepcopy(draft), 'repository': '/another/project'}
    elif mutation == 'duplicate_ids': modified['requirements'].append(deepcopy(modified['requirements'][0]))
    elif mutation == 'version': modified['version'] = -1
    elif mutation == 'status': modified['requirements'][0]['implementation_status'] = 'bogus'
    elif mutation == 'test_patterns': modified['requirements'][0]['test_patterns'] = 'oops'
    elif mutation == 'kinds': modified['document_kinds'] = {'README.md': []}
    elif mutation == 'empty_id': modified['requirements'][0]['id'] = ''
    elif mutation == 'invalid_base_line':
        modified['edit_base'] = deepcopy(draft)
        modified['edit_base']['requirements'][0]['evidence'] = {'path': 'x', 'line': 1.5, 'note': ''}
    cache_draft(root, data, draft, 'a' * 32)
    before = {path.name: path.read_bytes() for path in (data / 'drafts').glob('*.json')}
    source = tmp_path / 'invalid.json'
    source.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(ValueError): import_draft(root, data, source)
    assert {path.name: path.read_bytes() for path in (data / 'drafts').glob('*.json')} == before


@pytest.mark.parametrize('content', [b'{', b'\xff', b'{"n":NaN}', b'[' * 2000, b'x' * 2_000_001],
                         ids=['invalid-json', 'invalid-encoding', 'nonfinite', 'deep-nesting', 'oversized'])
def test_import_rejects_malformed_or_unbounded_files(tmp_path, content):
    from drift_gate.desktop.progress_drafts import import_draft
    root = project(tmp_path)
    data = tmp_path / 'data'
    source = tmp_path / 'invalid.json'
    source.write_bytes(content)
    with pytest.raises(ValueError): import_draft(root, data, source)
    assert not (data / 'drafts').exists()


def test_busy_gate_does_not_delay_closing_and_leaves_lease_file_for_gated_cleanup(tmp_path):
    from drift_gate.desktop.progress_drafts import DraftSession
    from drift_gate.desktop.store_lock import store_lock
    root = project(tmp_path)
    data = tmp_path / 'data'
    session = DraftSession(root, data, 'a' * 32)
    cache_draft(root, data, extract_requirements(root, ['README.md']), 'a' * 32, session)
    lease = session.lease.with_suffix('.live.lock')
    with store_lock(session.gate):
        assert session.close() is False
        assert session._held is None and lease.exists()
        # Handle has been released; shutdown never unlinks outside the gate.
        with store_lock(session.lease, timeout=0): pass
    result = recovery_copy(root, data, None)
    assert not result['recovery_options'][0]['active'] and not lease.exists()
    assert session.close() is True


def test_clone_backup_roundtrip_normalizes_checkout_without_sharing_drafts(tmp_path):
    import shutil
    import subprocess
    from copy import deepcopy
    from drift_gate.desktop.progress_service import load_baseline
    from drift_gate.desktop.progress_drafts import export_draft, import_draft
    root = project(tmp_path)
    subprocess.run(['git', '-C', str(root), 'remote', 'add', 'origin', 'https://example.invalid/a/project.git'], check=True)
    data = tmp_path / 'data'
    original = save_baseline(root, data, extract_requirements(root, ['README.md']))
    clone = tmp_path / 'clone'
    shutil.copytree(root, clone)
    baseline = load_baseline(clone, data)
    assert baseline['repository'] == str(clone.resolve())
    assert baseline['origin_repository'] == original['repository']
    baseline['edit_base'] = deepcopy(baseline)
    cache_draft(root, data, original, 'a' * 32)
    source = tmp_path / 'backup.json'
    export_draft(clone, baseline, source)
    key = import_draft(clone, data, source)
    restored = recovery_copy(clone, data, baseline, key)['recovery']
    assert restored['repository'] == restored['edit_base']['repository'] == str(clone.resolve())
    assert draft_file(root, data, 'a' * 32).is_file()


def test_recovery_can_preserve_legacy_overflow_and_large_edit_for_explicit_cleanup(tmp_path):
    from copy import deepcopy
    from drift_gate.desktop.progress_drafts import export_draft, import_draft
    root = project(tmp_path)
    data = tmp_path / 'data'
    draft = extract_requirements(root, ['README.md'])
    draft['requirements'] = [{**deepcopy(draft['requirements'][0]), 'id': str(i)} for i in range(121)]
    source = tmp_path / 'overflow.json'
    export_draft(root, draft, source)
    key = import_draft(root, data, source)
    assert len(recovery_copy(root, data, None, key)['recovery']['requirements']) == 121
    with pytest.raises(ValueError): save_baseline(root, data, draft)
    draft['requirements'] = draft['requirements'][:120]
    draft['requirements'][0]['verification_note'] = 'x' * 2_000_001
    export_draft(root, draft, source)
    key = import_draft(root, data, source)
    assert len(recovery_copy(root, data, None, key)['recovery']['requirements'][0]['verification_note']) == 2_000_001


def test_missing_edit_base_repository_is_normalized_before_wire_delivery(tmp_path):
    from copy import deepcopy
    from drift_gate.desktop.progress_drafts import export_draft, import_draft
    root = project(tmp_path)
    draft = extract_requirements(root, ['README.md'])
    draft['edit_base'] = deepcopy(draft)
    draft['edit_base'].pop('repository')
    source = tmp_path / 'backup.json'
    export_draft(root, draft, source)
    key = import_draft(root, tmp_path / 'data', source)
    recovery = recovery_copy(root, tmp_path / 'data', None, key)['recovery']
    assert recovery['edit_base']['repository'] == str(root.resolve())


def test_legacy_cached_base_path_is_bound_without_mutating_the_input(tmp_path):
    from copy import deepcopy
    root = project(tmp_path)
    draft = extract_requirements(root, ['README.md'])
    draft['edit_base'] = deepcopy(draft)
    draft['edit_base'].pop('repository')
    cache_draft(root, tmp_path / 'data', draft)
    assert recovery_copy(root, tmp_path / 'data', None)['recovery']['edit_base']['repository'] == str(root.resolve())
    assert 'repository' not in draft['edit_base']


def test_backup_at_its_exact_byte_limit_round_trips(tmp_path, monkeypatch):
    from drift_gate.desktop import progress_drafts as drafts
    root = project(tmp_path)
    draft = extract_requirements(root, ['README.md'])
    target = tmp_path / 'backup.json'
    drafts.export_draft(root, draft, target)
    ceiling = target.stat().st_size
    monkeypatch.setattr(drafts, 'MAX_BACKUP_BYTES', ceiling)
    drafts.export_draft(root, draft, target)
    key = drafts.import_draft(root, tmp_path / 'data', target)
    recovered = drafts.recovery_copy(root, tmp_path / 'data', None, key)
    assert recovered['recovery']['requirements'] == draft['requirements']
    before = target.read_bytes()
    draft['requirements'][0]['title'] += '한글'
    with pytest.raises(ValueError, match='16MB'):
        drafts.export_draft(root, draft, target)
    assert target.read_bytes() == before


def test_shared_recovery_contract_and_limits(tmp_path):
    from pathlib import Path
    from drift_gate.desktop import progress_limits
    fixture = json.loads((Path(__file__).parent / 'contracts/progress.json').read_text(encoding='utf-8'))
    assert fixture['limits'] == {'confirmed': progress_limits.MAX_REQUIREMENTS,
                                 'recovery': progress_limits.MAX_RECOVERY_REQUIREMENTS}
    draft = fixture['recovery']
    draft['repository'] = draft['edit_base']['repository'] = str(tmp_path.resolve())
    cache_draft(tmp_path, tmp_path / 'data', draft)
    assert recovery_copy(tmp_path, tmp_path / 'data', None)['recovery'] == draft
    draft['requirements'][0]['evidence']['line'] = 'invalid'
    with pytest.raises(ValueError, match='형식'):
        cache_draft(tmp_path, tmp_path / 'data', draft)


def test_archived_provenance_survives_backup_and_recovery(tmp_path):
    from copy import deepcopy
    from drift_gate.desktop.progress_drafts import export_draft, import_draft
    root = project(tmp_path)
    data = tmp_path / 'data'
    baseline = save_baseline(root, data, extract_requirements(root, ['README.md']))
    draft = deepcopy(baseline)
    draft['edit_base'] = deepcopy(baseline)
    draft['archived_documents'] = ['README.md']
    draft['document_kinds'] = {'README.md':'reference'}
    source = tmp_path / 'archive.json'
    export_draft(root, draft, source)
    import_draft(root, data, source)
    assert recovery_copy(root, data, baseline)['recovery']['archived_documents'] == ['README.md']
    assert recovery_copy(root, data, baseline)['recovery']['requirements'] == baseline['requirements']
