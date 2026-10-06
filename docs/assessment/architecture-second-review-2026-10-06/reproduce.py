"""Observe unresolved boundaries using temporary data; never touch user stores."""
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

workspace = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(workspace))
from drift_gate.desktop import progress_service as service
from drift_gate.tests.test_progress_service import project
from drift_gate.core.engine import run
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.desktop.progress_history import make_snapshot, summarize
from drift_gate.tests.test_progress_history import report

results = {}
with TemporaryDirectory(prefix='second-review-') as directory:
    tmp = Path(directory)
    root = project(tmp)
    data = tmp / 'data'
    baseline = service.save_baseline(root, data, service.extract_requirements(root, ['README.md']))
    (root / 'README.md').rename(root / 'PLAN.md')
    draft = deepcopy(baseline)
    draft['document_kinds'] = {'README.md':'reference'}
    draft['requirements'][0]['title'] = '편집 계속'
    try:
        service.save_baseline(root, data, draft)
    except ValueError as exc:
        results['document_rename'] = {'error':str(exc), 'saved_version':service.load_baseline(root, data)['version'],
            'available_documents':[d['path'] for d in service.list_documents(root)['documents']]}
    else:
        raise AssertionError('Expected the existing missing-document save failure')
    (root / 'PLAN.md').rename(root / 'README.md')
    results['document_rename']['control_version'] = service.save_baseline(root, data, draft)['version']

with TemporaryDirectory(prefix='second-review-aba-') as directory:
    tmp = Path(directory)
    root = project(tmp)
    data = tmp / 'data'
    baseline = service.save_baseline(root, data, service.extract_requirements(root, ['README.md']))
    old_editor = deepcopy(baseline)
    target = next(data.glob('*.json'))
    # Simulate storage deletion/restoration, not an ordinary app save.
    target.unlink()
    fresh = service.extract_requirements(root, ['README.md'])
    fresh['requirements'][1]['title'] = '새 기준의 중요한 편집'
    replacement = service.save_baseline(root, data, fresh)
    old_editor['requirements'][0]['title'] = '오래된 편집기 변경'
    overwritten = service.save_baseline(root, data, old_editor)
    assert replacement['version'] == baseline['version'] == 1
    assert overwritten['requirements'][1]['title'] != replacement['requirements'][1]['title']
    results['baseline_aba'] = {'old_version':baseline['version'], 'replacement_version':replacement['version'],
        'different_baseline_ids':baseline['baseline_id'] != replacement['baseline_id'],
        'accepted_stale_editor_version':overwritten['version'],
        'replacement_edit_preserved':False}

with TemporaryDirectory(prefix='second-review-policy-') as directory:
    policy = Path(directory) / 'policy.yml'
    policy.write_text('rules:\n  - id: required\n    when:\n      any_changed: ["src/**"]\n    require:\n      groups:\n        - name: docs\n          any_changed: ["docs/**"]\n    severity: blocker\n', encoding='utf-8')
    from drift_gate.adapters.policy_loader import load_policy
    files = [ChangedFile(path='src/routes/a.py',status='modified',patch='+x = 1')]
    by_path = run(files,policy_path=str(policy))
    loaded = run(files,policy=load_policy(policy))
    assert by_path.result == 'pass' and loaded.result == 'fail'
    results['core_policy_path'] = {'path_argument_result':by_path.result,'no_policy':by_path.no_policy,
        'loaded_policy_control':loaded.result}

script = 'from drift_gate.adapters.mcp.server import main; main([])'
valid = {'jsonrpc':'2.0','id':2,'method':'tools/list'}
invalid = subprocess.run([sys.executable,'-c',script],input='[]\n'+json.dumps(valid)+'\n',text=True,capture_output=True,cwd=workspace)
control = subprocess.run([sys.executable,'-c',script],input=json.dumps(valid)+'\n',text=True,capture_output=True,cwd=workspace)
assert invalid.returncode != 0 and not invalid.stdout and control.returncode == 0
results['mcp_non_object'] = {'exit':invalid.returncode,'responses':len(invalid.stdout.splitlines()),
    'error':invalid.stderr.splitlines()[-1],'valid_request_control_exit':control.returncode,
    'valid_request_control_responses':len(control.stdout.splitlines())}

# A valid inspection result is currently lost when convenience history is malformed.
with TemporaryDirectory(prefix='second-review-history-') as directory:
    tmp = Path(directory)
    root = project(tmp)
    data = tmp / 'data'
    service.save_baseline(root,data,service.extract_requirements(root,['README.md']))
    current = service.inspect_progress(root,data)
    history = next(data.glob('*.json')).with_suffix('.history.json')
    history.write_text('{"schema":1,"snapshots":[{}]}',encoding='utf-8')
    try:
        service.progress_history_view(root,data,current)
    except KeyError as exc:
        results['malformed_history'] = {'inspection_completed':True,'history_error':str(exc)}
    else:
        raise AssertionError('Expected malformed history to fail')

# Two inspections of the SAME baseline version can still be compared backwards.
old = report({'a':'unknown'}, version=1, at='2026-10-06T01:00:00Z')
future = make_snapshot(report({'a':'implemented'},version=1,at='2026-10-06T02:00:00Z',complete=1))
view = summarize([future],old)
assert view['since_save']['complete_delta'] == -1
results['same_version_history'] = {'report_at':old['at'],'comparison_at':view['since_save']['since'],
    'false_regressed_count':view['since_save']['counts']['regressed']}

(Path(__file__).parent / 'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(results,ensure_ascii=False,indent=2))
