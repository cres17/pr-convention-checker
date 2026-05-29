"""TypeScript/JavaScript semantic signal adapter.

Heuristic-based implementation using regex patterns on diff added lines.
Structured for future tree-sitter upgrade.

Future upgrade path (tree-sitter):
  - TS_ROUTE pattern -> tree-sitter CallExpression with callee matching router.get/post/etc.
  - API_SCHEMA pattern -> tree-sitter ObjectExpression keys / JSX attribute names
  - CLASS_TYPE pattern -> tree-sitter ClassDeclaration / InterfaceDeclaration / TSTypeAliasDeclaration
  - PUBLIC_EXPORT pattern -> tree-sitter ExportNamedDeclaration / ExportDefaultDeclaration
  - TS_CLI pattern -> tree-sitter CallExpression matching commander/program.command/option
"""
import re
from functools import lru_cache

_TS_ROUTE = re.compile(r"\b(router|app)\.(get|post|put|patch|delete)\s*\(")
_API_SCHEMA = re.compile(
    r"\b(z\.object|response_model|requestBody|responses|parameters|operationId)\b"
)
_CLASS_TYPE = re.compile(
    r"^\s*(export\s+)?(class|interface|type|enum|data\s+class|sealed\s+class)\s+\w+"
)
_PUBLIC_EXPORT = re.compile(
    r"^\s*export\s+(default\s+)?(async\s+)?"
    r"(function|class|const|let|var|type|interface|enum)\b"
)
_TS_CLI = re.compile(r"\b(program|commander)\.(command|option)\s*\(")


class TypeScriptAdapter:
    """Heuristic semantic signal extractor for TypeScript and JavaScript files.

    All logic operates on added lines from unified diff output. No file I/O.
    Structured so that individual `_has_*` checks can be replaced with
    tree-sitter queries when tree-sitter-typescript becomes available.
    """

    def extract_signals(
        self, added_lines: list[str]
    ) -> tuple[set[str], set[str]]:
        """Extract semantic signals and evidence from added diff lines.

        Results are cached by content hash + tuple identity so that repeated
        evaluations of the same patch (e.g. in benchmark runs comparing multiple
        engines) do not re-run all regex checks.

        Returns:
            A tuple of (signals, evidence) where both are sets of strings.
            signals: short identifiers used in policy min_change_intensity checks.
            evidence: human-readable descriptions for reports.
        """
        lines_tuple = tuple(added_lines)
        fs, fe = self._cached_extract(hash(lines_tuple), lines_tuple)
        return set(fs), set(fe)

    @lru_cache(maxsize=512)
    def _cached_extract(
        self, patch_hash: int, added_lines_tuple: tuple[str, ...]
    ) -> tuple[frozenset[str], frozenset[str]]:
        """Internal cached extraction keyed by (hash, tuple) for deduplication."""
        signals: set[str] = set()
        evidence: set[str] = set()
        lines = list(added_lines_tuple)

        if self._has_route_handler(lines):
            signals.add("route-contract-change")
            evidence.add("TS/JS route handler changed")

        if self._has_api_schema(lines):
            signals.add("route-contract-change")
            evidence.add("TS/JS request or response schema changed")

        if self._has_class_or_type(lines):
            signals.add("class-interface-type-changed")
            evidence.add("TS/JS public class/interface/type changed")

        if self._has_public_export(lines):
            signals.add("public-export-added")
            evidence.add("TS/JS public export added")

        if self._has_cli_change(lines):
            signals.add("public-cli-change")
            evidence.add("TS/JS CLI command or option changed")

        return frozenset(signals), frozenset(evidence)

    def _has_route_handler(self, lines: list[str]) -> bool:
        """Detect Express/Fastify-style route registrations.

        Tree-sitter upgrade: match CallExpression where callee is MemberExpression
        with object matching router|app and property matching HTTP methods.
        """
        return any(_TS_ROUTE.search(line) for line in lines)

    def _has_api_schema(self, lines: list[str]) -> bool:
        """Detect Zod schemas, OpenAPI annotations, or response_model usage.

        Tree-sitter upgrade: match ObjectExpression keys or JSX attribute
        names matching requestBody, responses, etc.
        """
        return any(_API_SCHEMA.search(line) for line in lines)

    def _has_class_or_type(self, lines: list[str]) -> bool:
        """Detect class, interface, type, or enum declarations.

        Tree-sitter upgrade: match ClassDeclaration, InterfaceDeclaration,
        TSTypeAliasDeclaration, or EnumDeclaration nodes.
        """
        return any(_CLASS_TYPE.search(line) for line in lines)

    def _has_public_export(self, lines: list[str]) -> bool:
        """Detect new public exports (function, class, const, etc.).

        Tree-sitter upgrade: match ExportNamedDeclaration or
        ExportDefaultDeclaration nodes.
        """
        return any(_PUBLIC_EXPORT.search(line) for line in lines)

    def _has_cli_change(self, lines: list[str]) -> bool:
        """Detect Commander.js-style CLI command or option registrations.

        Tree-sitter upgrade: match CallExpression where callee is MemberExpression
        with object matching program|commander and property matching command|option.
        """
        return any(_TS_CLI.search(line) for line in lines)
