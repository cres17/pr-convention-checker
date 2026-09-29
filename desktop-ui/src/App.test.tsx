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
  openDocument: vi.fn(),
  checkProgressLinks: vi.fn(),
  previewPolicy: vi.fn(),
  createPolicy: vi.fn(),
  exportProgress: vi.fn(),
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

it("uses one effective status for badge, filter and summary when evidence became stale", async () => {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "프로젝트 현황" }));
  await waitFor(() => expect(api.listProjectDocs).toHaveBeenCalledWith("/sample/project"));
  const { act } = await import("react");
  const source = { path: "README.md", line: 2, excerpt: "- [x] 로그인", sha256: "abc" };
  const make = (id: string, title: string) => ({
    id, title, criterion: title, area: "계정", included: true, source,
    implementation_status: "implemented" as const,
    evidence: { path: "src/a.py", line: 1, note: "확인", excerpt: "def a():", sha256: "old" },
    verification_status: "unverified" as const, verification_note: "",
  });
  const saved = [make("one", "로그인"), make("two", "가입")];
  act(() => emit({ type: "progressSaved", requested_path: "/sample/project",
    baseline: { repository: "/sample/project", documents: { "README.md": "abc" }, requirements: saved, version: 1 } }));
  act(() => emit({ type: "progressReport", requested_path: "/sample/project", report: {
    repository: "/sample/project", version: 1, at: "2026-09-29T00:00:00Z", head: "abc",
    stale_documents: [], total: 2, limitations: "",
    items: [{ ...saved[0], stale_evidence: true, effective_status: "unknown" },
      { ...saved[1], stale_evidence: false, effective_status: "implemented" }],
    counts: { implemented: 1, partial: 0, not_implemented: 0, unknown: 1, complete: 0, excluded: 0 },
  } }));
  expect(screen.getAllByText("재확인 필요").length).toBe(1);
  fireEvent.change(screen.getByLabelText("목록 필터"), { target: { value: "unknown" } });
  const list = screen.getByLabelText("기능 목록");
  expect(list.textContent).toContain("로그인");
  expect(list.textContent).not.toContain("가입");
});

it("shows how to fix a violation and opens the required document", async () => {
  const value = structuredClone(fixture) as Scan;
  Object.assign(value.result.violations![0], {
    message: "API 문서가 변경을 반영하지 않음",
    changed_contract_summary: "GET /members 추가, GET /users 삭제",
    missing_docs_explanation: "docs/api.md가 이번 변경에서 수정되지 않았습니다.",
    checklist: ["docs/api.md에 GET /members 추가"],
    docs_update_draft: "### GET /members",
  });
  render(<App initialScan={value} />);
  await waitFor(() => expect(screen.getByText("데스크톱 연결됨")).toBeTruthy());
  expect(screen.getAllByText("API 문서가 변경을 반영하지 않음").length).toBeGreaterThan(0);
  expect(screen.getAllByText(/반영되지 않은 문서 조건 1개: API docs/).length).toBeGreaterThan(0);
  expect(screen.queryByText("required groups are missing")).toBeNull();
  expect(screen.getByText("docs/api.md에 GET /members 추가")).toBeTruthy();
  expect(screen.getByText("### GET /members")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /docs\/api\.md 열기/ }));
  expect(api.openDocument).toHaveBeenCalledWith("docs/api.md");
  fireEvent.click(screen.getByRole("button", { name: /문서 수정 후 다시 검사/ }));
  expect(api.startScan).toHaveBeenCalledWith("/sample/project", "HEAD");
});

it("marks every invalid item after a failed save and jumps to the first one", async () => {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "프로젝트 현황" }));
  await waitFor(() => expect(api.listProjectDocs).toHaveBeenCalledWith("/sample/project"));
  const { act } = await import("react");
  const source = { path: "README.md", line: 2, excerpt: "- [x] 로그인", sha256: "abc" };
  const make = (id: string, title: string) => ({
    id, title, criterion: title, area: "계정", included: true, source,
    implementation_status: "unknown" as const, evidence: null,
    verification_status: "unverified" as const, verification_note: "",
    ...(id === "one" ? { duplicates: [{ path: "docs/b.md", line: 4, excerpt: "- [ ] 로그인", criterion: "로그인" }] } : {}),
  });
  act(() => emit({ type: "progressSaved", requested_path: "/sample/project",
    baseline: { repository: "/sample/project", documents: { "README.md": "abc" },
      requirements: [make("one", "로그인"), make("two", "가입")], version: 1 } }));
  fireEvent.click(screen.getByText(/로그인/, { selector: "strong" }));
  expect(screen.getByText(/같은 항목: docs\/b\.md:4/)).toBeTruthy();
  fireEvent.click(screen.getByText(/가입/, { selector: "strong" }));
  act(() => emit({ type: "progressError", requested_path: "/sample/project",
    message: "2개 항목을 확인해 주세요. 첫 오류: 줄 번호", errors: [
      { id: "two", field: "criterion", message: "완료 조건을 500자 이하로 입력해 주세요." },
      { id: "one", field: "title", message: "기능 이름을 500자 이하로 입력해 주세요." },
    ] }));
  expect(screen.getByText("2개 항목을 확인하세요.")).toBeTruthy();
  expect(screen.getByText("완료 조건을 500자 이하로 입력해 주세요.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "첫 항목으로 이동" }));
  await waitFor(() => expect(document.activeElement?.getAttribute("data-field")).toBe("title"));
  fireEvent.change(document.activeElement as HTMLInputElement, { target: { value: "로그인 화면" } });
  expect(screen.getByText("1개 항목을 확인하세요.")).toBeTruthy();
});

