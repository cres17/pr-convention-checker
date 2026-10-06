// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { Bridge, ProgressBaseline, ProgressItem } from "../../bridge";
import type { ProgressEvent, QueuedProgressEvent } from "../../events";
import ProjectProgress from "./ProjectProgress";

afterEach(() => { cleanup(); vi.useRealTimers(); });
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
    previewProgress: vi.fn(),
    loadTestResults: vi.fn(),
    cacheProgressDraft: vi.fn(),
    discardProgressDraft: vi.fn(),
    discardProgressDrafts: vi.fn(),
    exportProgressDraft: vi.fn(),
    importProgressDraft: vi.fn(),
    useLatestProgress: vi.fn(),
  } as unknown as Bridge;
  let events: QueuedProgressEvent[] = [];
  let path = "/sample/one";
  const view = render(
    <ProjectProgress path={path} connected bridge={bridge} events={events} />,
  );
  return {
    bridge,
    emit(event: ProgressEvent) {
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
    emitBatch(batch: ProgressEvent[]) {
      events = [...events, ...batch.map((event, n) => ({ ...event, _seq: events.length + n + 1 }))];
      view.rerender(<ProjectProgress path={path} connected bridge={bridge} events={events} />);
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

it("offers recovery without overwriting the confirmed baseline, then preserves incomplete edits", () => {
  vi.useFakeTimers();
  const page = harness();
  const recovery = makeBaseline();
  recovery.requirements[0] = { ...recovery.requirements[0], title: "복구할 제목", criterion: "" };
  page.emit({ type: "progressDocs", documents: [], omitted: 0, baseline: makeBaseline(), recovery,
    recovery_warning: "확정된 기준이 달라졌습니다." });
  expect((screen.getByLabelText("기능명") as HTMLInputElement).value).toBe("첫 기능");
  fireEvent.change(screen.getByLabelText("기능명"), { target: { value: "선택 전 덮어쓰기" } });
  expect(page.bridge.cacheProgressDraft).not.toHaveBeenCalled();
  expect((screen.getByLabelText("기능명") as HTMLInputElement).value).toBe("첫 기능");
  fireEvent.click(screen.getByRole("button", { name: "초안 복구" }));
  expect((screen.getByLabelText("기능명") as HTMLInputElement).value).toBe("복구할 제목");
  act(() => vi.advanceTimersByTime(650));
  const cached = vi.mocked(page.bridge.cacheProgressDraft!).mock.calls.at(-1)!;
  expect(JSON.parse(cached[1]).requirements[0].criterion).toBe("");
  expect(page.bridge.saveProgress).not.toHaveBeenCalled();
  page.emit({ type: "progressDraftCached", request_id: cached[2], requested_path: cached[0], request_done: true });
  expect(screen.getByText(/이 기기에 보관했습니다/)).toBeTruthy();
});

it("deletes only the recovery copy after a correlated confirmation", () => {
  const page = harness();
  page.emit({ type: "progressDocs", documents: [], omitted: 0, baseline: makeBaseline(), recovery: makeBaseline() });
  fireEvent.click(screen.getByRole("button", { name: "보관된 초안 삭제" }));
  expect(screen.getByText("이전 편집 초안이 있습니다.")).toBeTruthy();
  const [path, request_id] = vi.mocked(page.bridge.discardProgressDraft!).mock.calls.at(-1)!;
  page.emit({ type: "progressDraftDiscarded", requested_path: path, request_id, request_done: true });
  expect(screen.queryByText("이전 편집 초안이 있습니다.")).toBeNull();
  expect((screen.getByLabelText("기능명") as HTMLInputElement).value).toBe("첫 기능");
});

it("shows an autosave failure without unlocking a confirmed save in progress", () => {
  vi.useFakeTimers();
  const page = harness();
  page.emit({ type: "progressDocs", documents: [], omitted: 0, baseline: makeBaseline() });
  fireEvent.change(screen.getByLabelText("기능명"), { target: { value: "새 제목" } });
  act(() => vi.advanceTimersByTime(650));
  const [path, , request_id] = vi.mocked(page.bridge.cacheProgressDraft!).mock.calls.at(-1)!;
  fireEvent.click(screen.getByRole("button", { name: "기준과 근거 저장" }));
  page.emit({ type: "progressDraftError", requested_path: path, request_id, request_done: true, message: "디스크 오류" });
  expect(screen.getByText(/초안 자동 보관에 실패했습니다/)).toBeTruthy();
  expect((screen.getByRole("button", { name: "저장 중…" }) as HTMLButtonElement).disabled).toBe(true);
});

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

it("merges a newly current past document into the edited draft and saves the existing evidence", () => {
  const page = harness();
  const baseline = makeBaseline();
  baseline.documents["past.md"] = "past-h";
  baseline.document_kinds = { "README.md": "current", "past.md": "past" };
  const old = baseline.requirements[0];
  old.implementation_status = "implemented";
  old.evidence = { path: "src/first.py", line: 1, note: "확인", sha256: "code" };
  old.verification_status = "verified";
  old.verification_note = "직접 검증";
  page.emit({ type: "progressDocs", documents: [
    { path: "README.md", tracked: true, bytes: 10 },
    { path: "past.md", tracked: true, bytes: 10 },
  ], omitted: 0, baseline });
  fireEvent.click(screen.getByRole("button", { name: "기준 문서 변경" }));
  fireEvent.change(screen.getByLabelText("past.md의 문서 종류"), { target: { value: "current" } });
  fireEvent.click(screen.getByRole("button", { name: "기능 후보 추출" }));
  expect(page.bridge.previewProgress).toHaveBeenCalledWith("/sample/one", JSON.stringify([
    { path: "README.md", kind: "current" }, { path: "past.md", kind: "current" },
  ]), expect.any(String));
  // Editing while extraction runs must also survive its eventual reply.
  fireEvent.change(screen.getByLabelText("기능명"), { target: { value: "저장 전 편집" } });
  const added = makeItem("추가 기능");
  added.source.path = "past.md";
  added.source.sha256 = "past-h";
  page.emit({ type: "progressPreview", documents: baseline.documents,
    document_kinds: { "README.md": "current", "past.md": "current" },
    requirements: [makeItem(old.id), added] });
  expect((screen.getByLabelText("기능명") as HTMLInputElement).value).toBe("저장 전 편집");
  fireEvent.click(screen.getByRole("button", { name: "기준과 근거 저장" }));
  const saved = JSON.parse(vi.mocked(page.bridge.saveProgress).mock.calls[0][1]);
  expect(saved.requirements[0]).toMatchObject({
    title: "저장 전 편집", implementation_status: "implemented", evidence: old.evidence,
    verification_status: "verified", verification_note: "직접 검증",
  });
  expect(saved.requirements.map((entry: ProgressItem) => entry.id)).toEqual([old.id, "제외 기능", added.id]);
});

it("keeps changed document reviews stale until the user explicitly confirms the new conditions", () => {
  const page = harness();
  const baseline = makeBaseline();
  baseline.requirements[0].implementation_status = "not_implemented";
  baseline.requirements[0].implementation_note = "확인 기록";
  page.emit({ type: "progressDocs", documents: [], omitted: 0, baseline });
  const fresh = makeItem("첫 기능");
  fresh.source.sha256 = "new";
  page.emit({ type: "progressPreview", documents: { "README.md": "new" },
    document_kinds: { "README.md": "current" }, requirements: [fresh] });
  expect(screen.getAllByText("재확인 필요").length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole("button", { name: "변경된 문서와 완료 조건 확인" }));
  fireEvent.click(screen.getByRole("button", { name: "기준과 근거 저장" }));
  const saved = JSON.parse(vi.mocked(page.bridge.saveProgress).mock.calls[0][1]);
  expect(saved.requirements[0].reviewed_documents).toEqual({ "README.md": "new" });
  expect(saved.requirements[0].implementation_note).toBe("확인 기록");
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

it("hides prior test links and hints immediately when a goal document leaves current scope", () => {
  const page = harness();
  const baseline = makeBaseline();
  baseline.requirements[0].test_patterns = ["test_first"];
  page.emit({ type: "progressDocs", documents: [{ path: "README.md", tracked: true, bytes: 10 }], omitted: 0, baseline });
  page.emit({ type: "progressReport", report: {
    repository: "/sample/one", version: 1, at: "2026-10-01", head: "abc", stale_documents: [],
    total: 1, items: baseline.requirements,
    counts: { complete: 0, implemented: 0, partial: 0, not_implemented: 0, unknown: 1, excluded: 1 },
    test_pattern_hints: { "첫 기능": ["test_first"] }, limitations: "수동 기준",
  } });
  page.emit({ type: "progressTests", format: "junit", file: "r.xml", modified: "now", total: 1,
    items: { "첫 기능": { patterns: ["test_first"], matched: 1, passed: 1, failed: 0, skipped: 0, failing: [], no_match: false } },
  });
  expect(screen.getByLabelText("자동 검증 기록")).toBeTruthy();
  expect(screen.getByText(/저장소의 테스트 파일에서 찾지 못한 이름/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "기준 문서 변경" }));
  fireEvent.change(screen.getByLabelText("README.md의 문서 종류"), { target: { value: "past" } });
  fireEvent.change(screen.getByLabelText("목록 필터"), { target: { value: "excluded" } });
  expect(screen.queryByLabelText("자동 검증 기록")).toBeNull();
  expect(screen.queryByText(/저장소의 테스트 파일에서 찾지 못한 이름/)).toBeNull();
  expect(screen.getByText(/현재 목표 범위 밖이므로 테스트 힌트와 결과 연결을 적용하지 않습니다/)).toBeTruthy();
  expect((screen.getByLabelText("관련 테스트 이름 (쉼표로 구분, 이름의 일부)") as HTMLInputElement).value).toBe("test_first");
  expect(screen.getByLabelText("기능 목록").textContent).not.toContain("자동 검증:");
  expect(screen.getAllByText(/현재 목표 집계에서 제외/).length).toBeGreaterThan(0);
  expect(screen.getByLabelText("기능 목록").textContent).not.toContain("다음: 코드 근거 확인");
});

it("preserves evidence when baseline and extraction replies arrive in one render batch", () => {
  const page = harness();
  const baseline = makeBaseline();
  Object.assign(baseline.requirements[0], {
    implementation_status: "implemented", evidence: { path: "src/x.py", line: 1, note: "확인", sha256: "code" },
    verification_status: "verified", verification_note: "기존 검증",
  });
  page.emitBatch([
    { type: "progressDocs", documents: [], omitted: 0, baseline },
    { type: "progressPreview", documents: baseline.documents, requirements: [makeItem("첫 기능"), makeItem("새 기능")] },
  ]);
  fireEvent.click(screen.getByRole("button", { name: "기준과 근거 저장" }));
  const saved = JSON.parse(vi.mocked(page.bridge.saveProgress).mock.calls[0][1]);
  expect(saved.requirements[0].evidence).toEqual(baseline.requirements[0].evidence);
  expect(saved.requirements[0].verification_note).toBe("기존 검증");
  expect(saved.requirements.map((entry: ProgressItem) => entry.id)).toEqual(["첫 기능", "제외 기능", "새 기능"]);
});

it("merges successive extraction replies against the preceding state in one batch", () => {
  const page = harness();
  const baseline = makeBaseline();
  page.emit({ type: "progressDocs", documents: [], omitted: 0, baseline });
  page.emitBatch([
    { type: "progressPreview", documents: baseline.documents, requirements: [makeItem("추가 A")] },
    { type: "progressPreview", documents: baseline.documents, requirements: [makeItem("추가 B")] },
  ]);
  fireEvent.click(screen.getByRole("button", { name: "기준과 근거 저장" }));
  const saved = JSON.parse(vi.mocked(page.bridge.saveProgress).mock.calls[0][1]);
  expect(saved.requirements.map((entry: ProgressItem) => entry.id)).toEqual(["첫 기능", "제외 기능", "추가 A", "추가 B"]);
});

it("releases loading on a cancelled test picker and keeps the previous result", () => {
  const page = harness();
  const baseline = makeBaseline();
  page.emit({ type: "progressDocs", documents: [], omitted: 0, baseline });
  page.emit({ type: "progressReport", report: {
    repository: "/sample/one", version: 1, at: "2026-10-01", head: "abc", stale_documents: [],
    total: 1, items: baseline.requirements, counts: { unknown: 1 }, limitations: "수동 기준",
  } });
  page.emit({ type: "progressTests", format: "junit", file: "old.xml", modified: "now", total: 1,
    items: { "첫 기능": { patterns: [], matched: 1, passed: 1, failed: 0, skipped: 0, failing: [], no_match: false } },
  });
  fireEvent.click(screen.getByRole("button", { name: "테스트 결과 불러오기" }));
  expect(screen.getByRole("button", { name: "기준과 근거 저장" }).matches(":disabled")).toBe(true);
  page.emit({ type: "progressTestsCancelled" });
  expect(screen.getByRole("button", { name: "기준과 근거 저장" }).matches(":disabled")).toBe(false);
  expect(screen.getByLabelText("자동 검증 기록").textContent).toContain("old.xml");
});

it("invalidates old test links when their matching input is edited", () => {
  const page = harness();
  const baseline = makeBaseline();
  page.emit({ type: "progressDocs", documents: [], omitted: 0, baseline });
  page.emit({ type: "progressTests", format: "junit", file: "old.xml", modified: "now", total: 1,
    items: { "첫 기능": { patterns: ["test_old"], matched: 1, passed: 1, failed: 0, skipped: 0, failing: [], no_match: false } },
  });
  expect(screen.getByLabelText("자동 검증 기록")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("관련 테스트 이름 (쉼표로 구분, 이름의 일부)"), { target: { value: "test_new" } });
  expect(screen.queryByLabelText("자동 검증 기록")).toBeNull();
});

it("does not restore obsolete test links when a delayed result arrives after editing their input", () => {
  const page = harness();
  page.emit({ type: "progressDocs", documents: [], omitted: 0, baseline: makeBaseline() });
  fireEvent.change(screen.getByLabelText("관련 테스트 이름 (쉼표로 구분, 이름의 일부)"), { target: { value: "test_new" } });
  page.emit({ type: "progressTests", format: "junit", file: "old.xml", modified: "now", total: 1,
    items: { "첫 기능": { patterns: ["test_old"], matched: 1, passed: 1, failed: 0, skipped: 0, failing: [], no_match: false } },
  });
  expect(screen.queryByLabelText("자동 검증 기록")).toBeNull();
  expect((screen.getByLabelText("관련 테스트 이름 (쉼표로 구분, 이름의 일부)") as HTMLInputElement).value).toBe("test_new");
});

it("finishes a pending test read without applying its obsolete result after an edit", () => {
  const page = harness();
  const baseline = makeBaseline();
  page.emit({ type: "progressDocs", documents: [], omitted: 0, baseline });
  page.emit({ type: "progressReport", report: { repository: "/sample/one", version: 1, at: "now", head: "h",
    stale_documents: [], total: 1, items: baseline.requirements, counts: { unknown: 1 }, limitations: "수동 기준" } });
  fireEvent.click(screen.getByRole("button", { name: "테스트 결과 불러오기" }));
  const request_id = vi.mocked(page.bridge.loadTestResults).mock.calls.at(-1)?.[1];
  fireEvent.change(screen.getByLabelText("관련 테스트 이름 (쉼표로 구분, 이름의 일부)"), { target: { value: "new_test" } });
  page.emit({ type: "progressTests", request_id, request_done: true, format: "junit", file: "old.xml", modified: "now", total: 1,
    items: { "첫 기능": { patterns: ["old_test"], matched: 1, passed: 1, failed: 0, skipped: 0, failing: [], no_match: false } } });
  expect(screen.queryByLabelText("자동 검증 기록")).toBeNull();
  expect(screen.getByRole("button", { name: "기준과 근거 저장" }).matches(":disabled")).toBe(false);
});

it("coalesces rapid edits and cancels a pending cache when confirming a save", () => {
  vi.useFakeTimers();
  const page = harness();
  page.emit({ type: "progressDocs", documents: [], omitted: 0, baseline: makeBaseline() });
  for (const title of ["하", "하나", "하나 더"]) {
    fireEvent.change(screen.getByLabelText("기능명"), { target: { value: title } });
    act(() => vi.advanceTimersByTime(200));
  }
  expect(page.bridge.cacheProgressDraft).not.toHaveBeenCalled();
  act(() => vi.advanceTimersByTime(450));
  expect(page.bridge.cacheProgressDraft).toHaveBeenCalledOnce();
  expect(JSON.parse(vi.mocked(page.bridge.cacheProgressDraft!).mock.calls[0][1]).requirements[0].title).toBe("하나 더");
  fireEvent.change(screen.getByLabelText("기능명"), { target: { value: "확정 제목" } });
  fireEvent.click(screen.getByRole("button", { name: "기준과 근거 저장" }));
  const [path, , request_id] = vi.mocked(page.bridge.saveProgress).mock.calls.at(-1)!;
  page.emit({ type: "progressSaved", requested_path: path, request_id, request_done: true,
    baseline: makeBaseline(), warning: "기준은 저장했지만 초안을 지우지 못했습니다." });
  act(() => vi.advanceTimersByTime(1000));
  expect(page.bridge.cacheProgressDraft).toHaveBeenCalledOnce();
  expect(screen.getByText("기준은 저장했지만 초안을 지우지 못했습니다.")).toBeTruthy();
  expect((screen.getByLabelText("기능명") as HTMLInputElement).disabled).toBe(false);
});

it("flushes the latest pending draft when switching repositories", () => {
  vi.useFakeTimers();
  const page = harness();
  page.emit({ type: "progressDocs", documents: [], omitted: 0, baseline: makeBaseline() });
  fireEvent.change(screen.getByLabelText("기능명"), { target: { value: "전환 전 마지막 입력" } });
  page.move("/sample/two");
  const [path, payload] = vi.mocked(page.bridge.cacheProgressDraft!).mock.calls.at(-1)!;
  expect(path).toBe("/sample/one");
  expect(JSON.parse(payload).requirements[0].title).toBe("전환 전 마지막 입력");
});

it.each(['local', 'latest'] as const)('offers an explicit %s choice for overlapping edits while preserving unrelated edits', (choice) => {
  const page = harness();
  const original = { ...makeBaseline(), version: 1 };
  page.emit({ type: 'progressDocs', documents: [], omitted: 0, baseline: original });
  fireEvent.change(screen.getByLabelText('기능명'), { target: { value: '내 제목' } });
  fireEvent.click(screen.getByRole('button', { name: '기준과 근거 저장' }));
  const [path, , request_id] = vi.mocked(page.bridge.saveProgress).mock.calls.at(-1)!;
  const latest = structuredClone(original);
  latest.version = 2;
  latest.requirements[0].title = '최신 제목';
  latest.requirements[1].area = '다른 편집기의 변경';
  page.emit({ type: 'progressError', requested_path: path, request_id, request_done: true,
    message: '최신 기준과 합쳐 주세요.', current_baseline: latest });
  expect(screen.getByRole('button', { name: '기준과 근거 저장' }).matches(':disabled')).toBe(true);
  expect(screen.getByText('내 제목 · 기능명')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: choice === 'local'
    ? '겹치는 변경은 내 편집으로 합치기' : '겹치는 변경은 최신 기준으로 합치기' }));
  expect((screen.getByLabelText('기능명') as HTMLInputElement).value).toBe(choice === 'local' ? '내 제목' : '최신 제목');
  fireEvent.click(screen.getByRole('button', { name: '기준과 근거 저장' }));
  const saved = JSON.parse(vi.mocked(page.bridge.saveProgress).mock.calls.at(-1)![1]);
  expect(saved.version).toBe(2);
  expect(saved.requirements[1].area).toBe('다른 편집기의 변경');
});

it('selects another recovery copy and deletes only the displayed revision', () => {
  const page = harness();
  page.emit({ type: 'progressDocs', documents: [], omitted: 0, baseline: makeBaseline(), recovery: makeBaseline(),
    recovery_key: 'new.json', recovery_revision: 'new:1', recovery_options: [
      { key: 'new.json', updated_at: '2026-10-02T01:00:00Z' }, { key: 'old.json', updated_at: '2026-10-01T01:00:00Z' },
    ] });
  fireEvent.change(screen.getByLabelText('복구할 초안'), { target: { value: 'old.json' } });
  const [path, token, key] = vi.mocked(page.bridge.listProjectDocs).mock.calls.at(-1)!;
  expect(key).toBe('old.json');
  page.emit({ type: 'progressDocs', requested_path: path, request_id: token, request_done: true,
    documents: [], omitted: 0, baseline: makeBaseline(), recovery: makeBaseline(), recovery_key: key, recovery_revision: 'old:1' });
  fireEvent.click(screen.getByRole('button', { name: '보관된 초안 삭제' }));
  expect(vi.mocked(page.bridge.discardProgressDraft!).mock.calls.at(-1)?.slice(2)).toEqual(['old.json', 'old:1']);
});

it('protects running recovery copies and sends the selected cleanup revisions only', () => {
  const page = harness();
  const options = [
    { key: 'live.json', revision: 'live:1', updated_at: '2026-10-02T01:00:00Z', bytes: 2048, active: true },
    { key: 'old.json', revision: 'old:1', updated_at: '2026-10-01T01:00:00Z', bytes: 1024, active: false },
  ];
  page.emit({ type: 'progressDocs', documents: [], omitted: 0, baseline: makeBaseline(), recovery: makeBaseline(),
    recovery_key: 'live.json', recovery_revision: 'live:1', recovery_options: options });
  expect(screen.getByRole('button', { name: '초안 복구' }).matches(':disabled')).toBe(true);
  expect(screen.getByRole('button', { name: '보관된 초안 삭제' }).matches(':disabled')).toBe(true);
  expect(screen.getByLabelText('정리할 초안 1').matches(':disabled')).toBe(true);
  fireEvent.click(screen.getByLabelText('정리할 초안 2'));
  fireEvent.click(screen.getByRole('button', { name: '선택한 초안 1개 삭제' }));
  expect(JSON.parse(vi.mocked(page.bridge.discardProgressDrafts!).mock.calls.at(-1)![1])).toEqual([{ key: 'old.json', revision: 'old:1' }]);
});

function overflowPage() {
  const page = harness();
  const original = { ...makeBaseline(), version: 1 };
  page.emit({ type: 'progressDocs', documents: [], omitted: 0, baseline: original });
  // A new extracted requirement exists only in our editor; the other editor adds 118.
  page.emit({ type: 'progressPreview', documents: original.documents, requirements: [...original.requirements, makeItem('내 새 기능')] });
  fireEvent.click(screen.getByRole('button', { name: '기준과 근거 저장' }));
  const [path, , request_id] = vi.mocked(page.bridge.saveProgress).mock.calls.at(-1)!;
  const latest = { ...original, version: 2, requirements: [...original.requirements,
    ...Array.from({ length: 118 }, (_, index) => makeItem(`다른 새 기능 ${index}`))] };
  page.emit({ type: 'progressError', requested_path: path, request_id, request_done: true, message: 'conflict', current_baseline: latest });
  return { ...page, latest };
}

it('keeps an overflowing draft after export cancellation and failure', () => {
  const page = overflowPage();
  const useLatest = screen.getByRole('button', { name: '내 편집을 폐기하고 최신 기준 사용' });
  expect(useLatest.matches(':disabled')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '내 초안 파일로 내보내기' }));
  let request_id = vi.mocked(page.bridge.exportProgressDraft!).mock.calls.at(-1)![2];
  page.emit({ type: 'progressDraftExportCancelled', request_id, request_done: true });
  expect(useLatest.matches(':disabled')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '내 초안 파일로 내보내기' }));
  request_id = vi.mocked(page.bridge.exportProgressDraft!).mock.calls.at(-1)![2];
  page.emit({ type: 'progressError', request_id, request_done: true, message: 'disk full' });
  expect(useLatest.matches(':disabled')).toBe(true);
  expect(page.bridge.useLatestProgress).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: '기준과 근거 저장' }).matches(':disabled')).toBe(true);
});

