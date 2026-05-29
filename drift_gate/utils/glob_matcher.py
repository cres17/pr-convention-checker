"""
glob → regex 변환 유틸.
fnmatch 불사용 — ** 패턴(디렉토리 재귀)을 직접 처리.
I/O 없음, 순수 함수.
"""
import re
from functools import lru_cache
from typing import List


@lru_cache(maxsize=512)
def glob_to_regex(pattern: str) -> str:
    """
    glob 패턴 → 정규식 문자열 변환.
      **/  → 0개 이상의 디렉토리 세그먼트
      **   → 모든 경로 (슬래시 포함)
      *    → 슬래시 제외 임의 문자열
      ?    → 슬래시 제외 단일 문자
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
        elif pattern[i] in r".+^${}[]|()":
            regex += re.escape(pattern[i])
            i += 1
        else:
            regex += re.escape(pattern[i])
            i += 1
    return regex


def match_glob(path: str, pattern: str) -> bool:
    """path가 glob pattern과 매칭되면 True."""
    path = path.lstrip("/")
    pattern = pattern.lstrip("/")
    try:
        return bool(re.fullmatch(glob_to_regex(pattern), path))
    except re.error:
        return False


def matches_any(path: str, patterns: List[str]) -> bool:
    """path가 patterns 중 하나라도 매칭되면 True."""
    return any(match_glob(path, p) for p in patterns)


def pattern_confidence(pattern: str) -> str:
    """
    단일 패턴의 신뢰도.
      high   — 정확한 경로 또는 단순 디렉토리 glob (dir/**)
      medium — 교차 경로 와일드카드
    """
    wildcards = pattern.count("*")
    if wildcards == 0:
        return "high"
    if pattern.endswith("/**") and wildcards == 2:
        return "high"
    return "medium"
