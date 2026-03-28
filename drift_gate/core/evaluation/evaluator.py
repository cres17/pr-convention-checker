"""
규칙 평가 엔진 — 순수 함수. I/O 없음.
"""
from typing import List, Tuple

from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.policy import Policy, Rule, Group
from drift_gate.core.models.result import (
    Violation, UnsatisfiedGroup, SkippedRule, RejectedIgnore,
    DriftIgnoreDirective,
)
from drift_gate.core.classification.classifier import get_file_change_types
from drift_gate.core.reasoning.checklist import build_fallback_checklist
from drift_gate.utils.glob_matcher import matches_any, match_glob, pattern_confidence


def evaluate(
    policy: Policy,
    changed_files: List[ChangedFile],
    drift_ignores: List[DriftIgnoreDirective],
) -> Tuple[List[Violation], List[SkippedRule], List[RejectedIgnore]]:
    """
    모든 정책 규칙을 평가.
    반환: (violations, skipped_rules, rejected_ignores)
    """
    ignore_map = {d.rule_id: d.reason for d in drift_ignores}

    relevant_files = [
        f for f in changed_files
        if not matches_any(f.path, policy.ignore_paths)
    ]

    violations: List[Violation] = []
    skipped_rules: List[SkippedRule] = []
    rejected_ignores: List[RejectedIgnore] = []

    for rule in policy.rules:
        rule_id = rule.id
        severity = rule.severity.upper()

        # drift-ignore 처리
        if rule_id in ignore_map:
            reason = ignore_map[rule_id]
            if severity in ("BLOCKER", "MAJOR") and not reason:
                rejected_ignores.append(RejectedIgnore(
                    rule_id=rule_id, severity=severity, message=rule.message,
                ))
                # fall through — 규칙 정상 평가 유지
            else:
                skipped_rules.append(SkippedRule(
                    rule_id=rule_id, severity=severity,
                    reason=reason or "", message=rule.message,
                ))
                continue

        when_patterns = rule.when.any_changed

        trigger_files = [
            f for f in relevant_files
            if matches_any(f.path, when_patterns)
            or (f.previous_path and matches_any(f.previous_path, when_patterns))
        ]

        if not trigger_files:
            continue

        unsatisfied = [
            UnsatisfiedGroup(
                name=g.name,
                required=g.any_changed or g.all_changed,
                type="any_changed" if g.any_changed else "all_changed",
            )
            for g in rule.require.groups
            if not _evaluate_group(g, relevant_files)
        ]

        if unsatisfied:
            change_types = sorted(set(
                ct
                for f in trigger_files
                for ct in get_file_change_types(f.path)
            ))
            change_type = change_types[0] if change_types else "other"

            violations.append(Violation(
                rule_id=rule_id,
                severity=severity,
                confidence=_compute_confidence(trigger_files, when_patterns),
                change_types=change_types,
                change_type=change_type,
                message=rule.message,
                trigger_files=trigger_files,
                unsatisfied_groups=unsatisfied,
                checklist=build_fallback_checklist(unsatisfied),
                ignored=False,
            ))

    return violations, skipped_rules, rejected_ignores


def _evaluate_group(group: Group, changed_files: List[ChangedFile]) -> bool:
    """그룹 요구 조건 평가. deleted 상태 파일은 충족으로 보지 않음."""
    path_status = {}
    for f in changed_files:
        path_status[f.path] = f.status
        if f.previous_path:
            path_status[f.previous_path] = f.status

    def satisfied(pattern: str) -> bool:
        return any(
            match_glob(p, pattern) and s != "deleted"
            for p, s in path_status.items()
        )

    if group.any_changed:
        return any(satisfied(p) for p in group.any_changed)
    if group.all_changed:
        return all(satisfied(p) for p in group.all_changed)
    return False


def _compute_confidence(
    trigger_files: List[ChangedFile],
    when_patterns: List[str],
) -> str:
    change_types_set = set(
        ct for f in trigger_files for ct in get_file_change_types(f.path)
    )
    if not change_types_set or change_types_set == {"other"}:
        return "low"

    has_rename = any(f.status == "renamed" for f in trigger_files)
    if len(change_types_set) > 1 or has_rename:
        return "medium"

    for f in trigger_files:
        for p in when_patterns:
            if match_glob(f.path, p) and pattern_confidence(p) == "medium":
                return "medium"
    return "high"
