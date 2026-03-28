"""
evaluate.py 단위 테스트 — 7개 시나리오

실행:
  cd <repo-root>
  python3 -m pytest tests/test_evaluate.py -v
"""
import json
import sys
import os
import tempfile
import pytest

# evaluate.py가 github-action/ 디렉토리에 있으므로 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "github-action"))
import evaluate  # noqa: E402


# ─── 픽스처 헬퍼 ─────────────────────────────────────────────────────────────

def make_policy(rules, gate=None, ignore_paths=None):
    """테스트용 정책 딕셔너리를 생성."""
    p = {"rules": rules}
    if gate:
        p["gate"] = gate
    if ignore_paths:
        p["ignore_paths"] = ignore_paths
    return p


def make_rule(rule_id, when_patterns, groups, severity="major", message="test"):
    return {
        "id": rule_id,
        "when": {"any_changed": when_patterns},
        "require": {"groups": groups},
        "severity": severity,
        "message": message,
    }


def make_group(name, any_changed=None, all_changed=None):
    g = {"name": name}
    if any_changed is not None:
        g["any_changed"] = any_changed
    if all_changed is not None:
        g["all_changed"] = all_changed
    return g


def run_main(policy_path, changed_files, drift_ignores=None):
    """evaluate.main()을 인자 패치로 호출해 stdout JSON을 반환."""
    if drift_ignores is None:
        drift_ignores = []
    old_argv = sys.argv
    sys.argv = [
        "evaluate.py",
        policy_path,
        json.dumps(changed_files),
        json.dumps(drift_ignores),
    ]
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            evaluate.main()
    finally:
        sys.argv = old_argv
    return json.loads(buf.getvalue())


def write_policy(policy_dict):
    """임시 YAML 정책 파일을 작성하고 경로를 반환 (with 블록에서 사용)."""
    import yaml  # pyyaml 필요
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yml", delete=False, encoding="utf-8"
    )
    yaml.dump(policy_dict, f, allow_unicode=True)
    f.close()
    return f.name


# ─── 시나리오 1: docs-only PR → 평가 생략 ───────────────────────────────────

def test_docs_only_skip():
    policy = make_policy(rules=[
        make_rule("api-contract-sync", ["src/routes/**"],
                  [make_group("API 문서", any_changed=["docs/spec.md"])],
                  severity="blocker"),
    ])
    changed_files = [
        {"path": "docs/spec.md", "status": "modified"},
        {"path": "README.md",    "status": "modified"},
    ]
    policy_path = write_policy(policy)
    try:
        result = run_main(policy_path, changed_files)
    finally:
        os.unlink(policy_path)

    assert result.get("skip") is True
    assert result.get("reason") == "docs-only"
    assert result["violations"] == []


# ─── 시나리오 2: test-only PR → 평가 생략 ───────────────────────────────────

def test_test_only_skip():
    policy = make_policy(rules=[
        make_rule("schema-migration-proof", ["db/migrations/**"],
                  [make_group("운영 문서", any_changed=["docs/runbook.md"])]),
    ])
    changed_files = [
        {"path": "tests/integration/test_db.py", "status": "added"},
    ]
    policy_path = write_policy(policy)
    try:
        result = run_main(policy_path, changed_files)
    finally:
        os.unlink(policy_path)

    assert result.get("skip") is True
    assert result.get("reason") == "test-only"
    assert result["violations"] == []


# ─── 시나리오 3: require.groups 없는 규칙 → exit 2 ──────────────────────────

def test_missing_require_groups_exits_2():
    policy = make_policy(rules=[
        {
            "id": "bad-rule",
            "when": {"any_changed": ["src/routes/**"]},
            "require": {},   # groups 없음
            "severity": "blocker",
            "message": "broken",
        }
    ])
    changed_files = [{"path": "src/routes/user.py", "status": "modified"}]
    policy_path = write_policy(policy)
    try:
        with pytest.raises(SystemExit) as exc_info:
            run_main(policy_path, changed_files)
        assert exc_info.value.code == 2
    finally:
        os.unlink(policy_path)


# ─── 시나리오 4: 위반 생성 — groups 불충족 ──────────────────────────────────