// This renders the full 120-item boundary, including its recovery transitions.
// The Intel CI runner took 7.86s; the assertions are functional, not a speed budget.
it('uses latest only after successful export and never revives the discarded autosave', () => {
  vi.useFakeTimers();
  const page = overflowPage();
  fireEvent.click(screen.getByRole('button', { name: '내 초안 파일로 내보내기' }));
  const [, payload, request_id] = vi.mocked(page.bridge.exportProgressDraft!).mock.calls.at(-1)!;
  expect(JSON.parse(payload).requirements.some((item: ProgressItem) => item.id === '내 새 기능')).toBe(true);
  page.emit({ type: 'progressDraftExported', request_id, request_done: true, file: '/backup/draft.json' });
  fireEvent.click(screen.getByRole('button', { name: '내 편집을 폐기하고 최신 기준 사용' }));
  const latestRequest = vi.mocked(page.bridge.useLatestProgress!).mock.calls.at(-1)![1];
  page.emit({ type: 'progressLatestUsed', request_id: latestRequest, request_done: true, baseline: page.latest });
  act(() => vi.advanceTimersByTime(1000));
  expect(page.bridge.cacheProgressDraft).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: '기준과 근거 저장' }).matches(':disabled')).toBe(false);
  page.move('/sample/two');
  expect(page.bridge.cacheProgressDraft).not.toHaveBeenCalled();
}, 15_000);

