"""Protocol definition for semantic analysis adapters.

This interface allows TypeScriptAdapter and PythonAdapter to be swapped
out for tree-sitter-backed implementations without changing any call sites.

Current implementations (heuristic regex):
  - drift_gate.adapters.ast.typescript_adapter.TypeScriptAdapter
  - drift_gate.adapters.ast.python_adapter.PythonAdapter

When tree-sitter grammars become available (install tree-sitter,
tree-sitter-typescript, tree-sitter-python), the internal `_has_*`
methods in each adapter can be replaced with tree-sitter queries.
The SemanticAdapter protocol and all call sites remain unchanged.
"""
from typing import Protocol, runtime_checkable


@runtime_checkable
class SemanticAdapter(Protocol):
    """Protocol for language-specific semantic signal extraction.

    Implementations must accept a list of added diff lines and return a
    tuple of (signals, evidence). Both are sets of strings.

    - signals: short identifiers consumed by policy min_change_intensity checks
      (e.g. "route-contract-change", "function-signature-changed").
    - evidence: human-readable descriptions rendered in HTML/Markdown reports.

    All logic must operate on diff text only — no file I/O.
    """

    def extract_signals(
        self, added_lines: list[str]
    ) -> tuple[set[str], set[str]]:
        """Extract semantic signals and evidence from added diff lines.

        Args:
            added_lines: Lines from the unified diff that start with '+' (prefix stripped).

        Returns:
            A tuple (signals, evidence) where both elements are sets of strings.
        """
        ...