def test_violation_generated_when_groups_unsatisfied():
    policy = make_policy(rules=[
        make_rule(
            "api-contract-sync",
            ["src/routes/**"],
            [
                make_group("API 계약 문서", any_changed=["docs/spec.md", "docs/api/**"]),
                make_group("릴리즈 공지",   all_changed=["CHANGELOG.md"]),
            ],
            severity="blocker",
            message="API surface changed without docs",
        )
    ])
    # src/routes/ 변경, 하지만 docs/spec.md나 CHANGELOG.md는 없음
    changed_files = [
        {"path": "src/routes/user.py", "status": "modified"},
    ]
    policy_path = write_policy(policy)
    try:
        result = run_main(policy_path, changed_files)
    finally:
        os.unlink(policy_path)

    assert len(result["violations"]) == 1
    v = result["violations"][0]
    assert v["rule_id"] == "api-contract-sync"
    assert v["severity"] == "BLOCKER"
    assert "change_type" in v             # 단수형 필드 존재
    assert isinstance(v["change_types"], list)
    assert len(v["checklist"]) > 0        # fallback checklist
    assert isinstance(v["trigger_files"], list)
    assert len(v["unsatisfied_groups"]) == 2


# ─── 시나리오 5: BLOCKER + reason → skipped_rules에 기록 ────────────────────

def test_blocker_drift_ignore_with_reason_is_skipped():
    policy = make_policy(rules=[
        make_rule(
            "api-contract-sync",
            ["src/routes/**"],
            [make_group("API 계약 문서", any_changed=["docs/spec.md"])],
            severity="blocker",
        )
    ])
    changed_files = [{"path": "src/routes/user.py", "status": "modified"}]
    drift_ignores = [{"rule_id": "api-contract-sync", "reason": "internal refactor only"}]

    policy_path = write_policy(policy)
    try:
        result = run_main(policy_path, changed_files, drift_ignores)
    finally:
        os.unlink(policy_path)

    assert result["violations"] == []
    assert len(result["skipped_rules"]) == 1
    assert result["skipped_rules"][0]["rule_id"] == "api-contract-sync"
    assert result["skipped_rules"][0]["reason"] == "internal refactor only"
    assert result["rejected_ignores"] == []


# ─── 시나리오 6: BLOCKER + reason 없음 → rejected_ignores + 위반 유지 ────────

def test_blocker_drift_ignore_without_reason_is_rejected():
    policy = make_policy(rules=[
        make_rule(
            "api-contract-sync",
            ["src/routes/**"],
            [make_group("API 계약 문서", any_changed=["docs/spec.md"])],
            severity="blocker",
        )
    ])
    changed_files = [{"path": "src/routes/user.py", "status": "modified"}]
    drift_ignores = [{"rule_id": "api-contract-sync", "reason": None}]

    policy_path = write_policy(policy)
    try:
        result = run_main(policy_path, changed_files, drift_ignores)
    finally:
        os.unlink(policy_path)

    # 위반이 violations에 남아 있어야 함
    assert len(result["violations"]) == 1
    assert result["violations"][0]["rule_id"] == "api-contract-sync"

    # rejected_ignores에 기록
    assert len(result["rejected_ignores"]) == 1
    assert result["rejected_ignores"][0]["rule_id"] == "api-contract-sync"
    assert result["rejected_ignores"][0]["severity"] == "BLOCKER"

    # skipped_rules에는 없음
    assert result["skipped_rules"] == []


# ─── 시나리오 7: JSON 스키마 필드 검증 ──────────────────────────────────────

def test_json_schema_fields():
    policy = make_policy(rules=[
        make_rule(
            "env-config-sync",
            ["config/**"],
            [
                make_group("샘플 환경변수", all_changed=[".env.example"]),
                make_group("운영 문서",     any_changed=["docs/runbook.md"]),
            ],
            severity="major",
        )
    ])
    changed_files = [{"path": "config/settings.py", "status": "modified"}]

    policy_path = write_policy(policy)
    try:
        result = run_main(policy_path, changed_files)
    finally:
        os.unlink(policy_path)

    assert len(result["violations"]) == 1
    v = result["violations"][0]

    # 필수 필드 존재
    for field in ("rule_id", "severity", "confidence", "change_types",
                  "change_type", "message", "trigger_files",
                  "unsatisfied_groups", "checklist", "ignored"):
        assert field in v, f"필드 누락: {field}"

    # confidence는 high/medium/low 중 하나
    assert v["confidence"] in ("high", "medium", "low")

    # change_type은 change_types의 첫 번째 요소
    assert v["change_type"] == v["change_types"][0]

    # checklist는 비어 있지 않음 (샘플 환경변수 + 운영 문서 모두 불충족)
    assert len(v["checklist"]) >= 2

    # trigger_files는 경로/상태가 있는 객체
    tf = v["trigger_files"][0]
    assert "path" in tf
    assert "status" in tf

    # 최상위 필드
    assert "change_types" in result
    assert "skipped_rules" in result
    assert "rejected_ignores" in result
    assert "gate" in result