it('requires another export after editing the exported draft', () => {
  const page = overflowPage();
  fireEvent.click(screen.getByRole('button', { name: '내 초안 파일로 내보내기' }));
  const request_id = vi.mocked(page.bridge.exportProgressDraft!).mock.calls.at(-1)![2];
  page.emit({ type: 'progressDraftExported', request_id, request_done: true, file: '/backup/draft.json' });
  expect(screen.getByRole('button', { name: '내 편집을 폐기하고 최신 기준 사용' }).matches(':disabled')).toBe(false);
  fireEvent.change(screen.getByLabelText('기능명'), { target: { value: '내보낸 뒤 추가 편집' } });
  expect(screen.getByRole('button', { name: '내 편집을 폐기하고 최신 기준 사용' }).matches(':disabled')).toBe(true);
});

it('allows baseline editing while preserving the other running app recovery copy', () => {
  const page = harness();
  page.emit({ type: 'progressDocs', documents: [], omitted: 0, baseline: makeBaseline(), recovery: makeBaseline(),
    recovery_key: 'live.json', recovery_revision: '1', recovery_options: [
      { key: 'live.json', revision: '1', updated_at: '2026-10-02T01:00:00Z', active: true },
    ] });
  fireEvent.click(screen.getByRole('button', { name: '초안은 보존하고 기준 편집' }));
  expect(screen.queryByRole('button', { name: '초안 복구' })).toBeNull();
  fireEvent.change(screen.getByLabelText('기능명'), { target: { value: '새 창에서 기준 편집' } });
  expect((screen.getByLabelText('기능명') as HTMLInputElement).value).toBe('새 창에서 기준 편집');
  expect(page.bridge.discardProgressDraft).not.toHaveBeenCalled();
  expect(page.bridge.discardProgressDrafts).not.toHaveBeenCalled();
});

