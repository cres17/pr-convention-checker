#!/usr/bin/env python3
"""
Drift Gate 정책 평가기.
.drift-gate.yml을 로드하고 변경 파일에 대해 규칙을 평가한 뒤 결과를 JSON으로 출력.

Usage:
  python3 evaluate.py <policy_path> <changed_files_json> <ignored_rules_json>
"""
import sys
import json
import re

try:
    import yaml
except ImportError:
    # yaml 없으면 간단한 폴백 파서 사용
    yaml = None


# ─── YAML 파서 ───────────────────────────────────────────────────────────────

def load_yaml(path):
    if yaml is not None:
        with open(path) as f:
            return yaml.safe_load(f)
    # 폴백: pyyaml 없는 환경 (GitHub Actions에는 기본 설치됨)
    raise RuntimeError("pyyaml이 필요합니다. pip install pyyaml")


# ─── Glob 매처 ───────────────────────────────────────────────────────────────

def glob_to_regex(pattern):
    """
    glob 패턴을 정규식으로 변환.
    - **/ : 0개 이상의 디렉토리 (포함 없음도 매칭)
    - **  : 어떤 경로든
    - *   : 슬래시 제외 모든 문자
    - ?   : 슬래시 제외 단일 문자
    """
    regex = ""
    i = 0
    while i < len(pattern):
        if pattern[i:i+3] == "**/":
            regex += "(?:[^/]+/)* "
            regex = regex.replace("(?:[^/]+/)* ", "(?:[^/]+/)*")
            i += 3
        elif pattern[i:i+2] == "**":
            regex += ".*"
            i += 2
        elif pattern[i] == "*":
            regex += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            regex += "[^/]"
            i += 1
        elif pattern[i] in ".+^${}[]|()":
            regex += re.escape(pattern[i])
            i += 1
        else:
            regex += pattern[i]
            i += 1
    return regex


def match_glob(path, pattern):
    """경로가 glob 패턴과 매칭되는지 확인."""
    path = path.lstrip("/")
    pattern = pattern.lstrip("/")

    try:
        regex = glob_to_regex(pattern)
        return bool(re.fullmatch(regex, path))
    except re.error:
        return False


def matches_any(path, patterns):
    """경로가 패턴 목록 중 하나라도 매칭되면 True."""
    for pattern in patterns:
        if match_glob(path, pattern):
            return True
    return False


# ─── 변경 유형 분류 ───────────────────────────────────────────────────────────

TYPE_PATTERNS = {
    "api-surface": [
        "src/routes/**", "openapi/**", "proto/**",
        "src/controllers/**", "app/controllers/**", "api/**",
    ],
    "db-schema": [
        "db/migrations/**", "prisma/schema.prisma", "sql/**",
        "**/schema.sql", "database/migrations/**", "alembic/**",
    ],
    "env-config": [
        ".env", ".env.local", ".env.production", ".env.staging",
        "config/**", "src/config/**", "**/settings.py", "**/config.py",
    ],
    "workflow-ci": [
        ".github/workflows/**", "Dockerfile", "Dockerfile.*",
        "infra/**", "terraform/**", "k8s/**", "helm/**",
    ],
    "auth-permission": [
        "**/auth/**", "**/middleware/auth*", "**/rbac/**",
        "**/permissions/**", "**/policy/**",
    ],
}

DOCS_PATTERNS = ["docs/**", "**/*.md", "**/*.rst"]
TEST_PATTERNS = ["tests/**", "**/*.test.*", "**/*.spec.*", "test/**", "__tests__/**"]


def classify_change_types(changed_files):
    """
    변경 파일 목록에서 변경 유형을 분류.
    docs-only / test-only는 모든 파일이 해당 패턴에 속할 때만 반환.
    """
    paths = [f["path"] for f in changed_files]
    if not paths:
        return []

    # docs-only 판정: 모든 파일이 문서 패턴
    if all(matches_any(p, DOCS_PATTERNS) for p in paths):
        return ["docs-only"]

    # test-only 판정: 모든 파일이 테스트 패턴
    if all(matches_any(p, TEST_PATTERNS) for p in paths):
        return ["test-only"]

    # 일반 유형 분류
    detected = set()
    for path in paths:
        for change_type, patterns in TYPE_PATTERNS.items():
            if matches_any(path, patterns):
                detected.add(change_type)

    return sorted(detected) if detected else ["other"]


# ─── 그룹 평가 ───────────────────────────────────────────────────────────────

