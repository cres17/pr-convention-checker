"""Recovery copies preserve incomplete edits without confirming implementation."""
import json

import pytest

from drift_gate.desktop.progress_drafts import cache_draft, discard_draft, draft_file, recovery_copy
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
