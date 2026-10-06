from drift_gate.desktop import progress_history as h


def report(statuses, version=1, at="2026-09-29T00:00:00Z", complete=0):
    items = [{"id": i, "title": f"기능 {i}", "implementation_status": s, "effective_status": s}
             for i, s in statuses.items()]
    counts = {k: sum(1 for s in statuses.values() if s == k)
              for k in ("implemented", "partial", "not_implemented", "unknown", "excluded")}
    counts["complete"] = complete
    return {"items": items, "version": version, "at": at, "head": "abc", "counts": counts,
            "total": len(items) - counts["excluded"]}


def test_diff_classifies_each_kind_of_change():
    before = {"a": "unknown", "b": "implemented", "c": "implemented", "d": "unknown",
              "e": "excluded", "f": "not_implemented", "gone": "partial"}
    after = {"a": "implemented", "b": "unknown", "c": "excluded", "d": "unknown",
             "e": "unknown", "f": "not_implemented", "new": "implemented"}
    diff = h.diff_states(before, after)
    assert diff == {"gained": ["a"], "regressed": ["b"], "excluded": ["c"], "reincluded": ["e"],
                    "added": ["new"], "removed": ["gone"]}


def test_confirmed_not_implemented_staying_so_is_not_a_regression():
    assert h.diff_states({"x": "not_implemented"}, {"x": "not_implemented"}) == {
        "gained": [], "regressed": [], "excluded": [], "reincluded": [], "added": [], "removed": []}


def test_snapshots_record_changes_skip_duplicates_and_are_capped():
    first = h.make_snapshot(report({"a": "unknown", "b": "unknown"}))
    snaps = h.append_snapshot([], first)
    assert "changes" not in snaps[0]
    assert h.append_snapshot(snaps, first) == snaps  # same state: nothing new to record
    second = h.make_snapshot(report({"a": "implemented", "b": "unknown"}, version=2, complete=1))
    snaps = h.append_snapshot(snaps, second)
    assert snaps[1]["changes"]["gained"] == 1 and snaps[1]["complete_delta"] == 1
    for n in range(80):
        snaps = h.append_snapshot(snaps, h.make_snapshot(report({"a": "unknown"}, version=10 + n)))
    assert len(snaps) == h.MAX_SNAPSHOTS


def test_summary_lists_newest_first_and_changes_since_the_last_save():
    snaps = h.append_snapshot([], h.make_snapshot(report({"a": "implemented", "b": "unknown"}, complete=1)))
    now = report({"a": "unknown", "b": "unknown"}, complete=0, at="2026-09-30T00:00:00Z")
    summary = h.summarize(snaps, now)
    assert summary["since_save"]["regressed"] == [{"id": "a", "title": "기능 a"}]
    assert summary["since_save"]["complete_delta"] == -1
    assert summary["since_save"]["counts"]["regressed"] == 1
    assert h.summarize(snaps, report({"a": "implemented", "b": "unknown"}, complete=1))["since_save"] is None
    assert h.summarize([], now) == {"snapshots": [], "since_save": None}
    assert [row["version"] for row in h.summarize(snaps, None)["snapshots"]] == [1]


def test_delayed_old_inspection_does_not_replace_the_latest_save():
    newer = h.make_snapshot(report({'a': 'implemented'}, version=2, complete=1))
    older_report = report({'a': 'unknown'}, version=1, at='2026-09-30T00:00:00Z')
    snaps = h.append_snapshot([newer], h.make_snapshot(older_report))
    assert [entry['version'] for entry in snaps] == [1, 2]
    assert snaps[-1]['changes']['gained'] == 1
    assert snaps[-1]['complete_delta'] == 1
    # This response is still derived from the caller's v1, even after v2 commits.
    summary = h.summarize(snaps, older_report)
    assert [row['version'] for row in summary['snapshots']] == [1]
    assert summary['since_save'] is None
    assert h.summarize(snaps, report({'a': 'implemented'}, version=2, complete=1))['since_save'] is None


def test_same_version_future_snapshot_cannot_create_false_regression():
    future = h.make_snapshot(report({'a':'implemented'}, at='2026-09-29T02:00:00Z', complete=1))
    current = report({'a':'unknown'}, at='2026-09-29T01:00:00Z')
    assert h.summarize([future], current) == {'snapshots':[], 'since_save':None}
