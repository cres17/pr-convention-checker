// @vitest-environment jsdom
import { beforeAll, afterEach, describe, it, expect, vi } from "vitest";
import {
  render,
  screen,
  fireEvent,
  cleanup,
  waitFor,
} from "@testing-library/react";
import App from "./App";
import fixture from "./preview-fixture.json";
import type { Scan } from "./bridge";
const api = vi.hoisted(() => ({
  startScan: vi.fn(),
  previewReview: vi.fn(),
  startReview: vi.fn(),
  chooseRepository: vi.fn(),
  cancelReview: vi.fn(),
  exportReport: vi.fn(),
  listProjectDocs: vi.fn(),
  previewProgress: vi.fn(),
  saveProgress: vi.fn(),
  inspectProgress: vi.fn(),
  suggestProgressEvidence: vi.fn(),
}));
beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
});
let emit: (event: any) => void;
vi.mock("./bridge", () => ({
  connect: (fn: any) => {
    emit = fn;
    fn({
      type: "ready",
      repository: "/sample/project",
      base: "HEAD",
      installed: {},
    });
    return Promise.resolve(api);
  },
}));
vi.mock("./components/tool-ui/code-diff", () => ({
  CodeDiff: ({ patch }: any) => <pre>{patch}</pre>,
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
describe("desktop review flow", () => {
  it("does not request LLM until preview confirmation", async () => {
    render(<App initialScan={fixture as Scan} />);
    await waitFor(() =>
      expect(screen.getByText("데스크톱 연결됨")).toBeTruthy(),
    );
    expect(api.startReview).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("전송 내용 확인"));
    expect(api.previewReview).toHaveBeenCalledOnce();
    expect(api.startReview).not.toHaveBeenCalled();
    const { act } = await import("react");
    act(() => emit({ type: "preview", prompt: "Synthetic preview" }));
    fireEvent.click(screen.getByText("전송하고 검토"));
    await waitFor(() =>
      expect(api.startReview).toHaveBeenCalledWith("codex", ""),
    );
  });
  it("filters findings without changing the gate", () => {
    render(<App initialScan={fixture as Scan} />);
    fireEvent.click(screen.getByRole("button", { name: /^통과$/ }));
    expect(screen.getByText("조건에 맞는 규칙이 없습니다.")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "수정 필요" })).toBeTruthy();
  });
  it("shows session history honestly and the policy snapshot", () => {
    render(<App initialScan={fixture as Scan} />);
    fireEvent.click(screen.getByRole("button", { name: "히스토리" }));
    expect(screen.getByText("앱을 닫으면 목록이 지워집니다.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^규칙$/ }));
    expect(
      screen.getByText(
        (_text, node) =>
          node?.tagName === "PRE" && node.textContent === fixture.policy,
      ),
    ).toBeTruthy();
  });
  it("displays backend errors and keeps the next action available", async () => {
    render(<App />);
    await waitFor(() => expect(api).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "검사 시작" }));
    expect(api.startScan).toHaveBeenCalledWith("/sample/project", "HEAD");
    const { act } = await import("react");
    act(() => emit({ type: "error", message: "정책 파일이 없습니다." }));
    expect(screen.getByRole("alert").textContent).toContain(
      "정책 파일이 없습니다.",
    );
  });
});

it("preserves a complete Git patch without duplicating file headers", () => {
  const value = structuredClone(fixture) as Scan;
  const file = value.files[0];
  file.patch = `diff --git a/${file.path} b/${file.path}\n--- a/${file.path}\n+++ b/${file.path}\n${file.patch}`;
  render(<App initialScan={value} />);
  expect(screen.getByText((_text, node) => node?.tagName === "PRE" && node.textContent === file.patch)).toBeTruthy();
});

it("keeps project progress unconfirmed until the user saves reviewed evidence", async () => {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "프로젝트 현황" }));
  await waitFor(() => expect(api.listProjectDocs).toHaveBeenCalledWith("/sample/project"));
  const { act } = await import("react");
  act(() => emit({ type: "progressDocs", repository: "/sample/project", documents: [
    { path: "README.md", tracked: true, bytes: 100 },
  ], omitted: 0, baseline: null }));
  fireEvent.click(screen.getByRole("button", { name: "기능 후보 추출" }));
  expect(api.previewProgress).toHaveBeenCalledWith("/sample/project", '["README.md"]');
  const source = { path: "README.md", line: 2, excerpt: "- [x] 로그인", sha256: "abc" };
  act(() => emit({ type: "progressPreview", repository: "/sample/project",
    documents: { "README.md": "abc" }, requirements: [{
      id: "one", title: "로그인", criterion: "로그인", area: "계정", included: true,
      source, implementation_status: "unknown", evidence: null,
      verification_status: "unverified", verification_note: "",
    }], truncated: false }));
  expect(screen.getByText("기준 저장 필요")).toBeTruthy();
  expect(screen.getAllByText("확인 필요").length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole("button", { name: "기준과 근거 저장" }));
  expect(api.saveProgress).toHaveBeenCalledOnce();
  const saved = JSON.parse(api.saveProgress.mock.calls[0][1]);
  expect(saved.requirements[0].implementation_status).toBe("unknown");
  act(() => emit({ type: "progressSaved", requested_path: "/sample/project",
    baseline: { ...saved, version: 1 } }));
  act(() => emit({ type: "progressReport", requested_path: "/sample/project", report: {
    repository: "/sample/project", version: 1, at: "2026-09-29T00:00:00Z", head: "abc",
    stale_documents: [], total: 1, items: saved.requirements,
    counts: { implemented: 0, partial: 0, not_implemented: 0, unknown: 1, complete: 0, excluded: 0 },
    limitations: "수동 확인 기준",
  } }));
  expect(screen.getAllByText("0 / 1").length).toBe(2);
  expect(screen.getByRole("button", { name: "기준 문서 변경" })).toBeTruthy();
});
