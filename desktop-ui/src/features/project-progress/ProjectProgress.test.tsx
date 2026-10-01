// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { Bridge, ProgressBaseline, ProgressItem } from "../../bridge";
import ProjectProgress from "./ProjectProgress";

afterEach(cleanup);
const makeItem = (id: string, included = true): ProgressItem => ({
  id,
  title: id,
  criterion: id,
  area: "기능",
  included,
  source: { path: "README.md", line: 1, excerpt: id, sha256: "h" },
  implementation_status: "unknown",
  evidence: null,
  verification_status: "unverified",
  verification_note: "",
});
const makeBaseline = (): ProgressBaseline => ({
  repository: "/sample/one",
  documents: { "README.md": "h" },
  requirements: [makeItem("첫 기능"), makeItem("제외 기능", false)],
});
function harness() {
  const bridge = {
    listProjectDocs: vi.fn(),
    inspectProgress: vi.fn(),
    saveProgress: vi.fn(),
    suggestProgressEvidence: vi.fn(),
  } as unknown as Bridge;
  let events: { type: string; _seq: number; [key: string]: unknown }[] = [];
  let path = "/sample/one";
  const view = render(
    <ProjectProgress path={path} connected bridge={bridge} events={events} />,
  );
  return {
    bridge,
    emit(event: { type: string; [key: string]: unknown }) {
      events = [...events, { ...event, _seq: events.length + 1 }];
      view.rerender(
        <ProjectProgress
          path={path}
          connected
          bridge={bridge}
          events={events}
        />,
      );
    },
    move(next: string) {
      path = next;
      view.rerender(
        <ProjectProgress
          path={path}
          connected
          bridge={bridge}
          events={events}
        />,
      );
    },
  };
}

it("clears errors when moving to another repository and ignores the old repository's reply", () => {
  const page = harness();
  page.emit({
    type: "progressError",
    requested_path: "/sample/one",
    message: "이전 저장소의 오류",
  });
  expect(screen.getByText("이전 저장소의 오류")).toBeTruthy();
  page.move("/sample/two");
  expect(screen.queryByText("이전 저장소의 오류")).toBeNull();
  page.emit({
    type: "progressError",
    requested_path: "/sample/one",
    message: "늦게 도착한 오류",
  });
  expect(screen.queryByText("늦게 도착한 오류")).toBeNull();
});

it("does not carry an evidence candidate into another item selected by a filter", () => {
  const page = harness();
  page.emit({
    type: "progressDocs",
    documents: [],
    omitted: 0,
    baseline: makeBaseline(),
  });
  page.emit({
    type: "progressEvidence",
    id: "첫 기능",
    candidates: [{ path: "src/first.py", line: 1, excerpt: "def first():" }],
  });
  expect(screen.getByRole("button", { name: /src\/first.py:1/ })).toBeTruthy();
  fireEvent.change(screen.getByLabelText("목록 필터"), {
    target: { value: "excluded" },
  });
  expect((screen.getByLabelText("기능명") as HTMLInputElement).value).toBe(
    "제외 기능",
  );
  expect(screen.queryByRole("button", { name: /src\/first.py:1/ })).toBeNull();
});

it("locks the submitted fields until a save reply so edits cannot be silently overwritten", () => {
  const page = harness();
  page.emit({
    type: "progressDocs",
    documents: [],
    omitted: 0,
    baseline: makeBaseline(),
  });
  fireEvent.click(screen.getByRole("button", { name: "기준과 근거 저장" }));
  expect(page.bridge.saveProgress).toHaveBeenCalledOnce();
  expect(
    (screen.getByLabelText("기능명") as HTMLInputElement).matches(":disabled"),
  ).toBe(true);
  expect(
    (screen.getByLabelText("이번 범위에 포함") as HTMLInputElement).matches(
      ":disabled",
    ),
  ).toBe(true);
  page.emit({ type: "progressError", message: "저장 실패" });
  expect(
    (screen.getByLabelText("기능명") as HTMLInputElement).matches(":disabled"),
  ).toBe(false);
});

it("ignores an inspection reply for a baseline that the user has already edited", () => {
  const page = harness();
  const baseline = makeBaseline();
  page.emit({ type: "progressDocs", documents: [], omitted: 0, baseline });
  fireEvent.change(screen.getByLabelText("기능명"), {
    target: { value: "수정된 기능" },
  });
  page.emit({
    type: "progressReport",
    report: {
      repository: "/sample/one",
      version: 1,
      at: "2026-10-01",
      head: "abc",
      stale_documents: [],
      total: 1,
      items: baseline.requirements,
      counts: {
        implemented: 0,
        partial: 0,
        not_implemented: 0,
        unknown: 1,
        complete: 0,
        excluded: 1,
      },
      limitations: "수동 기준",
    },
  });
  expect(screen.getByText("기준 저장 필요")).toBeTruthy();
  expect((screen.getByLabelText("기능명") as HTMLInputElement).value).toBe(
    "수정된 기능",
  );
  expect(
    (
      screen.getByRole("button", {
        name: "완료 확인 기준 저장 필요",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
});

it("keeps save fields locked when an earlier inspection finishes first", () => {
  const page = harness();
  const baseline = makeBaseline();
  page.emit({ type: "progressDocs", documents: [], omitted: 0, baseline });
  fireEvent.click(screen.getByRole("button", { name: "기준과 근거 저장" }));
  page.emit({
    type: "progressReport",
    report: {
      repository: "/sample/one",
      version: 1,
      at: "2026-10-01",
      head: "abc",
      stale_documents: [],
      total: 1,
      items: baseline.requirements,
      counts: {
        implemented: 0,
        partial: 0,
        not_implemented: 0,
        unknown: 1,
        complete: 0,
        excluded: 1,
      },
      limitations: "수동 기준",
    },
  });
  expect(screen.getByLabelText("기능명").matches(":disabled")).toBe(true);
  page.emit({ type: "progressSaved", baseline });
  expect(screen.getByLabelText("기능명").matches(":disabled")).toBe(false);
});

it("refreshes document choices without replacing an edited baseline", () => {
  const page = harness();
  const baseline = makeBaseline();
  page.emit({ type: "progressDocs", documents: [], omitted: 0, baseline });
  fireEvent.change(screen.getByLabelText("기능명"), {
    target: { value: "보존할 편집" },
  });
  page.emit({
    type: "progressDocs",
    documents: [{ path: "README.md", tracked: true, bytes: 100 }],
    omitted: 0,
    baseline,
  });
  expect((screen.getByLabelText("기능명") as HTMLInputElement).value).toBe(
    "보존할 편집",
  );
  expect(screen.getByText("기준 저장 필요")).toBeTruthy();
});
