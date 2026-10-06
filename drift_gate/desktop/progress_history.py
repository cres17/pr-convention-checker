"""Progress snapshots and comparisons (pure; the service does the file I/O).

A snapshot is recorded whenever the user saves the baseline. It keeps the counts
and each item's effective status so later states can be compared with it. Status
words match ``progress_service``: implemented, partial, not_implemented, unknown,
excluded.
"""

from __future__ import annotations

from datetime import datetime

MAX_SNAPSHOTS = 50
MAX_LISTED = 20


class HistoryError(ValueError):
    """Invalid optional history; never replace its file with an empty history."""


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('history timestamp must include a timezone')
    return result


def validate_snapshots(data: object) -> list[dict]:
    """Validate bounded schema-1 history before sorting, comparing or rewriting it."""
    try:
        if not isinstance(data, dict) or data.get('schema') != 1:
            raise ValueError('invalid schema')
        rows = data.get('snapshots')
        if not isinstance(rows, list) or len(rows) > MAX_SNAPSHOTS:
            raise ValueError('invalid snapshots')
        statuses = {'implemented', 'partial', 'not_implemented', 'unknown', 'excluded'}
        for row in rows:
            if (not isinstance(row, dict) or type(row.get('version')) is not int or row['version'] < 0
                    or not isinstance(row.get('head'), str) or type(row.get('total')) is not int or row['total'] < 0
                    or not isinstance(row.get('items'), dict) or len(row['items']) > 120
                    or not all(isinstance(key, str) and value in statuses for key, value in row['items'].items())):
                raise ValueError('invalid snapshot')
            timestamp(row['at'])
            for key in ('counts', 'changes'):
                numbers = row.get(key)
                if key == 'changes' and numbers is None:
                    continue
                if not isinstance(numbers, dict) or not all(type(n) is int and n >= 0 for n in numbers.values()):
                    raise ValueError('invalid counts')
            if row.get('complete_delta') is not None and type(row['complete_delta']) is not int:
                raise ValueError('invalid delta')
        return rows
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HistoryError('진행 이력의 형식을 읽지 못했습니다. 원본 파일은 보존했습니다.') from exc


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
    # A slow inspection can finish after another process records a newer save.
    # Completion order must not turn that old baseline into the latest save.
    ordered = sorted([*snapshots, snapshot], key=lambda entry: (entry['version'], timestamp(entry['at'])))
    result = []
    for entry in ordered:
        last = result[-1] if result else None
        if last is not None and all(last[key] == entry[key] for key in ('version', 'items', 'counts')):
            continue
        entry = {key: value for key, value in entry.items() if key not in ('changes', 'complete_delta')}
        if last is not None:
            entry.update(changes=counts_of(diff_states(last['items'], entry['items'])),
                         complete_delta=entry['counts'].get('complete', 0) - last['counts'].get('complete', 0))
        result.append(entry)
    return result[-MAX_SNAPSHOTS:]


def summarize(snapshots: list[dict], report: dict | None) -> dict:
    """History rows for display plus what changed since the latest snapshot."""
    if report is not None:
        # A response derived from v1 must not compare against a concurrent v2 save.
        snapshots = [entry for entry in snapshots if entry['version'] <= report['version']
                     and timestamp(entry['at']) <= timestamp(report['at'])]
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
