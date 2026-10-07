import { expect, it } from "vitest";
import { decodeDesktopEvent } from "./eventSchema";
import fixture from "./preview-fixture.json";
import qtEvents from "../../docs/assessment/progress-session-review-2026-10-01/qt-events.json";
it("accepts recorded native Qt messages without rejecting valid backend data", () => {
  expect(qtEvents.map((event) => event.type)).toEqual(expect.arrayContaining([
    "progressSaved", "progressReport", "progressHistory", "progressTestsCancelled", "scanned",
  ]));
  for (const event of qtEvents) {
    const decoded = decodeDesktopEvent(JSON.stringify(event));
    expect(decoded.type, `native event ${event.type}`).toBe(event.type);
    expect(["error", "progressError"]).not.toContain(decoded.type);
  }
});
it("validates scans and preserves engine result fields", () => {
  const event = decodeDesktopEvent(JSON.stringify({ type: "scanned", scan: fixture }));
  expect(event).toEqual({ type: "scanned", scan: fixture });
});
it("preserves opt-in proof diagnostics through the native scan event", () => {
  const diagnostics = { schema: "contract-diagnostics-v1", role: "legacy-selector-shadow",
    complete_policy_coverage: false, gate_action_applied: false, records_seen: 1,
    retained_count: 0, omitted_record_count: 1, trace_truncated: true, entries: [] };
  const scan = { ...fixture, result: { ...fixture.result, contract_diagnostics: diagnostics } };
  expect(decodeDesktopEvent(JSON.stringify({ type: "scanned", scan })))
    .toEqual({ type: "scanned", scan });
});
it("rejects malformed JSON and unknown event names", () => {
  expect(decodeDesktopEvent("{").type).toBe("error");
  expect(decodeDesktopEvent('{"type":"unknown"}').type).toBe("error");
});
it('keeps malformed autosave replies separate from a confirmed save in progress', () => {
  expect(decodeDesktopEvent(JSON.stringify({ type: 'progressDraftCached', requested_path: '/repo',
    request_id: 'draft:1', request_done: 'wrong' }))).toMatchObject({ type: 'progressDraftError', request_id: 'draft:1', request_done: true });
});
it("rejects malformed nested progress data without exposing it to the editor", () => {
  expect(decodeDesktopEvent(JSON.stringify({ type: "progressSaved", requested_path: "/repo", request_id: "save:1",
    baseline: { repository: "/repo", documents: {}, requirements: [{ id: "one", included: "yes" }] } })))
    .toMatchObject({ type: "progressError", requested_path: "/repo", request_id: "save:1", request_done: true });
});
it("requires progress request context and validates terminal cancellations", () => {
  expect(decodeDesktopEvent('{"type":"progressTestsCancelled"}').type).toBe("error");
  const event = { type: "progressTestsCancelled", requested_path: "/repo", request_id: "tests:2", request_done: true };
  expect(decodeDesktopEvent(JSON.stringify(event))).toEqual(event);
});
it("rejects a nested status outside the allowed values", () => {
  const entry = { id: "x", title: "x", criterion: "x", area: "x", included: true,
    source: { path: "a.md", line: 1, excerpt: "x", sha256: "h" }, evidence: null,
    verification_status: "unverified", verification_note: "", implementation_status: "finished" };
  const result = decodeDesktopEvent(JSON.stringify({ type: "progressPreview", requested_path: "/repo", request_id: "extract:1",
    documents: { "a.md": "h" }, requirements: [entry] }));
  expect(result.type).toBe("progressError");
});
it("accepts the backend's first history snapshot with no preceding comparison", () => {
  const event = { type: "progressHistory", requested_path: "/repo", request_id: "save:1", request_done: true,
    snapshots: [{ at: "now", version: 1, head: "h", total: 1, counts: { unknown: 1 }, changes: null, complete_delta: null }],
    since_save: null };
  expect(decodeDesktopEvent(JSON.stringify(event))).toEqual(event);
});
it("keeps valid documents when a malformed recovery copy is rejected", () => {
  const event = decodeDesktopEvent(JSON.stringify({ type: "progressDocs", requested_path: "/repo", request_id: "docs:1",
    documents: [], omitted: 0, baseline: null, recovery: { documents: {}, requirements: [{ id: "x" }] } }));
  expect(event).toMatchObject({ type: "progressDocs", recovery: null, recovery_warning: expect.any(String) });
});
it("recovers invalid evidence inputs without treating them as a confirmed baseline", () => {
  const draft = { repository: "/repo", documents: { "a.md": "h" }, requirements: [{
    id: "x", title: "x", criterion: "", area: "x", included: true,
    source: { path: "a.md", line: 1, excerpt: "x", sha256: "h" },
    implementation_status: "implemented", evidence: { path: "", line: -1, note: "" },
    verification_status: "unverified", verification_note: "",
  }] };
  const result = decodeDesktopEvent(JSON.stringify({ type: "progressDocs", requested_path: "/repo", request_id: "docs:1",
    documents: [], omitted: 0, baseline: null, recovery: draft }));
  expect(result).toMatchObject({ type: "progressDocs", recovery: draft });
});
it("recovers fractional and empty evidence lines while rejecting them in confirmed baselines", () => {
  for (const line of [1.5, null]) {
    const baseline = { repository: "/repo", documents: { "a.md": "h" }, requirements: [{
      id: "x", title: "x", criterion: "x", area: "x", included: true,
      source: { path: "a.md", line: 1, excerpt: "x", sha256: "h" },
      implementation_status: "implemented", evidence: { path: "", line, note: "" },
      verification_status: "unverified", verification_note: "",
    }] };
    expect(decodeDesktopEvent(JSON.stringify({ type: "progressDocs", requested_path: "/repo", request_id: "docs:1",
      documents: [], omitted: 0, recovery: baseline }))).toMatchObject({ type: "progressDocs", recovery: baseline });
    expect(decodeDesktopEvent(JSON.stringify({ type: "progressSaved", requested_path: "/repo", request_id: "save:1", baseline })).type)
      .toBe("progressError");
  }
});