it('imports a file into recovery without replacing the confirmed editor until explicitly recovered', () => {
  const page = harness();
  const baseline = { ...makeBaseline(), version: 2 };
  page.emit({ type: 'progressDocs', documents: [], omitted: 0, baseline });
  fireEvent.click(screen.getByRole('button', { name: '초안 파일 불러오기' }));
  const [path, request_id] = vi.mocked(page.bridge.importProgressDraft!).mock.calls.at(-1)!;
  const recovered = structuredClone(baseline);
  recovered.requirements[0].title = '파일에서 복구한 제목';
  recovered.requirements[0].evidence = { path: '', line: 1.5, note: '' };
  page.emit({ type: 'progressDocs', requested_path: path, request_id, request_done: true, documents: [], omitted: 0,
    baseline, recovery: recovered, recovery_key: 'import.json', recovery_revision: 'r:1', recovery_options: [
      { key: 'import.json', revision: 'r:1', active: false, updated_at: '2026-10-06T01:00:00Z' },
    ] });
  expect((screen.getByLabelText('기능명') as HTMLInputElement).value).toBe('첫 기능');
  expect(page.bridge.saveProgress).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '초안 복구' }));
  expect(screen.getByText('초안을 복구했습니다. 내용을 검토한 뒤 기준과 근거 저장을 눌러 주세요.')).toBeTruthy();
  expect((screen.getByLabelText('기능명') as HTMLInputElement).value).toBe('파일에서 복구한 제목');
  expect(screen.getByRole('button', { name: '초안 파일 불러오기' }).matches(':disabled')).toBe(true);
});