def evaluate_group(group, changed_files):
    """
    단일 require 묶음을 평가.
    - any_changed: 묶음 내 경로 중 하나라도 변경(삭제 제외)되면 충족
    - all_changed: 묶음 내 경로가 모두 변경(삭제 제외)되어야 충족
    """
    # 파일 경로 → 상태 맵 구성 (rename 전후 경로 모두 포함)
    path_status = {}
    for f in changed_files:
        path_status[f["path"]] = f.get("status", "modified")
        prev = f.get("previous_path")
        if prev:
            path_status[prev] = f.get("status", "modified")

    def is_valid_change(path):
        """경로가 삭제가 아닌 변경으로 존재하면 True."""
        return path_status.get(path) != "deleted"

    def path_matches_pattern(pattern):
        """패턴과 매칭되고 유효한 변경 파일이 존재하면 True."""
        for path, status in path_status.items():
            if match_glob(path, pattern) and status != "deleted":
                return True
        return False

    if "any_changed" in group:
        return any(path_matches_pattern(p) for p in group["any_changed"])

    if "all_changed" in group:
        return all(path_matches_pattern(p) for p in group["all_changed"])

    return False


# ─── 규칙 평가 ───────────────────────────────────────────────────────────────

def evaluate_rules(policy, changed_files, ignored_rules, ignore_paths):
    """
    모든 정책 규칙을 평가하고 위반 목록을 반환.
    require.groups가 없는 규칙은 정책 오류로 즉시 종료.
    """
    rules = policy.get("rules", [])
    violations = []

    # ignore_paths 적용
    relevant_files = [
        f for f in changed_files
        if not matches_any(f["path"], ignore_paths)
    ]

    for rule in rules:
        rule_id = rule.get("id", "unknown")

        # drift-ignore 처리
        if rule_id in ignored_rules:
            continue

        # require.groups 검증
        require = rule.get("require") or {}
        groups = require.get("groups", [])
        if not groups:
            print(
                f"ERROR: rule '{rule_id}'에 require.groups가 없습니다. "
                "require.groups는 최소 1개 이상의 묶음을 정의해야 합니다.",
                file=sys.stderr,
            )
            sys.exit(2)

        # when 조건 확인
        when = rule.get("when") or {}
        when_patterns = when.get("any_changed", [])

        triggered_files = []
        for f in relevant_files:
            path = f["path"]
            prev = f.get("previous_path") or ""
            if matches_any(path, when_patterns) or (prev and matches_any(prev, when_patterns)):
                triggered_files.append(f)

        if not triggered_files:
            continue

        # require.groups 전체 평가
        unsatisfied = []
        for group in groups:
            if not evaluate_group(group, relevant_files):
                unsatisfied.append({
                    "name": group.get("name", ""),
                    "required": group.get("any_changed", group.get("all_changed", [])),
                    "type": "any_changed" if "any_changed" in group else "all_changed",
                })

        if unsatisfied:
            violations.append({
                "rule_id": rule_id,
                "severity": rule.get("severity", "minor").upper(),
                "message": rule.get("message", ""),
                "trigger_files": triggered_files,
                "unsatisfied_groups": unsatisfied,
                "ignored": False,
            })

    return violations


# ─── 메인 ────────────────────────────────────────────────────────────────────

def main():
    policy_path = sys.argv[1] if len(sys.argv) > 1 else ".drift-gate.yml"
    changed_files = json.loads(sys.argv[2]) if len(sys.argv) > 2 else []
    ignored_rules = set(json.loads(sys.argv[3])) if len(sys.argv) > 3 else set()

    # 정책 파일 로드
    try:
        policy = load_yaml(policy_path)
    except FileNotFoundError:
        print(json.dumps({
            "no_policy": True,
            "change_types": [],
            "violations": [],
            "gate": {"fail_on_blocker": True, "fail_on_major_count": 2},
        }))
        return
    except Exception as e:
        print(f"ERROR: 정책 파일 파싱 실패: {e}", file=sys.stderr)
        sys.exit(1)

    ignore_paths = policy.get("ignore_paths", [])
    gate = policy.get("gate", {"fail_on_blocker": True, "fail_on_major_count": 2})

    # 변경 유형 분류
    change_types = classify_change_types(changed_files)

    # docs-only / test-only → 드리프트 평가 생략
    if change_types and change_types[0] in ("docs-only", "test-only"):
        print(json.dumps({
            "skip": True,
            "reason": change_types[0],
            "change_types": change_types,
            "violations": [],
            "gate": gate,
        }))
        return

    # 규칙 평가
    violations = evaluate_rules(policy, changed_files, ignored_rules, ignore_paths)

    print(json.dumps({
        "change_types": change_types,
        "violations": violations,
        "gate": gate,
    }))


if __name__ == "__main__":
    main()
