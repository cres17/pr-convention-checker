"""PR 파일럿 표본 추출과 사례 파일 생성 (protocol.md · protocol-v2.md 규칙 그대로).

네트워크를 쓰지 않는다. 미리 복제해 둔 저장소의 git 이력만 읽는다.
  python collect.py sample --repos-dir DIR --out sample.json
  python collect.py cases  --repos-dir DIR --sample sample.json --out candidates.json
"""
import argparse
import fnmatch
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

REPOS = {
    'open-webui/open-webui': {'dir': 'open-webui', 'branch': 'dev', 'policy': 'open-webui'},
    'langflow-ai/langflow': {'dir': 'langflow', 'branch': 'main', 'policy': 'langflow'},
    'BerriAI/litellm': {'dir': 'litellm', 'branch': 'main', 'policy': 'litellm'},
}
SALT = 'pr-pilot-2026-10-21:'
WINDOW_START = datetime(2026, 7, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 10, 15, 23, 59, 59, tzinfo=timezone.utc)
FLOOR = datetime(2026, 1, 1, tzinfo=timezone.utc)
PER_REPO = 10
MIN_ELIGIBLE = 15
MAX_FILES, MAX_LINES, MAX_SOURCE = 30, 1500, 1_000_000
PR_SUBJECT = re.compile(r'\(#(\d+)\)\s*$|^Merge pull request #(\d+)\b')
BOT = re.compile(r'\[bot\]|dependabot|renovate|github-actions|pre-commit-ci', re.I)
DOC_SUFFIX = ('.md', '.rst', '.mdx')
TEST_GLOBS = ('test_*.py', '*_test.py', '*.test.*', '*.spec.*')
TEST_DIRS = {'tests', 'test', '__tests__'}


def git(repo, *args, check=True):
    out = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, check=check)
    return out.stdout.decode('utf-8', 'replace')


def is_doc(path):
    return path.startswith('docs/') or path.endswith(DOC_SUFFIX)


def is_test(path):
    parts = path.split('/')
    name = parts[-1]
    return any(p in TEST_DIRS for p in parts[:-1]) or any(fnmatch.fnmatch(name, g) for g in TEST_GLOBS)


def candidates(repo, branch, start):
    """대상 브랜치 first-parent 커밋 중 PR 제목 형식인 것. 각 항목은 포함 조건 판정 결과를 가진다."""
    fmt = '%H%x00%P%x00%an%x00%ae%x00%cI%x00%s'
    raw = git(repo, 'log', '--first-parent', branch, f'--since={start.isoformat()}', f'--until={WINDOW_END.isoformat()}',
              f'--format={fmt}')
    rows = []
    for line in raw.splitlines():
        sha, parents, an, ae, cdate, subject = line.split('\x00', 5)
        match = PR_SUBJECT.search(subject)
        if not match:
            continue
        number = int(match.group(1) or match.group(2))
        parent = parents.split()[0] if parents else ''
        row = {'pr': number, 'commit': sha, 'parent': parent, 'author': an, 'committed_at': cdate, 'title': subject}
        reasons = []
        if BOT.search(an) or BOT.search(ae):
            reasons.append('bot')
        if subject.lower().startswith('revert'):
            reasons.append('revert')
        if not parent:
            reasons.append('no-parent')
        else:
            stat = git(repo, 'diff', '--numstat', '-M', parent, sha)
            files, lines, code = 0, 0, 0
            for entry in stat.splitlines():
                add, rem, path = entry.split('\t', 2)
                if '=>' in path:
                    path = re.sub(r'.*=> ?', '', path).rstrip('}')
                files += 1
                lines += (int(add) if add.isdigit() else 0) + (int(rem) if rem.isdigit() else 0)
                if not is_doc(path) and not is_test(path):
                    code += 1
            row.update({'files': files, 'lines': lines, 'code_files': code})
            if files > MAX_FILES:
                reasons.append('too-many-files')
            if lines > MAX_LINES:
                reasons.append('too-many-lines')
            if code < 1:
                reasons.append('no-code-file')
        row['excluded'] = reasons
        rows.append(row)
    return rows


def order_key(repo_name, pr):
    return hashlib.sha256(f'{SALT}{repo_name}:{pr}'.encode()).hexdigest()


