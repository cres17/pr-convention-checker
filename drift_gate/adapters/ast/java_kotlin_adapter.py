"""Java and Kotlin semantic signal adapter."""
from __future__ import annotations

import re
from functools import lru_cache

from drift_gate.adapters.ast import TREE_SITTER_AVAILABLE
from drift_gate.adapters.ast.tree_sitter_support import parse_sexp

_JAVA_KOTLIN_SIGNATURE = re.compile(
    r"^\s*(public|private|protected|fun|class|interface|data\s+class)\s+"
)


class JavaKotlinAdapter:
    def extract_signals(
        self,
        added_lines: list[str],
        *,
        language: str = "java",
    ) -> tuple[set[str], set[str]]:
        lines_tuple = tuple(added_lines)
        fs, fe = self._cached_extract(hash(lines_tuple), lines_tuple, language)
        return set(fs), set(fe)

    @lru_cache(maxsize=512)
    def _cached_extract(
        self,
        patch_hash: int,
        added_lines_tuple: tuple[str, ...],
        language: str,
    ) -> tuple[frozenset[str], frozenset[str]]:
        lines = list(added_lines_tuple)
        signals: set[str] = set()
        evidence: set[str] = set()
        sexp = self._sexp(language, lines)
        structural_nodes = (
            "class_declaration",
            "interface_declaration",
            "method_declaration",
            "function_declaration",
        )
        if any(node in sexp for node in structural_nodes) or any(
            _JAVA_KOTLIN_SIGNATURE.search(line) for line in lines
        ):
            signals.add("class-interface-type-changed")
            evidence.add("Java/Kotlin public type or function changed")
        return frozenset(signals), frozenset(evidence)

    def _sexp(self, language: str, lines: list[str]) -> str:
        if not TREE_SITTER_AVAILABLE:
            return ""
        try:
            return parse_sexp(language, lines)
        except Exception:
            return ""
