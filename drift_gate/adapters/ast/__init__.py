"""Probe grammar availability; per-file fallback diagnostics live in analyzer.

Loading a grammar does not prove a diff fragment can be parsed. The analyzer
records recovery and failures separately from the deterministic gate result.
"""

try:
    from tree_sitter_language_pack import get_parser

    get_parser("python")
    TREE_SITTER_AVAILABLE: bool = True
except Exception:
    TREE_SITTER_AVAILABLE = False
