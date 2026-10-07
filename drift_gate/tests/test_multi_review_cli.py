"""CLI input failures replace previous successful output artifacts."""
import json
import subprocess

import pytest

from drift_gate.adapters.cli.runner import run_cli


def test_bad_temporal_window_replaces_previous_reports(tmp_path, monkeypatch, capsys):
    def git(*args):
        subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True)

    git('init')
    (tmp_path / 'api.py').write_text('value = 1\n', encoding='utf-8')
    (tmp_path / '.drift-gate.yml').write_text(
        'rules:\n  - id: api\n    when:\n      any_changed: [api.py]\n'
        '    severity: blocker\n    require:\n      groups:\n'
        '        - name: docs\n          all_changed: [api.md]\n', encoding='utf-8')
    git('add', '.')
    git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
        'commit', '-m', 'baseline')
    (tmp_path / 'api.py').write_text('value = 2\n', encoding='utf-8')
    out = tmp_path / 'report.json'
    html = tmp_path / 'report.html'
    out.write_text('{"result":"pass","execution":{"run_id":"OLD"}}', encoding='utf-8')
    html.write_text('OLD PASS', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        run_cli(['check', '--temporal-gate', '--temporal-window', 'nonsense', '--json',
                 '--out-json', str(out), '--out-html', str(html)])
    assert exc.value.code == 2
    streams = capsys.readouterr()
    result = json.loads(out.read_text(encoding='utf-8'))
    assert result == json.loads(streams.out)
    assert result['error']['code'] == 'input_error'
    assert result['execution']['run_id'] != 'OLD'
    assert '--temporal-window' in streams.err
    assert 'OLD PASS' not in html.read_text(encoding='utf-8')
    assert 'input_error' in html.read_text(encoding='utf-8')


def test_bad_history_window_uses_same_input_error_boundary(tmp_path, capsys):
    html = tmp_path / 'history.html'
    html.write_text('OLD PASS', encoding='utf-8')
    with pytest.raises(SystemExit) as exc:
        run_cli(['history', '--last', 'nonsense', '--html', str(html)])
    assert exc.value.code == 2
    assert '--last' in capsys.readouterr().err
    assert 'input_error' in html.read_text(encoding='utf-8')
