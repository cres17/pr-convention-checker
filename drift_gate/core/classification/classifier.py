"""
변경 유형 분류기 — 파일 경로 기반 규칙 우선.
I/O 없음, 순수 함수.
"""
from typing import List

from drift_gate.utils.glob_matcher import matches_any
from drift_gate.core.models.changed_file import ChangedFile

TYPE_PATTERNS: dict = {
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

DOCS_PATTERNS: List[str] = ["docs/**", "**/*.md", "**/*.rst"]
TEST_PATTERNS: List[str] = [
    "tests/**", "**/*.test.*", "**/*.spec.*", "test/**", "__tests__/**",
]


def get_file_change_types(path: str) -> List[str]:
    """단일 파일 경로 → 변경 유형 목록. 해당 없으면 ['other']."""
    types = [ct for ct, patterns in TYPE_PATTERNS.items() if matches_any(path, patterns)]
    return types or ["other"]


def classify_change_types(changed_files: List[ChangedFile]) -> List[str]:
    """
    전체 변경 파일 목록 → 대표 유형 목록.
    - 모든 파일이 docs 패턴 → ['docs-only']
    - 모든 파일이 test 패턴 → ['test-only']
    - 그 외 → 감지된 유형 정렬 목록
    """
    paths = [f.path for f in changed_files]
    if not paths:
        return []

    if all(matches_any(p, DOCS_PATTERNS) for p in paths):
        return ["docs-only"]
    if all(matches_any(p, TEST_PATTERNS) for p in paths):
        return ["test-only"]

    detected: set = set()
    for p in paths:
        detected.update(get_file_change_types(p))
    return sorted(detected)
