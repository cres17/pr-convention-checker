"""
불충족 묶음 → 결정론적 체크리스트 생성.
LLM 불필요. I/O 없음.
"""
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from drift_gate.core.models.result import UnsatisfiedGroup

CHECKLIST_TEMPLATES: dict = {
    "API 계약 문서":  ["관련 spec/API 문서를 변경 내용에 맞게 업데이트"],
    "릴리즈 공지":    ["CHANGELOG.md에 변경 항목 추가"],
    "운영 문서":      ["관련 runbook 또는 운영 문서 업데이트"],
    "샘플 환경변수":  [".env.example에 새 환경변수 반영"],
    "배포 문서":      ["배포 문서에 설정 변경 내용 업데이트"],
    "검증 흔적":      ["관련 integration/e2e 테스트 추가 또는 업데이트"],
    "보안/권한 문서": ["보안 문서 또는 권한 정책 업데이트"],
    "migration 문서": ["마이그레이션 노트 또는 롤백 절차 문서화"],
}


def build_fallback_checklist(unsatisfied_groups: List["UnsatisfiedGroup"]) -> List[str]:
    """
    불충족 묶음 목록 → 체크리스트 항목.
    템플릿에 없는 이름은 '<name> 업데이트'로 폴백.
    """
    items: List[str] = []
    for group in unsatisfied_groups:
        name = group.name
        if name in CHECKLIST_TEMPLATES:
            items.extend(CHECKLIST_TEMPLATES[name])
        else:
            desc = group.required[0] if group.required else name
            items.append(f"{name or desc} 업데이트")
    return items
