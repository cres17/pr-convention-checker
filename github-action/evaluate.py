#!/usr/bin/env python3
"""
Drift Gate 정책 평가기.
.drift-gate.yml을 로드하고 변경 파일에 대해 규칙을 평가한 뒤 결과를 JSON으로 출력.

Usage:
  python3 evaluate.py <policy_path> <changed_files_json> <drift_ignores_json>

  drift_ignores_json: [{"rule_id": "...", "reason": "..." | null}, ...]

Exit codes:
  0 — 정상 완료
  1 — 파일/파싱 오류
  2 — 정책 검증 실패 (require.groups 누락 등)
"""
import sys
import json
import re

try:
    import yaml
except ImportError:
    yaml = None


# ─── YAML 파서 ───────────────────────────────────────────────────────────────

def load_yaml(path):
    if yaml is not None:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    raise RuntimeError("pyyaml이 필요합니다: pip install pyyaml")


# ─── Glob 매처 ───────────────────────────────────────────────────────────────

def glob_to_regex(pattern):
    """
    glob 패턴을 정규식으로 변환.
      **/ → 0개 이상의 디렉토리
      **  → 모든 경로
      *   → 슬래시 제외 모든 문자
      ?   → 슬래시 제외 단일 문자
    """
    regex = ""
    i = 0
    while i < len(pattern):
        if pattern[i:i+3] == "**/":
            regex += "(?:[^/]+/)*"
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
    path = path.lstrip("/")
    pattern = pattern.lstrip("/")
    try:
        return bool(re.fullmatch(glob_to_regex(pattern), path))
    except re.error:
        return False


def matches_any(path, patterns):
    return any(match_glob(path, p) for p in patterns)


# ─── 신뢰도 계산 ──────────────────────────────────────────────────────────────

def pattern_confidence(pattern):
    """
    단일 패턴의 신뢰도를 반환.
      high   — 정확한 경로이거나 단순 디렉토리 glob (dir/**)
      medium — 교차 경로 와일드카드 (**/something/**)
    """
    wildcards = pattern.count("*")
    if wildcards == 0:
        return "high"
    if pattern.endswith("/**") and wildcards == 2:
        return "high"
    return "medium"


def compute_violation_confidence(trigger_files, when_patterns):
    """
    위반의 전체 신뢰도를 trigger_files × when_patterns 조합에서 산출.
    - "other" 유형만 있으면 low
    - 복수 유형이거나 renamed 파일이 있으면 medium
    - 매칭 패턴 신뢰도가 medium이면 medium
    - 그 외 high
    """
    change_types_set = set(
        ct
        for f in trigger_files
        for ct in get_file_change_types(f["path"])
    )
    if not change_types_set or change_types_set == {"other"}:
        return "low"

    has_rename = any(f.get("status") == "renamed" for f in trigger_files)
    if len(change_types_set) > 1 or has_rename:
        return "medium"

    for f in trigger_files:
        for pattern in when_patterns:
            if match_glob(f["path"], pattern) and pattern_confidence(pattern) == "medium":
                return "medium"
    return "high"


# ─── 변경 유형 분류 ───────────────────────────────────────────────────────────

