"""Removed-key duties. Repository observations are supplied by adapters only."""
import re

from drift_gate.core.evaluation.content_result import ContentCheck, combine
from drift_gate.core.evaluation.environment import environment_delta, environment_facts
from drift_gate.core.patch_lines import changed_lines
from drift_gate.utils.glob_matcher import matches_any


def js_environment_keys(source):
    """Conservative literal process.env reads; comments/strings are never code.

    Templates, rebinding or shadowing of process cannot establish a live use.
    This is a small lexical profile, not a general JavaScript interpreter.
    """
    tokens = re.findall(r'//[^\n]*|/\*[\s\S]*?\*/|/(?:\\.|[^/\n\\])+/[a-z]*|`(?:\\.|[^`])*`|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[A-Za-z_$][\w$]*|[^\s]', source)
    tokens = [t for t in tokens if not t.startswith(('//', '/*'))]
    # A locally declared process (including a parameter) is not Node's global.
    if re.search(r'\b(?:const|let|var|function|class|import)\s+process\b|[,(]\s*process\s*[,)=:]|\bprocess\s*=(?!=)', ' '.join(tokens)):
        return set()
    keys = set()
    for i in range(len(tokens)-4):
        if tokens[i:i+3] != ['process', '.', 'env'] or i and tokens[i-1] in {'.', '?.'}:
            continue
        if tokens[i+3] == '.' and re.fullmatch(r'[A-Z][A-Z0-9_]*', tokens[i+4]):
            keys.add(tokens[i+4])
        elif i+5 < len(tokens) and tokens[i+3] == '[' and tokens[i+5] == ']':
            literal = tokens[i+4]
            if len(literal) >= 2 and literal[0] in "\"'" and literal[-1] == literal[0] and re.fullmatch(r'[A-Z][A-Z0-9_]*', literal[1:-1]):
                keys.add(literal[1:-1])
    return keys


def removed_environment_keys(files):
    before, after = set(), set()
    for file in files:
        if file.removed_env_key_candidates is not None:
            before.update(file.removed_env_key_candidates)
            continue
        if not file.path.endswith(('.py', '.js', '.jsx', '.ts', '.tsx')):
            continue
        complete = ((file.status == 'added' or file.before_source is not None)
                    and (file.status == 'deleted' or file.after_source is not None))
        if complete:
            old = '' if file.status == 'added' else file.before_source
            new = '' if file.status == 'deleted' else file.after_source
        else:
            lines = changed_lines(file)
            old = '\n'.join(s for mark, s in lines if mark == '-')
            new = '\n'.join(s for mark, s in lines if mark == '+')
        if file.path.endswith('.py'):
            before.update(environment_facts(old, fragment=not complete).keys)
            after.update(environment_facts(new, fragment=not complete).keys)
        else:
            before.update(js_environment_keys(old))
            after.update(js_environment_keys(new))
    return before - after


def guidance(key):
    return (f'저장소 밖에서 사용하는 키라면 exclude_removed_keys: [{key}]로 키 하나만 예외로 두세요(권장). '
            '전체 검사를 끄려면 check_removed_keys: false를 설정하세요. 두 변경은 정책 약화로 기록됩니다.')


def environment_requirement(group, triggers, files, session=None):
    from drift_gate.core.evaluation.contracts import added_environment_requirement
    policy = getattr(session, 'policy', None)
    keys = removed_environment_keys(triggers)
    if not getattr(policy, 'check_removed_keys', True):
        keys = set()
    keys -= set(getattr(policy, 'exclude_removed_keys', []))
    facts = environment_delta(triggers)
    # A deletion-only patch has no added-key duty. Lack of repository evidence
    # belongs to advisories, not to gate.on_unverified.
    added = (ContentCheck('satisfied', 'not-applicable', 'No added environment key in deletion-only change', 'env-keys')
             if keys and not facts.keys and not facts.uncertain
             else added_environment_requirement(group, triggers, files))
    if not keys:
        return added
    patterns = group.any_changed or group.all_changed
    docs = [f for f in files if matches_any(f.path, patterns)]
    warnings, stale, reasons = [], set(), []
    complete_sources = all((f.status == 'added' or f.before_source is not None)
                           and (f.status == 'deleted' or f.after_source is not None)
                           and (f.path.endswith('.py') or f.removed_env_key_candidates is not None) for f in triggers)
    for key in sorted(keys):
        retained = sorted(f.path for f in docs if f.status != "deleted" and key in (f.documented_env_keys or []))
        uncertain_docs = not docs or any(f.documented_env_keys is None for f in docs)
        if not retained and not uncertain_docs:
            continue
        evidence = next((f.env_key_usage[key] for f in triggers if f.env_key_usage and key in f.env_key_usage), None)
        state = evidence.get('state') if evidence else 'incomplete'
        paths = tuple(evidence.get('paths', ())) if evidence else ()
        if state == 'code':
            continue
        if state == 'absent' and complete_sources and not uncertain_docs:
            stale.add(key)
            reasons.append(f'{key}: 코드에서 제거됐는데 문서에 남음 ({", ".join(retained)}). {guidance(key)}')
            continue
        if not retained:
            kind, detail = 'incomplete', '환경 변수 문서 전체를 확인하지 못함'
        elif state == 'config':
            kind, detail = 'config', f'{", ".join(paths)}에서 환경 변수 형태로 사용 중으로 보임; 문서 유지 여부 확인'
        elif state == 'mention':
            kind, detail = 'mention', f'{", ".join(paths)}에서 이름만 발견됨; 사용 여부 판단 불가'
        else:
            kind, detail = 'incomplete', '저장소 전체 또는 제거 전후 소스를 확인하지 못함'
        warnings.append({'key': key, 'kind': kind, 'paths': paths,
                         'message': f'{key}: {detail}. {guidance(key)}'})
    removal = ContentCheck('violated' if stale else 'satisfied', 'verified' if stale else 'not-applicable',
                           '; '.join(reasons) or 'Removed-key findings are clear or require advisory review', 'env-keys')
    combined = combine([added, removal], require_all=True, mode='env-keys')
    return ContentCheck(combined.decision, combined.verification, combined.reason, 'env-keys',
                        tuple(warnings), tuple(sorted(stale)))
