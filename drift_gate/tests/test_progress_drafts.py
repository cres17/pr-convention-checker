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
    cache_draft(other, data, draft)
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