it("applies progress events that arrive in the same render batch", async () => {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "프로젝트 현황" }));
  await waitFor(() => expect(api.listProjectDocs).toHaveBeenCalledWith("/sample/project"));
  const { act } = await import("react");
  const source = { path: "README.md", line: 2, excerpt: "- [x] 로그인", sha256: "abc" };
  const item = {
    id: "one", title: "서버가 정규화한 제목", criterion: "로그인", area: "계정", included: true, source,
    implementation_status: "unknown" as const, evidence: null,
    verification_status: "unverified" as const, verification_note: "",
  };
  act(() => {
    emit({ type: "progressSaved", requested_path: "/sample/project",
      baseline: { repository: "/sample/project", documents: { "README.md": "abc" }, requirements: [item], version: 1 } });
    emit({ type: "progressReport", requested_path: "/sample/project", report: {
      repository: "/sample/project", version: 1, at: "2026-09-29T00:00:00Z", head: "abc",
      stale_documents: [], total: 1, limitations: "", items: [item],
      counts: { implemented: 0, partial: 0, not_implemented: 0, unknown: 1, complete: 0, excluded: 0 },
    } });
  });
  expect(screen.getByText("서버가 정규화한 제목", { selector: "strong" })).toBeTruthy();
  expect(screen.getAllByText("0 / 1").length).toBe(2);
});

it("flags document checkmarks without evidence, checks links and exports the report", async () => {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "프로젝트 현황" }));
  await waitFor(() => expect(api.listProjectDocs).toHaveBeenCalledWith("/sample/project"));
  const { act } = await import("react");
  const source = { path: "README.md", line: 2, excerpt: "- [x] 로그인", sha256: "abc" };
  const make = (id: string, title: string) => ({
    id, title, criterion: title, area: "계정", included: true, source, doc_marked_done: true,
    implementation_status: "unknown" as const, evidence: null,
    verification_status: "unverified" as const, verification_note: "",
  });
  const items = [make("one", "로그인"), { ...make("two", "가입"), doc_marked_done: false }];
  act(() => emit({ type: "progressSaved", requested_path: "/sample/project",
    baseline: { repository: "/sample/project", documents: { "README.md": "abc" }, requirements: items, version: 1 } }));
  expect(screen.queryByText(/코드 근거가 확인되지 않은 항목이/)).toBeNull();
  act(() => emit({ type: "progressReport", requested_path: "/sample/project", report: {
    repository: "/sample/project", version: 1, at: "2026-09-29T00:00:00Z", head: "abc",
    stale_documents: [], total: 2, limitations: "", doc_claims_unbacked: 1,
    items: [{ ...items[0], effective_status: "unknown", doc_claim: "unbacked" }, { ...items[1], effective_status: "unknown" }],
    counts: { implemented: 0, partial: 0, not_implemented: 0, unknown: 2, complete: 0, excluded: 0 },
  } }));
  expect(screen.getByText(/코드 근거가 확인되지 않은 항목이 1개/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "해당 항목 보기" }));
  const list = screen.getByLabelText("기능 목록");
  expect(list.textContent).toContain("로그인");
  expect(list.textContent).toContain("문서는 완료 표시, 근거 없음");
  expect(list.textContent).not.toContain("가입");

  fireEvent.click(screen.getByRole("button", { name: "문서 링크 점검" }));
  expect(api.checkProgressLinks).toHaveBeenCalledWith("/sample/project");
  act(() => emit({ type: "progressLinks", requested_path: "/sample/project", documents: ["README.md"], checked: 3,
    truncated: false, limitations: "앵커는 검사하지 않습니다.", issues: [
      { path: "README.md", line: 5, target: "docs/gone.md", kind: "link", confidence: "high", message: "대상을 찾을 수 없습니다" },
      { path: "README.md", line: 6, target: "app/main.py", kind: "path", confidence: "low", message: "대상을 찾을 수 없습니다" },
    ] }));
  expect(screen.getByText(/docs\/gone\.md · 대상을 찾을 수 없습니다/)).toBeTruthy();
  expect(screen.getByText(/확인이 필요한 파일 경로 1개/)).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "Markdown 저장" }));
  expect(api.exportProgress).toHaveBeenCalledWith("/sample/project", "md");
  act(() => emit({ type: "progressExported", requested_path: "/sample/project", file: "/tmp/x.md" }));
  expect(screen.getByText("저장했습니다 · /tmp/x.md")).toBeTruthy();
});

