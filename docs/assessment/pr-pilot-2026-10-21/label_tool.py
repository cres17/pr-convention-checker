"""검토 packet에서 label 작성용 단일 HTML 도구를 만든다. 엔진 출력은 읽지 않는다 (protocol-v3).

  python label_tool.py --packet packet.json --out label-tool.html

만든 HTML은 외부 의존성이 없고 브라우저에서 파일로 열면 된다. 한 항목씩 문제·설명·볼 곳·선택지를 보여 주고,
답은 브라우저 저장소에 자동 저장하며 JSONL(`item_id`, `reviewer_id`, `reviewer_kind`, `label`, `rationale`)로 내보낸다.
도구가 보여 주는 내용은 packet(규칙, 변경 파일, 요구 문서 원문)과 규칙 경로의 glob 비교뿐이다.
`policy_gate`와 동결 기대값은 packet에 없고 이 도구에도 넣지 않는다.
"""
import argparse
import json
import sys
from hashlib import sha256
from pathlib import Path

from review_sheet import KEY_LINE, openapi_routes

from drift_gate.utils.glob_matcher import matches_any

LONG_DOCUMENT_LINES = 150


def document_lines(file):
    """요구 문서의 PR 커밋 시점 내용을 (설명, 줄 목록)으로 요약한다. review_sheet.document_summary와 같은 기준이다."""
    text = file.get('after_source')
    if text is None:
        return '내용을 수집하지 못함(없거나 1MB 초과 또는 바이너리)', []
    routes = openapi_routes(text) if file['path'].endswith('.json') else None
    if routes is not None:
        return f'API 경로 {len(routes)}개', routes
    lines = text.splitlines()
    if len(lines) > LONG_DOCUMENT_LINES:
        keys = [line for line in lines if KEY_LINE.match(line)]
        return f'원문이 길어 키처럼 보이는 줄만 표시({len(keys)}줄)', keys
    return f'원문 {len(lines)}줄', lines


def build_data(packet, packet_sha256):
    by_case = {}
    for item in packet['items']:
        by_case.setdefault(item['case_id'], []).append(item)
    cases = []
    for case_id, items in by_case.items():
        files = items[0]['changed_files']
        changed = [f for f in files if f.get('status') != 'unchanged']
        unchanged = {f['path']: f for f in files if f.get('status') == 'unchanged'}
        case_items = []
        for item in (i for i in items if i['kind'] == 'rule'):
            rule = item['rule']
            patterns = rule['when']['any_changed']
            required = sorted({p for g in rule['require']['groups'] for p in (g.get('all_changed') or g.get('any_changed') or [])})
            docs = []
            for path in required:
                if any(f['path'] == path for f in changed):
                    docs.append({'path': path, 'state': 'changed'})
                elif path in unchanged:
                    note, lines = document_lines(unchanged[path])
                    docs.append({'path': path, 'state': 'unchanged', 'note': note, 'lines': lines})
                else:
                    docs.append({'path': path, 'state': 'missing'})
            case_items.append({
                'item_id': item['item_id'], 'kind': 'rule', 'rule_id': rule['id'], 'message': rule.get('message', ''),
                'patterns': patterns, 'hit': [f['path'] for f in changed if matches_any(f['path'], patterns)],
                'docs': docs, 'allowed_labels': item['allowed_labels']})
        for item in (i for i in items if i['kind'] == 'pr-action'):
            case_items.append({'item_id': item['item_id'], 'kind': 'pr-action', 'allowed_labels': item['allowed_labels']})
        cases.append({
            'case_id': case_id,
            'files': [{'path': f['path'], 'status': f['status'], 'previous_path': f.get('previous_path'),
                       'patch': f.get('patch') or ''} for f in changed],
            'items': case_items})
    return {'meta': {'packet_sha256': packet_sha256, 'protocol': packet.get('protocol', ''),
                     'frozen_sha256': packet.get('frozen_sha256', ''), 'item_count': len(packet['items'])},
            'cases': cases}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--packet', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args(argv)
    out = Path(args.out)
    if out.exists():
        raise SystemExit(f'{out} already exists; outputs are written once')
    raw = Path(args.packet).read_bytes()
    data = build_data(json.loads(raw), sha256(raw).hexdigest())
    payload = json.dumps(data, ensure_ascii=False).replace('</', '<\\/').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    template = (Path(__file__).with_name('label_tool.template.html')).read_text(encoding='utf-8')
    out.write_text(template.replace('__DATA__', payload), encoding='utf-8')
    print(out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
