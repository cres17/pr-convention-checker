"""
규칙 평가 엔진 — 순수 함수. I/O 없음.
"""
from datetime import date
from typing import List, Tuple

from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.policy import Policy, Group, CrossFileRelation
from drift_gate.core.models.result import (
    Violation, UnsatisfiedGroup, SatisfiedGroup, RuleDecision,
    SkippedRule, RejectedIgnore, IgnoreAuditEntry,
    DriftIgnoreDirective,
)
from drift_gate.core.classification.classifier import get_file_change_types
from drift_gate.core.classification.intensity import (
    classify_file_intensity,
    max_intensity,
    meets_min_intensity,
)
from drift_gate.core.reasoning.checklist import build_fallback_checklist
from drift_gate.utils.glob_matcher import matches_any, match_glob, pattern_confidence


def evaluate(
    policy: Policy,
    changed_files: List[ChangedFile],
    drift_ignores: List[DriftIgnoreDirective],
) -> Tuple[List[Violation], List[SkippedRule], List[RejectedIgnore], List[RuleDecision], List[IgnoreAuditEntry]]:
    """
    모든 정책 규칙을 평가.
    반환: (violations, skipped_rules, rejected_ignores)
    """
    ignore_map = {d.rule_id: d for d in drift_ignores}

    relevant_files = [
        f for f in changed_files
        if not matches_any(f.path, policy.ignore_paths)
    ]

    violations: List[Violation] = []
    skipped_rules: List[SkippedRule] = []
    rejected_ignores: List[RejectedIgnore] = []
    rule_decisions: List[RuleDecision] = []
    ignore_audit: List[IgnoreAuditEntry] = []

    for rule in policy.rules:
        rule_id = rule.id
        severity = rule.severity.upper()

        # drift-ignore 처리
        if rule_id in ignore_map:
            directive = ignore_map[rule_id]
            rejection_reason = _ignore_rejection_reason(directive, rule, policy)
            if rejection_reason:
                rejected_ignores.append(RejectedIgnore(
                    rule_id=rule_id,
                    severity=severity,
                    message=rule.message,
                    reason=rejection_reason,
                ))
                ignore_audit.append(IgnoreAuditEntry(
                    rule_id=rule_id,
                    action="rejected",
                    reason=rejection_reason,
                    approved_by=directive.approved_by,
                    expires=directive.expires,
                ))
                # fall through — 규칙 정상 평가 유지
            else:
                skipped_rules.append(SkippedRule(
                    rule_id=rule_id, severity=severity,
                    reason=directive.reason or "", message=rule.message,
                ))
                ignore_audit.append(IgnoreAuditEntry(
                    rule_id=rule_id,
                    action="accepted",
                    reason=directive.reason or "",
                    approved_by=directive.approved_by,
                    expires=directive.expires,
                ))
                rule_decisions.append(RuleDecision(
                    rule_id=rule_id,
                    severity=severity,
                    status="skipped",
                    reason=directive.reason or "drift-ignore accepted",
                ))
                continue

        when_patterns = rule.when.any_changed

        trigger_files = [
            f for f in relevant_files
            if matches_any(f.path, when_patterns)
            or (f.previous_path and matches_any(f.previous_path, when_patterns))
        ]
        min_intensity = rule.when.min_change_intensity
        if min_intensity and min_intensity != "any":
            trigger_files = [
                f for f in trigger_files
                if meets_min_intensity(classify_file_intensity(f), min_intensity)
            ]

        if not trigger_files:
            rule_decisions.append(RuleDecision(
                rule_id=rule_id,
                severity=severity,
                status="unmatched",
                reason="no changed files matched this rule after ignore paths and intensity filters",
            ))
            continue

        satisfied, unsatisfied = _evaluate_groups(
            [group for group in rule.require.groups if group.required],
            relevant_files,
        )
        relation_satisfied, relation_unsatisfied, relation_names = (
            _evaluate_cross_file_relations(
                rule.require.cross_file,
                rule.require.groups,
                relevant_files,
            )
        )
        satisfied.extend(relation_satisfied)
        unsatisfied.extend(relation_unsatisfied)
        matched_patterns = _matched_patterns(trigger_files, when_patterns)

        if unsatisfied:
            change_types = sorted(set(
                ct
                for f in trigger_files
                for ct in get_file_change_types(f.path)
            ))
            change_type = change_types[0] if change_types else "other"
            change_intensities = sorted(set(
                classify_file_intensity(f) for f in trigger_files
            ))

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
                change_intensity=max_intensity(trigger_files),
                change_intensities=change_intensities,
                trigger_patterns=matched_patterns,
                blast_radius=_blast_radius(change_types, change_intensities, unsatisfied),
                satisfied_groups=satisfied,
                cross_file_relations=relation_names,
            ))
            status = "rejected-ignore" if rule_id in ignore_map else "fail"
            reason = (
                "drift-ignore rejected; required groups are still missing"
                if status == "rejected-ignore"
                else "required groups are missing"
            )
            rule_decisions.append(RuleDecision(
                rule_id=rule_id,
                severity=severity,
                status=status,
                reason=reason,
                matched_patterns=matched_patterns,
                trigger_files=[f.path for f in trigger_files],
                satisfied_groups=satisfied,
                unsatisfied_groups=unsatisfied,
            ))
        else:
            rule_decisions.append(RuleDecision(
                rule_id=rule_id,
                severity=severity,
                status="pass",
                reason="trigger matched and all required groups were satisfied",
                matched_patterns=matched_patterns,
                trigger_files=[f.path for f in trigger_files],
                satisfied_groups=satisfied,
            ))

    return violations, skipped_rules, rejected_ignores, rule_decisions, ignore_audit