it("tells the review screen which saved evidence a scan touches and opens that item in progress", async () => {
  const value = fixture as Scan;
  render(<App initialScan={value} />);
  await waitFor(() => expect(screen.getByText("데스크톱 연결됨")).toBeTruthy());
  const { act } = await import("react");
  const impact = { type: "scanImpact", requested_path: "/sample/project", version: 2, documents: [
    { path: "README.md", invalidated: false }], items: [
    { id: "two", title: "가입", path: "src/routes/users.py", line: 3, change: "modified", invalidated: true },
    { id: "one", title: "로그인", path: "src/login.py", line: 1, change: "deleted", invalidated: false }] };
  act(() => emit({ ...impact, scan_at: "some-older-scan" }));
  expect(screen.queryByLabelText("프로젝트 현황 영향")).toBeNull();
  act(() => emit({ ...impact, scan_at: value.at }));
  const section = screen.getByLabelText("프로젝트 현황 영향");
  expect(section.textContent).toContain("1개 기능은 저장된 근거와 현재 코드가 달라");
  expect(section.textContent).toContain("근거 무효");
  expect(section.textContent).toContain("삭제");
  fireEvent.click(screen.getAllByRole("button", { name: "현황에서 보기" })[0]);
  await waitFor(() => expect(api.listProjectDocs).toHaveBeenCalledWith("/sample/project"));
  const source = { path: "README.md", line: 2, excerpt: "- [x] 로그인", sha256: "abc" };
  const make = (id: string, title: string) => ({
    id, title, criterion: title, area: "계정", included: true, source,
    implementation_status: "unknown" as const, evidence: null,
    verification_status: "unverified" as const, verification_note: "",
  });
  act(() => emit({ type: "progressDocs", requested_path: "/sample/project", documents: [], omitted: 0,
    baseline: { repository: "/sample/project", documents: { "README.md": "abc" },
      requirements: [make("one", "로그인"), make("two", "가입")], version: 2 } }));
  await waitFor(() => expect((screen.getByLabelText("기능명") as HTMLInputElement).value).toBe("가입"));
});

it("offers to create a starter policy when the repository has none, then scans again", async () => {
  render(<App />);
  await waitFor(() => expect(screen.getByText("데스크톱 연결됨")).toBeTruthy());
  const { act } = await import("react");
  act(() => emit({ type: "policyMissing", repository: "/sample/project" }));
  expect(api.previewPolicy).toHaveBeenCalledWith("/sample/project", "auto");
  expect(screen.getByText("저장소를 살펴보는 중…")).toBeTruthy();
  const preview = { type: "policyPreview", repository: "/sample/project", exists: false, preset: "api",
    presets: ["auto", "api", "db"], policy: "rules:\n  - id: api-contract-sync\n",
    recommendations: { presets: ["api"], frameworks: ["FastAPI"], docs_paths: ["docs/api/**"] } };
  act(() => emit(preview));
  expect(screen.getByLabelText("만들 정책 파일 내용").textContent).toContain("api-contract-sync");
  expect(screen.getByText(/감지한 프레임워크: FastAPI/)).toBeTruthy();
  expect(api.createPolicy).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("시작용 정책"), { target: { value: "db" } });
  expect(api.previewPolicy).toHaveBeenLastCalledWith("/sample/project", "db");
  fireEvent.click(screen.getByRole("button", { name: /\.drift-gate\.yml 만들고 검사/ }));
  expect(api.createPolicy).toHaveBeenCalledWith("/sample/project", "db");
  act(() => emit({ type: "policyCreated", repository: "/sample/project", path: "/sample/project/.drift-gate.yml", preset: "db" }));
  await waitFor(() => expect(api.startScan).toHaveBeenCalledWith("/sample/project", "HEAD"));
  expect(screen.queryByLabelText("정책 파일 만들기")).toBeNull();
  expect(screen.getByText(/정책 파일을 만들었습니다/)).toBeTruthy();
});
