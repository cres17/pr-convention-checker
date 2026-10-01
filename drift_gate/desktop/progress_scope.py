"""Document provenance and current-goal scope, independent of test-result I/O."""
from __future__ import annotations


def requirement_sources(item: dict) -> list[dict]:
    return [item["source"], *item.get("duplicates", [])]


def in_current_scope(item: dict, document_kinds: dict[str, str] | None = None) -> bool:
    """One scope rule for raw baselines and already inspected report items.

    Legacy callers without document metadata keep their included-only behaviour.
    A shared goal stays current while any of its source documents is current.
    """
    if not item.get("included"):
        return False
    if document_kinds is None:
        return (
            bool(item.get("in_current_scope", True))
            and item.get("effective_status") != "excluded"
        )
    return any(
        document_kinds.get(place["path"], "current") == "current"
        for place in requirement_sources(item)
    )
