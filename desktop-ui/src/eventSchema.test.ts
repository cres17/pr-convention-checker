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
it("rejects malformed JSON and unknown event names", () => {
  expect(decodeDesktopEvent("{").type).toBe("error");
  expect(decodeDesktopEvent('{"type":"unknown"}').type).toBe("error");
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
