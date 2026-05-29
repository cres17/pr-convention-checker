"""
정책 파일 유효성 검사 — 로드 후 실행.
PolicyValidationError: 즉시 중단해야 할 오류
PolicyWarning: 계속 진행하되 운영자에게 알릴 사항
I/O 없음.
"""
from dataclasses import dataclass, field
from typing import List

from drift_gate.core.models.policy import Policy
from drift_gate.core.classification.intensity import VALID_INTENSITIES

VALID_SEVERITIES = {"blocker", "major", "minor", "nit"}


class PolicyValidationError(Exception):
    """즉시 중단이 필요한 정책 오류."""


@dataclass
class ValidationResult:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_if_errors(self) -> None:
        if self.errors:
            msg = "\n".join(f"  - {e}" for e in self.errors)
            raise PolicyValidationError(f"정책 파일 유효성 검사 실패:\n{msg}")


def validate(policy: Policy) -> ValidationResult:
    """
    Policy 객체 전체를 검사.
    반환: ValidationResult (errors + warnings)
    """
    result = ValidationResult()
    seen_ids: set = set()

    for rule in policy.rules:
        rule_id = rule.id

        # 1. rule id 중복
        if rule_id in seen_ids:
            result.errors.append(f"rule id 중복: '{rule_id}'")
        seen_ids.add(rule_id)

        # 2. severity 값 검증
        if rule.severity not in VALID_SEVERITIES:
            result.errors.append(
                f"rule '{rule_id}': severity='{rule.severity}' 오류 — "
                f"허용값: {', '.join(sorted(VALID_SEVERITIES))}"
            )

        # 3. require.groups 없음 (loader에서도 체크하지만 여기서도 방어)
        if not rule.require.groups:
            result.errors.append(
                f"rule '{rule_id}': require.groups가 없습니다."
            )
        group_names = {group.name for group in rule.require.groups}
        for relation in rule.require.cross_file:
            if not relation.name:
                result.errors.append(
                    f"rule '{rule_id}': require.cross_file 항목의 name이 비어 있습니다."
                )
            if not relation.when_any_changed:
                result.errors.append(
                    f"rule '{rule_id}' / relation '{relation.name}': "
                    "when_any_changed가 비어 있습니다."
                )
            if not relation.require_groups:
                result.errors.append(
                    f"rule '{rule_id}' / relation '{relation.name}': "
                    "require_groups가 비어 있습니다."
                )
            missing_groups = [
                name for name in relation.require_groups
                if name not in group_names
            ]
            if missing_groups:
                result.errors.append(
                    f"rule '{rule_id}' / relation '{relation.name}': "
                    f"정의되지 않은 require group 참조 {missing_groups}"
                )

        # 4. when.any_changed 없음
        if not rule.when.any_changed:
            result.errors.append(
                f"rule '{rule_id}': when.any_changed가 비어 있습니다."
            )

        # 4-1. when.min_change_intensity 값 검증
        if rule.when.min_change_intensity not in VALID_INTENSITIES:
            result.errors.append(
                f"rule '{rule_id}': min_change_intensity="
                f"'{rule.when.min_change_intensity}' 오류 — "
                f"허용값: {', '.join(sorted(VALID_INTENSITIES))}"
            )

        # 5. when 경로가 ignore_paths와 완전 포함 관계 → rule이 절대 활성화 안 됨
        if policy.ignore_paths and rule.when.any_changed:
            dead_patterns = [
                p for p in rule.when.any_changed
                if _all_covered_by_ignore(p, policy.ignore_paths)
            ]
            if dead_patterns:
                result.warnings.append(
                    f"rule '{rule_id}': when 패턴 {dead_patterns}이 "
                    f"ignore_paths에 완전히 포함됨 — 이 규칙은 절대 활성화되지 않습니다."
                )

        # 6. require.groups 경로가 ignore_paths에 포함 → 충족 불가
        for group in rule.require.groups:
            required = group.any_changed or group.all_changed
            blocked = [
                p for p in required
                if _all_covered_by_ignore(p, policy.ignore_paths)
            ]
            if blocked:
                result.warnings.append(
                    f"rule '{rule_id}' / group '{group.name}': "
                    f"required 경로 {blocked}이 ignore_paths에 포함됨 — "
                    f"이 묶음은 절대 충족되지 않습니다. "
                    f"ignore_paths에서 해당 경로를 제거하세요."
                )

    return result


def _all_covered_by_ignore(pattern: str, ignore_paths: List[str]) -> bool:
    """
    패턴이 나타낼 수 있는 대표 경로들이 모두 ignore_paths에 덮이는지 추정.
    정확한 판단은 불가하므로 단순 suffix/prefix 포함 체크로 근사.
    """
    # 패턴 자체가 ignore_paths 중 하나에 직접 매칭되는지 확인
    # (예: "docs/**"가 ignore_paths의 "docs/**"와 같으면)
    return pattern in ignore_paths or any(
        pattern.startswith(ip.rstrip("*").rstrip("/"))
        for ip in ignore_paths
        if not ip.startswith("**")
    )
