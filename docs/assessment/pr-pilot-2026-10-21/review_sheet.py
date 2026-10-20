"""검토 packet에서 사람·모델 검토자용 시트를 만든다. 엔진 출력은 읽지 않는다 (protocol-v3).

  python review_sheet.py --packet packet.json --out review-sheet.md

시트에는 변경 파일의 diff, 규칙의 변경 경로에 해당하는 파일, 그리고 규칙이 요구하는 문서의
현재(PR 커밋 시점) 내용 요약(키 이름 목록·API 경로 목록)이 들어간다. 규칙 경로 일치는 규칙 정의의
glob 비교일 뿐 엔진의 판정이 아니다.
"""
import argparse
import json
import re
from pathlib import Path

from drift_gate.utils.glob_matcher import matches_any

KEY_LINE = re.compile(r'^\s*#?\s*[A-Za-z_][A-Za-z0-9_]*\s*=')

PR_LABELS = """PR 단위 항목(pass / warn / fail)의 뜻 — 정책 내부 설정이 아니라 저장소 관례 기준이다.
- fail: 이 PR을 그대로 병합하면 저장소 관례상 필요한 문서·예시 파일 갱신이 빠진 상태다(병합 전에 고쳐야 한다).
- warn: 빠졌는지 확정할 수 없지만 의심스럽다(근거를 rationale에 적는다).
- pass: 필요한 갱신이 모두 있거나 문서 갱신이 필요한 변경이 아니다.
같은 PR의 규칙 항목에 violated가 하나라도 있으면 보통 fail이다. 규칙이 undecidable뿐이면 warn이 자연스럽다."""


def openapi_routes(text):
    try:
        paths = json.loads(text).get('paths', {})
    except (ValueError, AttributeError):
        return None
    return sorted(f'{method.upper()} {path}' for path, ops in paths.items() for method in ops
                  if method.lower() in {'get', 'post', 'put', 'patch', 'delete', 'head', 'options'})


def document_summary(file):
    """엔진의 해석(documented_env_keys 등)은 packet에 없다. 원문에서 직접 요약한다."""
    text = file.get('after_source')
    if text is None:
        return '내용을 수집하지 못함(없거나 1MB 초과 또는 바이너리)'
    routes = openapi_routes(text) if file['path'].endswith('.json') else None
    if routes is not None:
        return f"API 경로 {len(routes)}개: " + '; '.join(routes)
    lines = text.splitlines()
    if len(lines) > 150:
        lines = [line for line in lines if KEY_LINE.match(line)]
        head = f"원문이 길어 키처럼 보이는 줄만 표시({len(lines)}줄):"
    else:
        head = f"원문 {len(lines)}줄:"
    return head + '\n```\n' + '\n'.join(lines) + '\n```'


def build(packet):
    out = ['# PR 파일럿 검토 시트 (protocol-v3)\n', '```\n' + packet['instructions'] + '\n```\n', PR_LABELS + '\n',
           '출력 형식: 한 줄에 JSON 하나. 항목마다 `item_id`, `reviewer_id`, `reviewer_kind`(사람이면 `human`, 모델이면 `llm-proxy`), `label`, `rationale`.\n',
           '판정 질문(규칙 항목): 이 PR의 변경에 대해, 저장소가 스스로 따르는 관례상 같은 PR에서 규칙이 요구하는 문서가 갱신되어 있어야 했는가, 그리고 현재 문서가 그 변경을 반영하는가. 도구 출력은 주어지지 않는다.\n']
    by_case = {}
    for item in packet['items']:
        by_case.setdefault(item['case_id'], []).append(item)
    for case_id, items in by_case.items():
        files = items[0]['changed_files']
        changed = [f for f in files if f.get('status') != 'unchanged']
        docs = [f for f in files if f.get('status') == 'unchanged']
        out.append(f'\n---\n\n## {case_id}\n')
        for f in changed:
            prev = f" (이전 경로 {f['previous_path']})" if f.get('previous_path') else ''
            out.append(f"### `{f['path']}` — {f['status']}{prev}\n")
            patch = f.get('patch') or '(patch 없음: 바이너리이거나 비어 있음)'
            out.append('```diff\n' + patch.rstrip('\n') + '\n```\n')
        for item in items:
            if item['kind'] != 'rule':
                continue
            rule = item['rule']
            patterns = rule['when']['any_changed']
            hit = [f['path'] for f in changed if matches_any(f['path'], patterns)]
            required = sorted({p for g in rule['require']['groups'] for p in (g.get('all_changed') or g.get('any_changed') or [])})
            out.append(f"**규칙 `{rule['id']}`** — 항목 `{item['item_id']}`")
            out.append(f"- 규칙의 변경 경로: {patterns} → 이 PR에서 해당하는 파일: {hit or '없음'}")
            out.append(f"- 규칙이 요구하는 문서: {required}")
            for path in required:
                changed_doc = next((f for f in changed if f['path'] == path), None)
                if changed_doc is not None:
                    out.append(f"  - `{path}`: 이 PR에서 변경됨(위 diff 참고)")
                    continue
                doc = next((f for f in docs if f['path'] == path), None)
                if doc is None:
                    out.append(f"  - `{path}`: 이 PR에서 변경되지 않았고 내용을 수집하지 못함")
                elif hit:
                    out.append(f"  - `{path}`: 이 PR에서 변경되지 않음. PR 커밋 시점 내용 요약 →\n    " + document_summary(doc).replace('\n', '\n    '))
                else:
                    out.append(f"  - `{path}`: 이 PR에서 변경되지 않음(규칙 경로 변경이 없어 내용 요약 생략)")
            out.append(f"- 선택: {', '.join(item['allowed_labels'])}\n")
        for item in items:
            if item['kind'] == 'pr-action':
                out.append(f"**PR 전체** — 항목 `{item['item_id']}` — 선택: pass / warn / fail\n")
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--packet', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    if Path(a.out).exists():
        raise SystemExit(f'{a.out} already exists; outputs are written once')
    Path(a.out).write_text(build(json.loads(Path(a.packet).read_text(encoding='utf-8'))), encoding='utf-8')
    print(a.out)