it('keeps the editor and existing recovery options after import cancellation or failure', () => {
  const page = harness();
  page.emit({ type: 'progressDocs', documents: [], omitted: 0, baseline: makeBaseline(), recovery: makeBaseline(),
    recovery_key: 'old.json', recovery_revision: 'r:1' });
  fireEvent.click(screen.getByRole('button', { name: '초안 파일 불러오기' }));
  let [path, request_id] = vi.mocked(page.bridge.importProgressDraft!).mock.calls.at(-1)!;
  page.emit({ type: 'progressDraftImportCancelled', requested_path: path, request_id, request_done: true });
  expect(screen.getByRole('button', { name: '초안 복구' }).matches(':disabled')).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: '초안 파일 불러오기' }));
  [path, request_id] = vi.mocked(page.bridge.importProgressDraft!).mock.calls.at(-1)!;
  page.emit({ type: 'progressError', requested_path: path, request_id, request_done: true, message: '다른 프로젝트의 초안입니다.' });
  expect(screen.getByText('다른 프로젝트의 초안입니다.')).toBeTruthy();
  expect(screen.getByRole('button', { name: '초안 복구' }).matches(':disabled')).toBe(false);
  expect((screen.getByLabelText('기능명') as HTMLInputElement).value).toBe('첫 기능');
});
