"""Tree-sitter-backed Python semantic adapter."""
from __future__ import annotations

from drift_gate.adapters.ast.python_adapter import PythonAdapter
from drift_gate.adapters.ast.tree_sitter_support import parse_sexp


class TreeSitterPythonAdapter(PythonAdapter):
    """Use grammar parsing for Python definitions, then conservative regexes."""

    def _sexp(self, lines: list[str]) -> str:
        try:
            return parse_sexp("python", lines)
        except Exception:
            return ""

    def _has_function_signature(self, lines: list[str]) -> bool:
        if "function_definition" in self._sexp(lines):
            return True
        return super()._has_function_signature(lines)

    def _has_class_or_type(self, lines: list[str]) -> bool:
        if "class_definition" in self._sexp(lines):
            return True
        return super()._has_class_or_type(lines)

    def _has_route_decorator(self, lines: list[str]) -> bool:
        sexp = self._sexp(lines)
        if "decorator" in sexp and "attribute" in sexp and "call" in sexp:
            return super()._has_route_decorator(lines)
        return super()._has_route_decorator(lines)
