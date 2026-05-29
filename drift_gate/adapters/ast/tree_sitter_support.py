"""Small tree-sitter wrapper used by semantic adapters."""
from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=16)
def _parser(language: str):
    from tree_sitter_language_pack import get_parser

    return get_parser(language)


def parse_sexp(language: str, added_lines: list[str]) -> str:
    """Parse added lines with a real grammar and return the root S-expression."""
    parser = _parser(language)
    tree = parser.parse("\n".join(added_lines) + "\n")
    return tree.root_node().to_sexp()