def sample(repos_dir):
    result = {'protocol': ['protocol.md', 'protocol-v2.md'], 'repos': {}}
    for name, cfg in REPOS.items():
        repo = Path(repos_dir) / cfg['dir']
        start, extended = WINDOW_START, []
        rows = candidates(repo, cfg['branch'], start)
        eligible = [r for r in rows if not r['excluded']]
        while len(eligible) < MIN_ELIGIBLE and start > FLOOR:
            start = max(FLOOR, datetime(start.year, start.month, 1, tzinfo=timezone.utc) - __import__('datetime').timedelta(days=30))
            extended.append(start.date().isoformat())
            rows = candidates(repo, cfg['branch'], start)
            eligible = [r for r in rows if not r['excluded']]
        eligible.sort(key=lambda r: order_key(name, r['pr']))
        chosen = eligible[:PER_REPO]
        excluded = {}
        for r in rows:
            for reason in r['excluded']:
                excluded[reason] = excluded.get(reason, 0) + 1
        result['repos'][name] = {
            'branch': cfg['branch'], 'window_start': start.date().isoformat(), 'window_extended_to': extended,
            'pr_commits': len(rows), 'eligible': len(eligible), 'excluded_reasons': excluded,
            'head': git(repo, 'rev-parse', cfg['branch']).strip(),
            'selected': [{**{k: v for k, v in r.items() if k != 'excluded'}, 'order_key': order_key(name, r['pr'])} for r in chosen],
        }
    return result


def read_blob(repo, rev, path):
    try:
        data = subprocess.run(['git', '-C', str(repo), 'show', f'{rev}:{path}'], capture_output=True, check=True).stdout
    except subprocess.CalledProcessError:
        return None
    if len(data) > MAX_SOURCE or b'\0' in data:
        return None
    return data.decode('utf-8', 'replace')


def changed_files(repo, parent, commit):
    entries = git(repo, 'diff', '--name-status', '-M', parent, commit).splitlines()
    files = []
    for entry in entries:
        parts = entry.split('\t')
        code = parts[0][0]
        status = {'A': 'added', 'D': 'deleted', 'R': 'renamed'}.get(code, 'modified')
        path, previous = (parts[2], parts[1]) if code == 'R' else (parts[1], None)
        patch = git(repo, 'diff', '--no-color', '-U3', '-M', parent, commit, '--', *( [previous, path] if previous else [path]))
        if '@@' in patch:
            patch = patch[patch.index('@@'):]
        else:
            patch = ''
        files.append({
            'path': path, 'status': status, 'previous_path': previous, 'patch': patch,
            'before_source': None if status == 'added' else read_blob(repo, parent, previous or path),
            'after_source': None if status == 'deleted' else read_blob(repo, commit, path),
        })
    return files


def cases(repos_dir, sample_path):
    if yaml is None:
        sys.exit('PyYAML required')
    data = json.loads(Path(sample_path).read_text(encoding='utf-8'))
    out = []
    here = Path(__file__).parent
    for name, info in data['repos'].items():
        cfg = REPOS[name]
        repo = Path(repos_dir) / cfg['dir']
        policy = yaml.safe_load((here / 'policies' / f"{cfg['policy']}.yml").read_text(encoding='utf-8'))
        for item in info['selected']:
            out.append({
                'case_id': f"{name}#{item['pr']}", 'repository': name, 'source_family': name,
                'policy': policy, 'evaluated_on': item['committed_at'][:10],
                'changed_files': changed_files(repo, item['parent'], item['commit']),
                # 스키마가 요구하는 자리표시자다. 기대값이 아니며 정답은 별도 검토 label로 만든다.
                'expected': {'gate': 'pass', 'rules': {}},
            })
    return {'cases': out}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('step', choices=['sample', 'cases'])
    ap.add_argument('--repos-dir', required=True)
    ap.add_argument('--sample')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    body = sample(a.repos_dir) if a.step == 'sample' else cases(a.repos_dir, a.sample)
    if Path(a.out).exists():
        sys.exit(f'{a.out} already exists; outputs are written once')
    Path(a.out).write_text(json.dumps(body, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(a.out)
