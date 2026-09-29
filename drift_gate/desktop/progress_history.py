"""Progress snapshots and comparisons (pure; the service does the file I/O).

A snapshot is recorded whenever the user saves the baseline. It keeps the counts
and each item's effective status so later states can be compared with it. Status
words match ``progress_service``: implemented, partial, not_implemented, unknown,
excluded.
"""

from __future__ import annotations

MAX_SNAPSHOTS = 50
MAX_LISTED = 20


def make_snapshot(report: dict) -> dict:
    items = {
        item["id"]: item.get("effective_status") or item["implementation_status"]
        for item in report["items"]
    }
    return {
        "at": report["at"],
        "version": report["version"],
        "head": report.get("head", ""),
        "total": report["total"],
        "counts": dict(report["counts"]),
        "items": items,
    }


def diff_states(previous: dict[str, str], current: dict[str, str]) -> dict:
    """Changes between two ``{item id: status}`` maps.

    ``regressed`` only means "was implemented, no longer is": confirmed-not-implemented
    items that stay that way are not regressions.
    """
    ids = {"gained": [], "regressed": [], "excluded": [], "reincluded": [], "added": [], "removed": []}
    for item_id, status in current.items():
        before = previous.get(item_id)
        if before is None:
            ids["added"].append(item_id)
        elif before != "excluded" and status == "excluded":
            ids["excluded"].append(item_id)
        elif before == "excluded" and status != "excluded":
            ids["reincluded"].append(item_id)
        elif before != "implemented" and before != "excluded" and status == "implemented":
            ids["gained"].append(item_id)
        elif before == "implemented" and status not in {"implemented", "excluded"}:
            ids["regressed"].append(item_id)
    ids["removed"] = [item_id for item_id in previous if item_id not in current]
    return ids


def counts_of(diff: dict) -> dict:
    return {key: len(value) for key, value in diff.items()}


def append_snapshot(snapshots: list[dict], snapshot: dict) -> list[dict]:
    """Add a snapshot with its change counts against the previous one.

    An unchanged state (same baseline version, statuses and counts) is not recorded twice.
    """
    if snapshots:
        last = snapshots[-1]
        if (
            last["version"] == snapshot["version"]
            and last["items"] == snapshot["items"]
            and last["counts"] == snapshot["counts"]
        ):
            return snapshots
        snapshot = {
            **snapshot,
            "changes": counts_of(diff_states(last["items"], snapshot["items"])),
            "complete_delta": snapshot["counts"].get("complete", 0) - last["counts"].get("complete", 0),
        }
    return [*snapshots, snapshot][-MAX_SNAPSHOTS:]


def summarize(snapshots: list[dict], report: dict | None) -> dict:
    """History rows for display plus what changed since the latest snapshot."""
    rows = [{key: snap.get(key) for key in ("at", "version", "head", "total", "counts", "changes", "complete_delta")}
            for snap in reversed(snapshots)]
    since = None
    if snapshots and report is not None:
        current = make_snapshot(report)["items"]
        diff = diff_states(snapshots[-1]["items"], current)
        titles = {item["id"]: item["title"] for item in report["items"]}
        since = {
            "since": snapshots[-1]["at"],
            "version": snapshots[-1]["version"],
            "complete_delta": report["counts"].get("complete", 0) - snapshots[-1]["counts"].get("complete", 0),
            **{
                key: [{"id": i, "title": titles.get(i, "")} for i in ids[:MAX_LISTED]]
                for key, ids in diff.items()
            },
            "counts": counts_of(diff),
        }
        if not any(since["counts"].values()) and not since["complete_delta"]:
            since = None
    return {"snapshots": rows, "since_save": since}
