"""Semantic analysis adapters.

These adapters are optional. They add semantic_signals to ChangedFile objects
before the deterministic core evaluates policy.

TREE_SITTER_AVAILABLE: bool
    Set to True after installing tree-sitter grammars (tree-sitter,
    tree-sitter-typescript, tree-sitter-python).  When True, the
    TypeScriptAdapter and PythonAdapter will slot in tree-sitter parsers
    without any API changes — they already implement SemanticAdapter protocol
    and each `_has_*` method documents the exact tree-sitter query to use.

    Current state: False (heuristic regex in use).
    To enable: pip install tree-sitter tree-sitter-languages (or per-grammar),
    then flip this flag and update each adapter's _has_* methods.
"""

try:
    from tree_sitter_language_pack import get_parser

    get_parser("python")
    TREE_SITTER_AVAILABLE: bool = True
except Exception:
    TREE_SITTER_AVAILABLE = False
