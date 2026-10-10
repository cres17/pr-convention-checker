import { expect, it } from "vitest";
import { ProgressRequests } from "./requestSession";
it("rejects a previous editor session even if the repository path is the same", () => {
  const requests = new ProgressRequests();
  const earlier = requests.start("save");
  requests.reset();
  const current = requests.start("save");
  const event = { type: "progressError" as const, requested_path: "/same", message: "failed", request_id: earlier };
  expect(requests.accepts(event)).toBe(false);
  expect(requests.accepts({ ...event, request_id: current })).toBe(true);
});
it("rejects an older response of the same purpose and a wrong response type", () => {
  const requests = new ProgressRequests();
  const old = requests.start("evidence");
  const current = requests.start("evidence");
  const event = { type: "progressEvidence" as const, id: "same", candidates: [], request_id: old };
  expect(requests.accepts(event)).toBe(false);
  expect(requests.accepts({ ...event, request_id: current })).toBe(true);
  expect(requests.accepts({ type: "progressTestsCancelled", request_id: current })).toBe(false);
});
it("invalidates derived reads while keeping a save's trailing responses", () => {
  const requests = new ProgressRequests();
  const read = requests.start("inspect");
  const save = requests.start("save");
  requests.invalidateReads();
  expect(requests.accepts({ type: "progressError", request_id: read, message: "old" })).toBe(false);
  expect(requests.accepts({ type: "progressError", request_id: save, message: "current" })).toBe(true);
});
it("rejects replayed responses after a request has completed", () => {
  const requests = new ProgressRequests();
  const token = requests.start("save");
  const event = { type: "progressError" as const, message: "done", request_id: token, request_done: true };
  expect(requests.accepts(event)).toBe(true);
  requests.complete(event);
  expect(requests.accepts(event)).toBe(false);
});