TYPE_PATTERNS = {
    "api-surface": [
        "src/routes/**", "openapi/**", "proto/**",
        "src/controllers/**", "app/controllers/**", "api/**",
    ],
    "db-schema": [
        "db/migrations/**", "prisma/schema.prisma", "sql/**",
        "**/schema.sql", "database/migrations/**", "alembic/versions/**",
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


def get_file_change_types(path):
    """단일 파일 경로에 해당하는 변경 유형 목록을 반환."""
    return [ct for ct, patterns in TYPE_PATTERNS.items() if matches_any(path, patterns)] or ["other"]


def classify_change_types(changed_files):
    """
    전체 변경 파일 목록의 유형을 분류.
    docs-only / test-only 는 모든 파일이 해당 패턴에 속할 때만 반환.
    """
    paths = [f["path"] for f in changed_files]
    if not paths:
        return []

    if all(matches_any(p, DOCS_PATTERNS) for p in paths):
        return ["docs-only"]
    if all(matches_any(p, TEST_PATTERNS) for p in paths):
        return ["test-only"]

    detected = set()
    for p in paths:
        detected.update(get_file_change_types(p))
    return sorted(detected)


# ─── 체크리스트 템플릿 ────────────────────────────────────────────────────────

CHECKLIST_TEMPLATES = {
    "API 계약 문서":  ["관련 spec/API 문서를 변경 내용에 맞게 업데이트"],
    "릴리즈 공지":    ["CHANGELOG.md에 변경 항목 추가"],
    "운영 문서":      ["관련 runbook 또는 운영 문서 업데이트"],
    "샘플 환경변수":  [".env.example에 새 환경변수 반영"],
    "배포 문서":      ["배포 문서에 설정 변경 내용 업데이트"],
    "검증 흔적":      ["관련 integration/e2e 테스트 추가 또는 업데이트"],
    "보안/권한 문서": ["보안 문서 또는 권한 정책 업데이트"],
}


def build_fallback_checklist(unsatisfied_groups):
    """
    불충족 묶음 목록으로부터 결정론적 체크리스트 항목을 생성.
    템플릿에 없는 묶음 이름은 "<이름> 업데이트"로 폴백.
    """
    items = []
    for group in unsatisfied_groups:
        name = group.get("name", "")
        if name in CHECKLIST_TEMPLATES:
            items.extend(CHECKLIST_TEMPLATES[name])
        else:
            required = group.get("required", [])
            desc = required[0] if required else name
            items.append(f"{name or desc} 업데이트")
    return items


# ─── 그룹 평가 ───────────────────────────────────────────────────────────────

def evaluate_group(group, changed_files):
    """
    단일 require 묶음을 평가.
    deleted 상태 파일은 충족으로 간주하지 않는다.
    """
    path_status = {}
    for f in changed_files:
        path_status[f["path"]] = f.get("status", "modified")
        if f.get("previous_path"):
            path_status[f["previous_path"]] = f.get("status", "modified")

    def pattern_satisfied(pattern):
        return any(
            match_glob(path, pattern) and status != "deleted"
            for path, status in path_status.items()
        )

    if "any_changed" in group:
        return any(pattern_satisfied(p) for p in group["any_changed"])
    if "all_changed" in group:
        return all(pattern_satisfied(p) for p in group["all_changed"])
    return False


# ─── 규칙 평가 ───────────────────────────────────────────────────────────────

def evaluate_rules(policy, changed_files, drift_ignores, ignore_paths):
    """
    모든 정책 규칙을 평가.

    drift_ignores: [{"rule_id": "...", "reason": "..." | null}, ...]
    - BLOCKER/MAJOR + reason 있음  → skipped_rules (규칙 생략)
    - BLOCKER/MAJOR + reason 없음  → rejected_ignores에 기록 + 규칙은 정상 평가
    - MINOR/NIT + reason 있음      → skipped_rules
    - MINOR/NIT + reason 없음      → skipped_rules (reason 없어도 허용)

    require.groups 없는 규칙은 정책 오류로 exit 2.
    반환값: (violations, skipped_rules, rejected_ignores)
    """
    rules = policy.get("rules", [])
    violations = []
    skipped_rules = []
    rejected_ignores = []

    # drift_ignores를 rule_id → reason 맵으로 변환
    ignore_map = {d["rule_id"]: d.get("reason") for d in drift_ignores}

    relevant_files = [
        f for f in changed_files
        if not matches_any(f["path"], ignore_paths)
    ]

    for rule in rules:
        rule_id = rule.get("id", "unknown")
        severity = rule.get("severity", "minor").upper()

        # drift-ignore 처리
        if rule_id in ignore_map:
            reason = ignore_map[rule_id]
            if severity in ("BLOCKER", "MAJOR") and not reason:
                # reason 없는 BLOCKER/MAJOR ignore → 거부. 규칙은 계속 평가.
                rejected_ignores.append({
                    "rule_id": rule_id,
                    "severity": severity,
                    "message": rule.get("message", ""),
                })
                # fall through — evaluate this rule normally
            else:
                # reason 있는 BLOCKER/MAJOR 또는 MINOR/NIT (reason 유무 무관)
                skipped_rules.append({
                    "rule_id": rule_id,
                    "severity": severity,
                    "reason": reason or "",
                    "message": rule.get("message", ""),
                })
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
        when_patterns = (rule.get("when") or {}).get("any_changed", [])

        trigger_files = [
            f for f in relevant_files
            if matches_any(f["path"], when_patterns)
            or (f.get("previous_path") and matches_any(f["previous_path"], when_patterns))
        ]

        if not trigger_files:
            continue

        # require.groups 전체 평가
        unsatisfied = [
            {
                "name": g.get("name", ""),
                "required": g.get("any_changed", g.get("all_changed", [])),
                "type": "any_changed" if "any_changed" in g else "all_changed",
            }
            for g in groups
            if not evaluate_group(g, relevant_files)
        ]

        if unsatisfied:
            # 트리거 파일의 변경 유형 산출
            change_types = sorted(set(
                ct
                for f in trigger_files
                for ct in get_file_change_types(f["path"])
            ))
            # 단수형: 첫 번째 유형(대표값)
            change_type = change_types[0] if change_types else "other"

            violations.append({
                "rule_id": rule_id,
                "severity": severity,
                "confidence": compute_violation_confidence(trigger_files, when_patterns),
                "change_types": change_types,
                "change_type": change_type,
                "message": rule.get("message", ""),
                "trigger_files": trigger_files,
                "unsatisfied_groups": unsatisfied,
                "checklist": build_fallback_checklist(unsatisfied),
                "ignored": False,
            })

    return violations, skipped_rules, rejected_ignores


# ─── 메인 ────────────────────────────────────────────────────────────────────

def main():
    policy_path   = sys.argv[1] if len(sys.argv) > 1 else ".drift-gate.yml"
    changed_files = json.loads(sys.argv[2]) if len(sys.argv) > 2 else []
    drift_ignores = json.loads(sys.argv[3]) if len(sys.argv) > 3 else []

    try:
        policy = load_yaml(policy_path)
    except FileNotFoundError:
        print(json.dumps({
            "no_policy": True,
            "change_types": [],
            "violations": [],
            "skipped_rules": [],
            "rejected_ignores": [],
            "gate": {"fail_on_blocker": True, "fail_on_major_count": 2},
        }))
        return
    except Exception as e:
        print(f"ERROR: 정책 파일 파싱 실패: {e}", file=sys.stderr)
        sys.exit(1)

    ignore_paths = policy.get("ignore_paths", [])
    gate = policy.get("gate", {"fail_on_blocker": True, "fail_on_major_count": 2})

    change_types = classify_change_types(changed_files)

    # docs-only / test-only → 평가 생략
    if change_types and change_types[0] in ("docs-only", "test-only"):
        print(json.dumps({
            "skip": True,
            "reason": change_types[0],
            "change_types": change_types,
            "violations": [],
            "skipped_rules": [],
            "rejected_ignores": [],
            "gate": gate,
        }))
        return

    violations, skipped_rules, rejected_ignores = evaluate_rules(
        policy, changed_files, drift_ignores, ignore_paths
    )

    print(json.dumps({
        "change_types": change_types,
        "violations": violations,
        "skipped_rules": skipped_rules,
        "rejected_ignores": rejected_ignores,
        "gate": gate,
    }))


if __name__ == "__main__":
    main()
