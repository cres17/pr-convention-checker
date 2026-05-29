"""Tree-sitter-backed TypeScript/JavaScript semantic adapter."""
from __future__ import annotations

from drift_gate.adapters.ast.tree_sitter_support import parse_sexp
from drift_gate.adapters.ast.typescript_adapter import TypeScriptAdapter


class TreeSitterTypeScriptAdapter(TypeScriptAdapter):
    """Use grammar parsing for structural declarations, then conservative regexes."""

    def _sexp(self, lines: list[str], language: str = "typescript") -> str:
        try:
            return parse_sexp(language, lines)
        except Exception:
            return ""

    def _has_class_or_type(self, lines: list[str]) -> bool:
        sexp = self._sexp(lines)
        if any(
            node in sexp
            for node in (
                "class_declaration",
                "interface_declaration",
                "type_alias_declaration",
                "enum_declaration",
            )
        ):
            return True
        return super()._has_class_or_type(lines)

    def _has_public_export(self, lines: list[str]) -> bool:
        sexp = self._sexp(lines)
        if "export_statement" in sexp:
            return True
        return super()._has_public_export(lines)
