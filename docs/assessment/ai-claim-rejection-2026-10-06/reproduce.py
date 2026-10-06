#!/usr/bin/env python3
"""Re-check claims written by an AI against the real Drift Gate implementation.

Every probe builds its own throw-away Git repository or stdio session and calls
the shipped CLI/adapters. Nothing is read from earlier reports. A claim is
`accepted` only when the probe could not falsify it.

    python reproduce.py --repo ../../.. --out results.json [--audit-base 7244969]
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sh(cwd, *args, stdin=None):
    done = subprocess.run(args, cwd=cwd, input=stdin, capture_output=True, timeout=120)
    return done.returncode, done.stdout.decode('utf-8', 'replace'), done.stderr.decode('utf-8', 'replace')


def git(cwd, *args):
    code, out, err = sh(cwd, 'git', *args)
    if code:
        raise RuntimeError(f'git {args}: {err}')
    return out


def new_repo(parent, name):
    root = Path(parent) / name
    root.mkdir()
    git(root, 'init', '-q')
    git(root, 'config', 'user.email', 'probe@example.invalid')
    git(root, 'config', 'user.name', 'probe')
    return root


def commit(root, message='c'):
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', message)


def cli(repo, cwd, *args):
    return sh(cwd, sys.executable, str(repo / 'main.py'), *args)


def gate(repo, cwd, policy, base):
    code, out, err = cli(repo, cwd, 'check', '--policy', policy, '--base', base, '--json')
    data = json.loads(out)
    return code, data.get('result'), [v['rule_id'] for v in data.get('violations', [])], data


# --- probes -----------------------------------------------------------------

def probe_exit_codes(repo, tmp):
    root = new_repo(tmp, 'codes')
    (root / 'a.md').write_text('x\n')
    commit(root)
    checklist = root / 'cl.md'
    checklist.write_text('- [x] done\n')
    runs = {
        'check --json': ('check', '--base', 'no-such-ref', '--json'),
        'report': ('report', '--base', 'no-such-ref'),
        'review --format json': ('review', '--base', 'no-such-ref', '--format', 'json'),
        'self-audit': ('self-audit', '--checklist', str(checklist), '--base', 'no-such-ref', '--json'),
    }
    codes = {name: cli(repo, root, *args)[0] for name, args in runs.items()}
    outside = Path(tmp) / 'not-a-repo'
    outside.mkdir()
    codes['check outside a repository'] = cli(repo, outside, 'check', '--json')[0]
    missing = cli(repo, root, 'self-audit', '--checklist', str(root / 'missing.md'), '--base', 'HEAD', '--json')
    return {'exit_codes': codes, 'missing_checklist_json_mode': {
        'exit': missing[0], 'stdout': missing[1][:120], 'stderr': missing[2][:120]}}


def probe_json_error(repo, tmp):
    root = new_repo(tmp, 'jsonerr')
    (root / 'a.md').write_text('x\n')
    commit(root)
    code, out, _ = cli(repo, root, 'check', '--base', 'no-such-ref', '--json')
    return {'git_failure': json.loads(out), 'exit': code}


def probe_git_names(repo, tmp):
    sys.path.insert(0, str(repo))
    from drift_gate.adapters.git.client import GitAdapter, GitInputError
    root = new_repo(tmp, 'names')
    (root / 'README.md').write_text('a\n')
    commit(root)
    names = ['src/routes/한글.py', 'dir with space/a b.md', 'src/routes/[x]*.py', "src/routes/'q'.py",
             'src/routes/new\nline.py', '-dash.txt']
    for name in names:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('1\n')
    git(root, 'add', '-A')
    found = sorted(f.path for f in GitAdapter(root).get_changed_files('HEAD'))
    try:
        GitAdapter(root).get_changed_files('--output=/tmp/x')
        injected = 'accepted'
    except GitInputError:
        injected = 'rejected'
    return {'expected': sorted(names), 'collected': found, 'equal': found == sorted(names), 'option_like_base': injected}


def probe_untracked(repo, tmp):
    root = new_repo(tmp, 'untracked')
    (root / '.drift-gate.yml').write_text((repo / '.drift-gate.yml').read_text(encoding='utf-8'), encoding='utf-8')
    (root / 'README.md').write_text('a\n')
    commit(root)
    (root / 'src' / 'routes').mkdir(parents=True)
    (root / 'src' / 'routes' / 'new.py').write_text('@app.get("/x")\ndef x(): pass\n')
    code, out, err = cli(repo, root, 'check', '--base', 'HEAD', '--json')
    data = json.loads(out)
    untracked_result = {'result': data['result'], 'scanned_files': data['scan_metrics']['scanned_files'], 'stderr': err[:100]}
    git(root, 'add', '-N', 'src/routes/new.py')
    after = json.loads(cli(repo, root, 'check', '--base', 'HEAD', '--json')[1])
    return {'untracked': untracked_result, 'after_add_N': {'result': after['result'], 'rules': [v['rule_id'] for v in after['violations']]}}


def probe_stale_base(repo, tmp):
    root = new_repo(tmp, 'stale')
    (root / '.drift-gate.yml').write_text((repo / '.drift-gate.yml').read_text(encoding='utf-8'), encoding='utf-8')
    (root / 'README.md').write_text('x\n')
    (root / 'docs').mkdir()
    (root / 'src' / 'routes').mkdir(parents=True)
    commit(root, 'base')
    git(root, 'branch', '-M', 'main')
    git(root, 'checkout', '-qb', 'feature')
    (root / 'src' / 'app.py').write_text('def f():\n    return 1\n')
    commit(root, 'feature work')
    git(root, 'checkout', '-q', 'main')
    (root / 'docs' / 'spec.md').write_text('# api\n')
    (root / 'src' / 'routes' / 'new.py').write_text('route\n')
    commit(root, 'main moves on')
    git(root, 'checkout', '-q', 'feature')
    base_name = gate(repo, root, str(root / '.drift-gate.yml'), 'main')
    merge_base = git(root, 'merge-base', 'main', 'HEAD').strip()
    base_sha = gate(repo, root, str(root / '.drift-gate.yml'), merge_base)
    deleted = [f['path'] + ':' + f['status'] for v in base_name[3]['violations'] for f in v['trigger_files']]
    return {'base_main': {'result': base_name[1], 'rules': base_name[2], 'trigger_files': deleted},
            'base_merge_base': {'result': base_sha[1], 'rules': base_sha[2]}}


def probe_mcp(repo, tmp):
    import math  # noqa: F401  (documented: NaN must be injected through a real file)
    secret = Path(tmp) / 'outside.jsonl'
    secret.write_text('{"timestamp":"2026-10-05T00:00:00+00:00","rule_id":"x","note":"OUTSIDE-REPO-VALUE","score":NaN}\n')

    def session(frames):
        done = subprocess.run([sys.executable, str(repo / 'main.py'), 'serve', '--repo', str(repo)],
                              input=b''.join(frames), capture_output=True, timeout=120)
        return [line for line in done.stdout.decode('utf-8', 'replace').splitlines() if line.strip()]

    def rpc(ident, method, params=None):
        return (json.dumps({'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params or {}}) + '\n').encode()

    oversize = session([b'{"jsonrpc":"2.0","id":1,"method":"x","params":{"p":"' + b'a' * 1_100_000 + b'"}}\n', rpc(2, 'tools/list')])
    bad_utf8 = session([b'\xff\xfe{"a":1}\n', rpc(3, 'initialize')])
    history_args = {'path': str(secret), 'days': 3650}
    rpc_history = session([rpc(4, 'tools/call', {'name': 'drift_gate_history', 'arguments': history_args})])[0]
    legacy_history = session([(json.dumps({'tool': 'drift_gate_history', 'args': history_args}) + '\n').encode()])[0]
    batch = session([b'[{"jsonrpc":"2.0","id":1,"method":"tools/list"}]\n'])[0]
    parse_error = session([b'{not json}\n'])[0]
    notification = session([(json.dumps({'jsonrpc': '2.0', 'method': 'tools/list'}) + '\n').encode()])
    text = json.loads(rpc_history)['result']['content'][0]['text']
    return {
        'oversize_then_next_ok': len(oversize) == 2 and json.loads(oversize[1]).get('id') == 2,
        'bad_utf8_then_next_ok': json.loads(bad_utf8[1]).get('id') == 3,
        'batch': json.loads(batch)['error']['message'],
        'jsonrpc_text_contains_NaN_token': 'NaN' in text,
        'jsonrpc_text_excerpt': text.replace('\n', ' ')[:200],
        'legacy_path_same_input': json.loads(legacy_history)['error']['message'],
        'history_reads_file_outside_repo': 'OUTSIDE-REPO-VALUE' in text,
        'parse_error_shape': json.loads(parse_error),
        'notification_without_id_responses': len(notification),
    }


def probe_python_env(repo, _tmp):
    sys.path.insert(0, str(repo))
    from drift_gate.core.evaluation.contracts import env_keys_in_code
    cases = {
        'os.getenv': ['x = os.getenv("A_KEY")'],
        'os.environ.get': ['x = os.environ.get("A_KEY")'],
        'os.environ[]': ['x = os.environ["A_KEY"]'],
        'comment': ['# os.getenv("A_KEY")'],
        'string literal': ['s = "os.getenv(\'A_KEY\')"'],
    }
    return {name: sorted(env_keys_in_code(lines, 'a.py')) for name, lines in cases.items()}


def probe_env_languages(repo, tmp):
    policy = ('rules:\n  - id: env-sync\n    when:\n      any_changed: ["config/**"]\n    require:\n      groups:\n'
              '        - name: sample env\n          all_changed: [".env.example"]\n          content: env-keys\n'
              '    severity: major\n    message: env changed\ngate: {fail_on_blocker: true, fail_on_major_count: 2}\n')
    samples = {
        'python': ('config/loader.py', 'import os\nx = os.getenv("OLD")\n', 'import os\nx = os.getenv("OLD")\ny = os.getenv("NEW_KEY")\n'),
        'go': ('config/config.go', 'package config\nimport "os"\nvar _ = os.Getenv("OLD")\n',
               'package config\nimport "os"\nvar _ = os.Getenv("OLD")\nvar _ = os.Getenv("NEW_KEY")\n'),
        'java': ('config/Config.java', 'class C { String a = System.getenv("OLD"); }\n',
                 'class C { String a = System.getenv("OLD"); String b = System.getenv("NEW_KEY"); }\n'),
        'ruby': ('config/app.rb', 'a = ENV["OLD"]\n', 'a = ENV["OLD"]\nb = ENV["NEW_KEY"]\n'),
        'vite': ('config/env.ts', 'export const a = process.env.OLD;\n',
                 'export const a = process.env.OLD;\nexport const b = import.meta.env.VITE_NEW_KEY;\n'),
    }
    results = {}
    for language, (path, before, after) in samples.items():
        root = new_repo(tmp, f'env-{language}')
        (root / 'p.yml').write_text(policy)
        (root / '.env.example').write_text('OLD=1\n')
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(before)
        commit(root)
        (root / path).write_text(after)
        key = 'VITE_NEW_KEY' if language == 'vite' else 'NEW_KEY'
        (root / '.env.example').write_text(f'OLD=1\n{key}=1\n')
        git(root, 'add', '-A')
        code, result, rules, data = gate(repo, root, 'p.yml', 'HEAD')
        evidence = [g.get('evidence') for v in data['violations'] for g in v['unsatisfied_groups']]
        results[language] = {'result': result, 'rules': rules, 'evidence': evidence[:1]}
    return results


def probe_intensity(repo, tmp):
    policy = ('rules:\n  - id: src-doc-sync\n    when:\n      any_changed: ["src/**", "include/**"]\n'
              '      min_change_intensity: impl-only\n    require:\n      groups:\n        - name: docs\n'
              '          all_changed: ["docs/api.md"]\n    severity: major\n    message: source changed without docs\n'
              'gate: {fail_on_blocker: true, fail_on_major_count: 1}\n')
    root = new_repo(tmp, 'intensity')
    (root / 'p.yml').write_text(policy)
    for folder in ('src', 'docs', 'include'):
        (root / folder).mkdir()
    (root / 'src' / 'service.py').write_text('def make(a,\n         b=1):\n    return a\n')
    (root / 'docs' / 'api.md').write_text('# api\n')
    (root / 'include' / 'api.h').write_text('#define API_VERSION 1\n')
    commit(root)
    edits = {
        'add *extra to a public signature': ('src/service.py', 'def make(a,\n         *extra,\n         b=1):\n    return a\n'),
        'add **options to a public signature': ('src/service.py', 'def make(a,\n         **options,\n         b=1):\n    return a\n'),
        'control: add c=2 to the signature': ('src/service.py', 'def make(a,\n         c=2,\n         b=1):\n    return a\n'),
        'bump #define API_VERSION': ('include/api.h', '#define API_VERSION 2\n'),
        'control: real comment line': ('src/service.py', '# note\ndef make(a,\n         b=1):\n    return a\n'),
    }
    out = {}
    for name, (path, content) in edits.items():
        original = (root / path).read_text()
        (root / path).write_text(content)
        git(root, 'add', '-A')
        code, result, rules, _ = gate(repo, root, 'p.yml', 'HEAD')
        out[name] = {'result': result, 'rules': rules}
        (root / path).write_text(original)
        git(root, 'add', '-A')
    return out


def probe_policy_inputs(repo, tmp):
    """Not claims in the AI documents: other input paths found while reviewing."""
    root = new_repo(tmp, 'policy')
    shutil_policy = (repo / '.drift-gate.yml').read_text(encoding='utf-8')
    (root / '.drift-gate.yml').write_text(shutil_policy, encoding='utf-8')
    (root / 'docs').mkdir()
    (root / 'src' / 'routes').mkdir(parents=True)
    (root / 'docs' / 'readme.md').write_text('x\n')
    commit(root)
    (root / 'src' / 'routes' / 'new.py').write_text('@app.get("/x")\ndef x(): pass\n')
    git(root, 'add', '-A')

    def summary(code, out, err):
        try:
            data = json.loads(out)
            shown = {'result': data.get('result'), 'rules_evaluated': data['scan_metrics']['evaluated_rules']}
        except (ValueError, KeyError):
            shown = {'stdout': out[:80]}
        return {'exit': code, **shown, 'stderr': err.strip().splitlines()[-1][:100] if err.strip() else ''}

    results = {'policy_present_at_root': summary(*cli(repo, root, 'check', '--base', 'HEAD', '--json')),
               'run_from_subdirectory': summary(*cli(repo, root / 'src', 'check', '--base', 'HEAD', '--json')),
               'explicit_policy_that_does_not_exist': summary(*cli(repo, root, 'check', '--policy', 'nope.yml', '--base', 'HEAD', '--json'))}
    (root / 'bad.yml').write_text('rules: [oops\n')
    results['malformed_policy'] = summary(*cli(repo, root, 'check', '--policy', 'bad.yml', '--base', 'HEAD', '--json'))
    (root / 'src' / 'a.py').write_text('def f(x):\n    return x\n')
    git(root, 'add', '-A')
    from_root = cli(repo, root, 'review', '--base', 'HEAD', '--format', 'json')
    from_sub = cli(repo, root / 'src', 'review', '--base', 'HEAD', '--format', 'json')
    results['review_from_root'] = {'exit': from_root[0]}
    results['review_from_subdirectory'] = {'exit': from_sub[0], 'stdout': from_sub[1][:140]}
    return results


def probe_self_audit(repo, audit_base):
    checklist = HERE / 'claims-as-asserted.md'
    code, out, err = cli(repo, repo, 'self-audit', '--checklist', str(checklist), '--base', audit_base, '--json')
    data = json.loads(out)['self_audit']
    return {item['text'].split(' ', 1)[0]: {'status': item['status'], 'evidence_count': len(item['evidence'])}
            for item in data['checklist_items']}


# --- verdicts ---------------------------------------------------------------

def verdicts(r):
    codes = r['exit_codes']['exit_codes']
    missing = r['exit_codes']['missing_checklist_json_mode']
    mcp = r['mcp']
    stale = r['stale_base']
    intensity = r['intensity']
    languages = r['env_languages']
    return {
        'C01': ('accepted' if set(codes.values()) == {2} else 'rejected',
                f'exit codes {codes}'),
        'C02': ('partially accepted' if missing['exit'] != 2 or not missing['stdout'].strip().startswith('{') else 'accepted',
                f"Git failure gives input_error JSON, but a missing checklist in --json mode exits {missing['exit']} with stdout={missing['stdout']!r}"),
        'C03': ('accepted' if r['git_names']['equal'] and r['git_names']['option_like_base'] == 'rejected' else 'rejected',
                f"special names collected={r['git_names']['equal']}, option-like base {r['git_names']['option_like_base']}"),
        'C04': ('accepted with caveat' if r['untracked']['untracked']['scanned_files'] == 0 else 'rejected',
                f"untracked file: {r['untracked']['untracked']}; the run gives no warning that it was skipped"),
        'C05': ('rejected' if stale['base_main']['result'] != stale['base_merge_base']['result'] else 'accepted',
                f"base=main reports {stale['base_main']} on a branch that is behind main; the merge-base gives {stale['base_merge_base']}"),
        'C06': ('accepted' if mcp['oversize_then_next_ok'] else 'rejected', 'oversize frame answered, next frame served'),
        'C07': ('accepted' if mcp['bad_utf8_then_next_ok'] else 'rejected', 'invalid UTF-8 frame answered, next frame served'),
        'C08': ('partially accepted',
                f"batch refused ({mcp['batch']}); parse errors use {mcp['parse_error_shape']} instead of a JSON-RPC error; "
                f"a notification without id got {mcp['notification_without_id_responses']} response(s)"),
        'C09': ('rejected' if mcp['jsonrpc_text_contains_NaN_token'] else 'accepted',
                f"JSON-RPC tools/call text contains NaN: {mcp['jsonrpc_text_excerpt']}; legacy path: {mcp['legacy_path_same_input']}"),
        'C10': ('accepted' if r['python_env'] == {'os.getenv': ['A_KEY'], 'os.environ.get': ['A_KEY'], 'os.environ[]': ['A_KEY'],
                                                   'comment': [], 'string literal': []} else 'rejected', str(r['python_env'])),
        'C11': ('partially accepted' if languages['python']['result'] == 'pass' and languages['go']['result'] != 'pass' else 'accepted',
                'with a correctly updated .env.example: ' + ', '.join(f"{k}={v['result']}" for k, v in languages.items())),
        'C12': ('rejected' if intensity['add *extra to a public signature']['result'] == 'pass' else 'accepted',
                'semantic edits classified as comment-only: ' + ', '.join(
                    f"{k} -> {v['result']}" for k, v in intensity.items())),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=HERE.parents[2])
    parser.add_argument('--out', type=Path, default=HERE / 'results.json')
    parser.add_argument('--audit-base', default='7244969')
    args = parser.parse_args()
    repo = args.repo.resolve()
    if args.out.exists():
        parser.error('results already exist; snapshots are never overwritten')
    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        results['exit_codes'] = probe_exit_codes(repo, tmp)
        results['json_error'] = probe_json_error(repo, tmp)
        results['git_names'] = probe_git_names(repo, tmp)
        results['untracked'] = probe_untracked(repo, tmp)
        results['stale_base'] = probe_stale_base(repo, tmp)
        results['mcp'] = probe_mcp(repo, tmp)
        results['python_env'] = probe_python_env(repo, tmp)
        results['env_languages'] = probe_env_languages(repo, tmp)
        results['intensity'] = probe_intensity(repo, tmp)
        results['additional_policy_inputs'] = probe_policy_inputs(repo, tmp)
    results['self_audit_tool_status'] = probe_self_audit(repo, args.audit_base)
    final = verdicts(results)
    results['claims'] = {key: {'tool_status': results['self_audit_tool_status'].get(key, {}).get('status', 'not audited'),
                               'independent_verdict': verdict, 'observed': observed}
                         for key, (verdict, observed) in final.items()}
    args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for key, value in results['claims'].items():
        print(f"{key}  tool={value['tool_status']:<11} verdict={value['independent_verdict']}")


if __name__ == '__main__':
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    main()
