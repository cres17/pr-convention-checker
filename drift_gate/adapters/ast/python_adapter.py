"""Python semantic signal adapter.

Heuristic-based implementation using regex patterns on diff added lines.
Structured for future tree-sitter upgrade.

Future upgrade path (tree-sitter):
  - PY_ROUTE pattern -> tree-sitter Decorator node wrapping a FunctionDef,
    where the decorator call matches @router.get/post/etc.
  - API_SCHEMA pattern -> tree-sitter keyword_argument or assignment matching
    response_model, requestBody, etc.
  - PY_SIGNATURE pattern -> tree-sitter FunctionDef node at module or class level.
  - CLASS_TYPE pattern -> tree-sitter ClassDef node.
  - PY_CLI / CLICK_CLI pattern -> tree-sitter Call matching add_argument,
    add_parser, or @click.command/@click.option decorators.
"""
import re
from functools import lru_cache

_PY_ROUTE = re.compile(r"@\w+\.(get|post|put|patch|delete)\s*\(")
_API_SCHEMA = re.compile(
    r"\b(z\.object|response_model|requestBody|responses|parameters|operationId)\b"
)
_PY_SIGNATURE = re.compile(r"^\s*def\s+\w+\s*\(")
_CLASS_TYPE = re.compile(
    r"^\s*(export\s+)?(class|interface|type|enum|data\s+class|sealed\s+class)\s+\w+"
)
_PY_CLI = re.compile(r"\b(add_argument|add_parser)\s*\(")
_CLICK_CLI = re.compile(r"\b@click\.(command|option|argument)\s*\(")


class PythonAdapter:
    """Heuristic semantic signal extractor for Python files.

    All logic operates on added lines from unified diff output. No file I/O.
    Structured so that individual `_has_*` checks can be replaced with
    tree-sitter queries when tree-sitter-python becomes available.
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

        if self._has_route_decorator(lines):
            signals.add("route-contract-change")
            evidence.add("Python route decorator changed")

        if self._has_api_schema(lines):
            signals.add("route-contract-change")
            evidence.add("Python request or response schema changed")

        if self._has_function_signature(lines):
            signals.add("function-signature-changed")
            evidence.add("Python function signature changed")

        if self._has_class_or_type(lines):
            signals.add("class-interface-type-changed")
            evidence.add("Python class/type declaration changed")

        if self._has_cli_change(lines):
            signals.add("public-cli-change")
            evidence.add("Python CLI command or option changed")

        return frozenset(signals), frozenset(evidence)

    def _has_route_decorator(self, lines: list[str]) -> bool:
        """Detect FastAPI/Flask route decorator on added lines.

        Tree-sitter upgrade: match Decorator nodes whose Call target is a
        MemberExpression matching @router.get, @app.post, etc.
        """
        return any(_PY_ROUTE.search(line) for line in lines)

    def _has_api_schema(self, lines: list[str]) -> bool:
        """Detect Pydantic response_model or OpenAPI annotation keywords.

        Tree-sitter upgrade: match keyword_argument nodes in FunctionDef
        decorators where the keyword matches response_model, etc.
        """
        return any(_API_SCHEMA.search(line) for line in lines)

    def _has_function_signature(self, lines: list[str]) -> bool:
        """Detect function definition lines (def keyword at any indent level).

        Tree-sitter upgrade: match FunctionDef or AsyncFunctionDef nodes at
        module scope or class scope.
        """
        return any(_PY_SIGNATURE.search(line) for line in lines)

    def _has_class_or_type(self, lines: list[str]) -> bool:
        """Detect class or type declaration lines.

        Tree-sitter upgrade: match ClassDef nodes or type alias assignments
        using the `type` keyword (Python 3.12+).
        """
        return any(_CLASS_TYPE.search(line) for line in lines)

    def _has_cli_change(self, lines: list[str]) -> bool:
        """Detect argparse or Click CLI registration calls.

        Tree-sitter upgrade: match Call nodes where the function is
        add_argument/add_parser, or Decorator nodes matching @click.command,
        @click.option, @click.argument.
        """
        return any(_PY_CLI.search(line) or _CLICK_CLI.search(line) for line in lines)