def _evaluate_groups(
    groups: List[Group],
    changed_files: List[ChangedFile],
) -> Tuple[List[SatisfiedGroup], List[UnsatisfiedGroup]]:
    satisfied: List[SatisfiedGroup] = []
    unsatisfied: List[UnsatisfiedGroup] = []
    for group in groups:
        required = group.any_changed or group.all_changed
        group_type = "any_changed" if group.any_changed else "all_changed"
        if _evaluate_group(group, changed_files):
            satisfied.append(SatisfiedGroup(
                name=group.name,
                required=required,
                type=group_type,
            ))
        else:
            unsatisfied.append(UnsatisfiedGroup(
                name=group.name,
                required=required,
                type=group_type,
            ))
    return satisfied, unsatisfied


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


def _evaluate_cross_file_relations(
    relations: List[CrossFileRelation],
    groups: List[Group],
    changed_files: List[ChangedFile],
) -> Tuple[List[SatisfiedGroup], List[UnsatisfiedGroup], List[str]]:
    group_by_name = {group.name: group for group in groups}
    satisfied: List[SatisfiedGroup] = []
    unsatisfied: List[UnsatisfiedGroup] = []
    triggered_names: List[str] = []

    for relation in relations:
        if not relation.when_any_changed:
            continue
        triggered = any(
            matches_any(file.path, relation.when_any_changed)
            or (
                file.previous_path
                and matches_any(file.previous_path, relation.when_any_changed)
            )
            for file in changed_files
        )
        if not triggered:
            continue

        triggered_names.append(relation.name)
        for group_name in relation.require_groups:
            group = group_by_name.get(group_name)
            if group is None:
                continue
            required = group.any_changed or group.all_changed
            group_type = "any_changed" if group.any_changed else "all_changed"
            relation_group_name = f"{relation.name}: {group.name}"
            if _evaluate_group(group, changed_files):
                satisfied.append(SatisfiedGroup(
                    name=relation_group_name,
                    required=required,
                    type=group_type,
                ))
            else:
                unsatisfied.append(UnsatisfiedGroup(
                    name=relation_group_name,
                    required=required,
                    type=group_type,
                ))

    return satisfied, unsatisfied, sorted(triggered_names)


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


def _matched_patterns(
    trigger_files: List[ChangedFile],
    when_patterns: List[str],
) -> List[str]:
    matches = set()
    for file in trigger_files:
        paths = [file.path]
        if file.previous_path:
            paths.append(file.previous_path)
        for path in paths:
            for pattern in when_patterns:
                if match_glob(path, pattern):
                    matches.add(pattern)
    return sorted(matches)


def _blast_radius(
    change_types: List[str],
    change_intensities: List[str],
    unsatisfied: List[UnsatisfiedGroup],
) -> List[str]:
    """Human-readable impact areas derived from deterministic signals."""
    radius = set()
    types = set(change_types)
    intensities = set(change_intensities)

    if "api-surface" in types or "route-contract-change" in intensities:
        radius.update([
            "external API consumers",
            "OpenAPI/spec documentation",
            "release notes",
        ])
    if "db-schema" in types or "db-schema-change" in intensities:
        radius.update([
            "database migrations",
            "rollback/runbook operators",
            "integration/e2e verification",
        ])
    if "env-config" in types or "config-key-added" in intensities:
        radius.update([
            "deployment configuration",
            ".env.example consumers",
            "runtime operators",
        ])
    if "workflow-ci" in types or "ci-secret-change" in intensities:
        radius.update([
            "CI/CD pipeline",
            "repository secrets",
            "ops/runbook owners",
        ])
    if "auth-permission" in types or "auth-policy-change" in intensities:
        radius.update([
            "authorization behavior",
            "security documentation",
            "role/permission owners",
        ])
    if "cli-public-interface" in types or "public-cli-change" in intensities:
        radius.update([
            "CLI users",
            "automation scripts",
            "README/help documentation",
        ])

    for group in unsatisfied:
        if group.name:
            radius.add(f"missing requirement group: {group.name}")

    return sorted(radius)


def _ignore_rejection_reason(
    directive: DriftIgnoreDirective,
    rule,
    policy: Policy,
) -> str:
    severity = rule.severity.upper()
    suppression = policy.suppression
    if not suppression.allow_ignores:
        return "drift-ignore is disabled by policy"
    if not rule.allow_ignore:
        return "this rule does not allow drift-ignore"
    if suppression.allowed_rules and directive.rule_id not in suppression.allowed_rules:
        return "rule is not listed in suppression.allowed_rules"
    if suppression.require_codeowners_approval and not directive.approved_by:
        return "CODEOWNERS approval is required"
    if severity in ("BLOCKER", "MAJOR") and not directive.reason:
        return "reason is required"
    if not directive.expires:
        return ""
    try:
        expires = date.fromisoformat(directive.expires)
    except ValueError:
        return f"invalid expires date: {directive.expires}"
    if expires < date.today():
        return f"ignore expired on {directive.expires}"
    return ""
