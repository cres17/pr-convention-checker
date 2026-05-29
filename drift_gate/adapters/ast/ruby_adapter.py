"""Ruby semantic signal adapter."""
from __future__ import annotations

import re
from functools import lru_cache

from drift_gate.adapters.ast import TREE_SITTER_AVAILABLE
from drift_gate.adapters.ast.tree_sitter_support import parse_sexp

_RUBY_SIGNATURE = re.compile(r"^\s*(def|class|module)\s+\w+")


class RubyAdapter:
    def extract_signals(self, added_lines: list[str]) -> tuple[set[str], set[str]]:
        lines_tuple = tuple(added_lines)
        fs, fe = self._cached_extract(hash(lines_tuple), lines_tuple)
        return set(fs), set(fe)

    @lru_cache(maxsize=512)
    def _cached_extract(
        self, patch_hash: int, added_lines_tuple: tuple[str, ...]
    ) -> tuple[frozenset[str], frozenset[str]]:
        lines = list(added_lines_tuple)
        signals: set[str] = set()
        evidence: set[str] = set()
        sexp = self._sexp(lines)
        if any(node in sexp for node in ("method", "class", "module")) or any(
            _RUBY_SIGNATURE.search(line) for line in lines
        ):
            signals.add("function-signature-changed")
            evidence.add("Ruby public class/module/method changed")
        return frozenset(signals), frozenset(evidence)

    def _sexp(self, lines: list[str]) -> str:
        if not TREE_SITTER_AVAILABLE:
            return ""
        try:
            return parse_sexp("ruby", lines)
        except Exception:
            return ""
