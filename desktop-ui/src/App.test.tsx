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
import type { Scan, ProgressItem, ProgressReport } from "./bridge";
import type { DesktopEvent } from "./events";
// Full App renders exceeded vitest's 5 s default on the macOS Intel runner
// (Desktop app build runs 37741382186 and 37742364446, 2026-10-08) while passing elsewhere.
vi.setConfig({ testTimeout: 20_000 });
const api = vi.hoisted(() => ({
  setProgressDirty: vi.fn(),
  startScan: vi.fn(),
  previewReview: vi.fn(),
  startReview: vi.fn(),
  chooseRepository: vi.fn(),
  cancelReview: vi.fn(),
  exportReport: vi.fn(),
  openDocument: vi.fn(),
  checkProgressLinks: vi.fn(),
  loadTestResults: vi.fn(),
  forgetTestResults: vi.fn(),
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
let emit: (event: DesktopEvent) => void;
vi.mock("./bridge", () => ({
  connect: (fn: (event: DesktopEvent) => void) => {
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
  CodeDiff: ({ patch }: { patch: string }) => <pre>{patch}</pre>,
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
  await waitFor(() => expect(api.listProjectDocs).toHaveBeenCalledWith("/sample/project", expect.any(String)));
  const { act } = await import("react");
  act(() => emit({ type: "progressDocs", repository: "/sample/project", documents: [
    { path: "README.md", tracked: true, bytes: 100 },
  ], omitted: 0, baseline: null }));
  fireEvent.click(screen.getByRole("button", { name: "기능 후보 추출" }));
  expect(api.previewProgress).toHaveBeenCalledWith("/sample/project", '[{"path":"README.md","kind":"current"}]', expect.any(String));
  const source = { path: "README.md", line: 2, excerpt: "- [x] 로그인", sha256: "abc" };
  act(() => emit({ type: "progressPreview", repository: "/sample/project",
    documents: { "README.md": "abc" }, requirements: [{
      id: "one", title: "로그인", criterion: "로그인", area: "계정", included: true,
      source, implementation_status: "unknown", evidence: null,
      verification_status: "unverified", verification_note: "",
    }], truncated: false }));
  expect(screen.getByText("기준 저장 필요")).toBeTruthy();
  expect(screen.getAllByText("근거 없음").length).toBeGreaterThan(0);
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
  await waitFor(() => expect(api.listProjectDocs).toHaveBeenCalledWith("/sample/project", expect.any(String)));
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
  expect(screen.getByLabelText("기능 목록").querySelectorAll(".progress-status.recheck").length).toBe(1);
  fireEvent.change(screen.getByLabelText("목록 필터"), { target: { value: "recheck" } });
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

it("keeps unknown contracts in the action filter without inventing a violation", () => {
  const value = structuredClone(fixture) as Scan;
  value.result.violations = [];
  value.result.rule_decisions = [{ rule_id: "unknown-contract", status: "undetermined", reason: "source unavailable",
    decision: "undetermined", verification: "unverified", trigger_files: ["src/api.py"], satisfied_groups: [],
    unsatisfied_groups: [{ name: "response schema", decision: "undetermined", verification: "unverified", evidence: "source unavailable" }],
  }];
  render(<App initialScan={value} />);
  fireEvent.click(screen.getByRole("button", { name: "조치 필요" }));
  expect(screen.getAllByText("판단 보류").length).toBeGreaterThan(0);
  expect(screen.getAllByText(/내용을 확인하지 못해 판단을 보류했습니다/).length).toBeGreaterThan(0);
  expect(screen.queryByText(/반영되지 않은 문서 조건/)).toBeNull();
});

it("marks every invalid item after a failed save and jumps to the first one", async () => {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "프로젝트 현황" }));
  await waitFor(() => expect(api.listProjectDocs).toHaveBeenCalledWith("/sample/project", expect.any(String)));
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
  await waitFor(() => expect(api.listProjectDocs).toHaveBeenCalledWith("/sample/project", expect.any(String)));
  const { act } = await import("react");
  const source = { path: "README.md", line: 2, excerpt: "- [x] 로그인", sha256: "abc" };
  const item: ProgressItem = {
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
  await waitFor(() => expect(api.listProjectDocs).toHaveBeenCalledWith("/sample/project", expect.any(String)));
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
  expect(api.checkProgressLinks).toHaveBeenCalledWith("/sample/project", expect.any(String));
  act(() => emit({ type: "progressLinks", requested_path: "/sample/project", documents: ["README.md"], checked: 3,
    truncated: false, limitations: "앵커는 검사하지 않습니다.", issues: [
      { path: "README.md", line: 5, target: "docs/gone.md", kind: "link", confidence: "high", message: "대상을 찾을 수 없습니다" },
      { path: "README.md", line: 6, target: "app/main.py", kind: "path", confidence: "low", message: "대상을 찾을 수 없습니다" },
    ] }));
  expect(screen.getByText(/docs\/gone\.md · 대상을 찾을 수 없습니다/)).toBeTruthy();
  expect(screen.getByText(/확인이 필요한 파일 경로 1개/)).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "Markdown 저장" }));
  expect(api.exportProgress).toHaveBeenCalledWith("/sample/project", "md", expect.any(String));
  act(() => emit({ type: "progressExported", requested_path: "/sample/project", file: "/tmp/x.md" }));
  expect(screen.getByText("저장했습니다 · /tmp/x.md")).toBeTruthy();
});

it("tells the review screen which saved evidence a scan touches and opens that item in progress", async () => {
  const value = fixture as Scan;
  render(<App initialScan={value} />);
  await waitFor(() => expect(screen.getByText("데스크톱 연결됨")).toBeTruthy());
  const { act } = await import("react");
  const impact = { type: "scanImpact" as const, requested_path: "/sample/project", version: 2, documents: [
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
  await waitFor(() => expect(api.listProjectDocs).toHaveBeenCalledWith("/sample/project", expect.any(String)));
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
  const preview = { type: "policyPreview" as const, repository: "/sample/project", exists: false, preset: "api",
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

it("shows what changed since the last save and the list of saved states", async () => {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "프로젝트 현황" }));
  await waitFor(() => expect(api.listProjectDocs).toHaveBeenCalledWith("/sample/project", expect.any(String)));
  const { act } = await import("react");
  const source = { path: "README.md", line: 2, excerpt: "- [x] 로그인", sha256: "abc" };
  const item: ProgressItem = { id: "one", title: "로그인", criterion: "로그인", area: "계정", included: true, source,
    implementation_status: "unknown" as const, evidence: null,
    verification_status: "unverified" as const, verification_note: "" };
  act(() => emit({ type: "progressSaved", requested_path: "/sample/project",
    baseline: { repository: "/sample/project", documents: { "README.md": "abc" }, requirements: [item], version: 3 } }));
  expect(screen.queryByText(/마지막 저장/)).toBeNull();
  act(() => emit({ type: "progressHistory", requested_path: "/sample/project",
    since_save: { since: "2026-09-29T00:00:00Z", version: 3, complete_delta: -1,
      counts: { regressed: 1, gained: 0 }, regressed: [{ id: "one", title: "로그인" }], gained: [], excluded: [],
      reincluded: [], added: [], removed: [] },
    snapshots: [
      { at: "2026-09-29T00:00:00Z", version: 3, head: "abc", total: 2, counts: { complete: 1, implemented: 2 },
        changes: { gained: 2, regressed: 0 }, complete_delta: 1 },
      { at: "2026-09-28T00:00:00Z", version: 2, head: "abc", total: 2, counts: { complete: 0, implemented: 0 } },
    ] }));
  const notice = screen.getByText(/마지막 저장\(기준 v3\) 이후 변화/);
  expect(notice.textContent).toContain("회귀(구현 확인 → 아님) 1");
  expect(notice.textContent).toContain("완료 확인 -1");
  expect(notice.textContent).toContain("회귀: 로그인");
  expect(screen.getByText("진행 이력 2개")).toBeTruthy();
  expect(screen.getByText("새로 구현 확인 2")).toBeTruthy();
  expect(screen.getByText("첫 기록")).toBeTruthy();
});

it("links a test-result file to items without changing the progress counts", async () => {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "프로젝트 현황" }));
  await waitFor(() => expect(api.listProjectDocs).toHaveBeenCalledWith("/sample/project", expect.any(String)));
  const { act } = await import("react");
  const source = { path: "README.md", line: 2, excerpt: "- [x] 로그인", sha256: "abc" };
  const item: ProgressItem = { id: "abcdef1234567890", title: "로그인", criterion: "로그인", area: "계정", included: true, source,
    implementation_status: "implemented" as const, evidence: null, test_patterns: ["test_login"],
    verification_status: "verified" as const, verification_note: "수동 확인" };
  act(() => emit({ type: "progressSaved", requested_path: "/sample/project",
    baseline: { repository: "/sample/project", documents: { "README.md": "abc" }, requirements: [item], version: 1 } }));
  act(() => emit({ type: "progressReport", requested_path: "/sample/project", report: {
    repository: "/sample/project", version: 1, at: "2026-09-29T00:00:00Z", head: "abc",
    stale_documents: [], total: 1, limitations: "", items: [{ ...item, effective_status: "implemented" }],
    counts: { implemented: 1, partial: 0, not_implemented: 0, unknown: 0, complete: 1, excluded: 0 } } }));
  fireEvent.click(screen.getByText(/로그인/, { selector: "strong" }));
  expect(screen.getByText("req-abcdef12")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "테스트 결과 불러오기" }));
  expect(api.loadTestResults).toHaveBeenCalledWith("/sample/project", expect.any(String));
  act(() => emit({ type: "progressTests", requested_path: "/sample/project", format: "junit", file: "junit.xml",
    modified: "2026-09-29T00:00:00Z", total: 9, items: { abcdef1234567890: { patterns: ["test_login"], matched: 3,
      passed: 2, failed: 1, skipped: 0, failing: ["tests.test_auth::test_login_bad"], no_match: false } } }));
  expect(screen.getByText(/테스트 결과: junit\.xml · JUnit XML · 테스트 9개/)).toBeTruthy();
  expect(screen.getByLabelText("기능 목록").textContent).toContain("자동 검증: 통과 2 · 실패 1");
  const record = screen.getByLabelText("자동 검증 기록");
  expect(record.textContent).toContain("tests.test_auth::test_login_bad");
  expect(record.textContent).toContain("수동 확인으로 기록됐지만 연결된 테스트가 실패했습니다");
  expect(screen.getAllByText("1 / 1").length).toBeGreaterThan(0);  // the summary counts stay as saved
  expect(screen.queryByText(/이전에 선택한 파일을 다시 읽었습니다/)).toBeNull();
  act(() => emit({ type: "progressTests", requested_path: "/sample/project", format: "junit", file: "junit.xml",
    modified: "2026-09-29T00:00:00Z", total: 9, remembered: true, items: { abcdef1234567890: { patterns: ["test_login"],
      matched: 3, passed: 3, failed: 0, skipped: 0, failing: [], no_match: false, code_newer: true } } }));
  expect(screen.getByText(/이전에 선택한 파일을 다시 읽었습니다/)).toBeTruthy();
  expect(screen.getByLabelText("기능 목록").textContent).toContain("(결과가 코드보다 오래됨)");
  expect(screen.getByText(/결과 파일보다 근거 코드가 나중에 바뀌었습니다/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "파일 기억 해제" }));
  expect(api.forgetTestResults).toHaveBeenCalledWith("/sample/project");
  expect(screen.queryByText(/테스트 결과: junit\.xml/)).toBeNull();
  fireEvent.change(screen.getByLabelText(/관련 테스트 이름/), { target: { value: "test_login, test_logout" } });
  expect((screen.getByLabelText(/관련 테스트 이름/) as HTMLInputElement).value).toBe("test_login, test_logout");
});

it("warns about test-name patterns that no repository test file contains", async () => {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "프로젝트 현황" }));
  await waitFor(() => expect(api.listProjectDocs).toHaveBeenCalledWith("/sample/project", expect.any(String)));
  const { act } = await import("react");
  const source = { path: "README.md", line: 2, excerpt: "- [x] 로그인", sha256: "abc" };
  const item: ProgressItem = { id: "one", title: "로그인", criterion: "로그인", area: "계정", included: true, source,
    implementation_status: "unknown" as const, evidence: null, test_patterns: ["test_logn"],
    verification_status: "unverified" as const, verification_note: "" };
  act(() => emit({ type: "progressSaved", requested_path: "/sample/project",
    baseline: { repository: "/sample/project", documents: { "README.md": "abc" }, requirements: [item], version: 1 } }));
  act(() => emit({ type: "progressReport", requested_path: "/sample/project", report: {
    repository: "/sample/project", version: 1, at: "2026-09-29T00:00:00Z", head: "abc", stale_documents: [], total: 1,
    limitations: "", test_pattern_hints: { one: ["test_logn"] }, items: [{ ...item, effective_status: "unknown" }],
    counts: { implemented: 0, partial: 0, not_implemented: 0, unknown: 1, complete: 0, excluded: 0 } } }));
  fireEvent.click(screen.getByText(/로그인/, { selector: "strong" }));
  expect(screen.getByText(/저장소의 테스트 파일에서 찾지 못한 이름: test_logn/)).toBeTruthy();
});

it("sends explicit document roles and preserves evidence when changing a saved role", async () => {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "프로젝트 현황" }));
  await waitFor(() => expect(api.listProjectDocs).toHaveBeenCalled());
  const { act } = await import("react");
  const item: ProgressItem = { id: "role-one", title: "로그인", criterion: "로그인", included: true, area: "계정",
    source: { path: "README.md", line: 1, excerpt: "- [ ] 로그인", sha256: "h" },
    implementation_status: "implemented", evidence: { path: "src/login.py", line: 1, note: "정의 확인", sha256: "code" },
    verification_status: "unverified", verification_note: "" };
  act(() => emit({ type: "progressDocs", documents: [
    { path: "README.md", tracked: true, bytes: 100 }, { path: "past.md", tracked: true, bytes: 100 },
  ], omitted: 0, baseline: { repository: "/sample/project", documents: { "README.md": "h", "past.md": "p" },
    document_kinds: { "README.md": "current", "past.md": "past" }, requirements: [item], version: 1 } }));
  fireEvent.click(screen.getByRole("button", { name: "기준 문서 변경" }));
  expect((screen.getByLabelText("past.md의 문서 종류") as HTMLSelectElement).value).toBe("past");
  fireEvent.change(screen.getByLabelText("README.md의 문서 종류"), { target: { value: "future" } });
  expect(screen.getByLabelText("기능 목록").textContent).not.toContain("로그인");
  fireEvent.change(screen.getByLabelText("목록 필터"), { target: { value: "excluded" } });
  expect(screen.getByLabelText("기능 목록").textContent).toContain("로그인");
  fireEvent.click(screen.getByRole("button", { name: "기준과 근거 저장" }));
  const saved = JSON.parse(api.saveProgress.mock.calls[0][1]);
  expect(saved.document_kinds).toEqual({ "README.md": "future", "past.md": "past" });
  expect(saved.requirements[0].evidence).toEqual(item.evidence);
  act(() => emit({ type: "progressSaved", baseline: saved }));
  fireEvent.click(screen.getByRole("button", { name: "기준 문서 변경" }));
  fireEvent.click(screen.getByRole("button", { name: "기능 후보 추출" }));
  expect(JSON.parse(api.previewProgress.mock.calls[0][1])).toEqual([
    { path: "README.md", kind: "future" }, { path: "past.md", kind: "past" },
  ]);
});

it("filters summary cards by effective status, clears search and includes verified subset only", async () => {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "프로젝트 현황" }));
  await waitFor(() => expect(api.listProjectDocs).toHaveBeenCalled());
  const { act } = await import("react");
  const make = (id: string, status: ProgressItem["implementation_status"], verified = false, sourcePath = "README.md"): ProgressItem => ({
    id, title: id, criterion: id, area: "기능", included: true,
    source: { path: sourcePath, line: 1, excerpt: id, sha256: "h" }, implementation_status: status,
    verification_status: verified ? "verified" : "unverified", verification_note: verified ? "확인" : "",
    evidence: status === "implemented" ? { path: "src/x.py", line: 1, note: "확인" } : null,
  });
  const items = [make("완료기능", "implemented", true), make("구현기능", "implemented"),
    make("변경기능", "implemented", true), make("미확인기능", "unknown"), make("과거기능", "implemented", true, "past.md")];
  act(() => emit({ type: "progressSaved", baseline: { repository: "/sample/project", documents: { "README.md": "h", "past.md": "h" },
    document_kinds: { "README.md": "current", "past.md": "past" }, requirements: items } }));
  act(() => emit({ type: "progressReport", report: { repository: "/sample/project", version: 1, at: "2026-10-01", head: "abc", stale_documents: [], total: 4,
    counts: { complete: 1, implemented: 2, partial: 0, not_implemented: 0, unknown: 2, excluded: 1 },
    items: items.map((item) => ({ ...item, effective_status: item.id === "변경기능" ? "unknown" : item.id === "과거기능" ? "excluded" : item.implementation_status, stale_evidence: item.id === "변경기능" })), limitations: "수동 기준" } }));
  fireEvent.change(screen.getByLabelText("기능 검색"), { target: { value: "없는 검색어" } });
  const complete = screen.getByRole("button", { name: /^완료 확인 1/ });
  fireEvent.click(complete);
  expect(complete.getAttribute("aria-pressed")).toBe("true");
  expect((screen.getByLabelText("기능 검색") as HTMLInputElement).value).toBe("");
  expect(screen.getByLabelText("기능 목록").querySelectorAll("button").length).toBe(1);
  expect(screen.getByLabelText("기능 목록").textContent).toContain("완료기능");
  fireEvent.click(screen.getByRole("button", { name: /^구현 확인 2/ }));
  expect(screen.getByLabelText("기능 목록").querySelectorAll("button").length).toBe(2);
  expect(screen.getByLabelText("기능 목록").textContent).not.toContain("변경기능");
  fireEvent.click(screen.getByRole("button", { name: /^재확인 필요 1/ }));
  expect(screen.getByLabelText("기능 목록").querySelectorAll("button").length).toBe(1);
  expect(screen.getByLabelText("기능 목록").textContent).toContain("변경기능");
  expect(screen.getByLabelText("기능 목록").textContent).not.toContain("미확인기능");
  fireEvent.click(screen.getByRole("button", { name: /^근거 없음 1/ }));
  expect(screen.getByLabelText("기능 목록").querySelectorAll("button").length).toBe(1);
  expect(screen.getByLabelText("기능 목록").textContent).toContain("미확인기능");
  expect(screen.getByLabelText("기능 목록").textContent).not.toContain("변경기능");
  expect(screen.getByLabelText("기능 목록").textContent).not.toContain("과거기능");
  expect(screen.getByTitle("구현 확인 2개")).toBeTruthy();
});

it("guides first evidence input without implying real development progress, then guides stale evidence separately", async () => {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "프로젝트 현황" }));
  await waitFor(() => expect(api.listProjectDocs).toHaveBeenCalled());
  const { act } = await import("react");
  const item: ProgressItem = { id: "first", title: "첫기능", criterion: "조건", included: true, area: "기능",
    source: { path: "README.md", line: 1, excerpt: "조건", sha256: "h" }, implementation_status: "unknown", evidence: null,
    verification_status: "unverified", verification_note: "" };
  act(() => emit({ type: "progressSaved", baseline: { repository: "/sample/project", documents: { "README.md": "h" }, requirements: [item] } }));
  const report: ProgressReport = { repository: "/sample/project", version: 1, at: "2026-10-01", head: "abc", stale_documents: [], total: 1,
    counts: { complete: 0, implemented: 0, partial: 0, not_implemented: 0, unknown: 1, excluded: 0 }, items: [item], limitations: "수동 기준" };
  act(() => emit({ type: "progressReport", report }));
  expect(screen.queryByRole("img", { name: /총 1개/ })).toBeNull();
  expect(screen.getByText(/이 수치는 실제 개발률이 아닙니다/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "첫 기능의 코드 근거 연결" }));
  expect(document.activeElement).toBe(screen.getByLabelText("코드 파일 경로"));
  act(() => emit({ type: "progressReport", report: { ...report, items: [{ ...item, stale_evidence: true }] } }));
  expect(screen.queryByRole("button", { name: "첫 기능의 코드 근거 연결" })).toBeNull();
  expect(screen.getByRole("button", { name: "재확인할 기능 보기" })).toBeTruthy();
  act(() => emit({ type: "progressReport", report: { ...report, total: 0, counts: { ...report.counts, unknown: 0, excluded: 1 } } }));
  expect(screen.getByText(/집계할 현재 목표가 없습니다/)).toBeTruthy();
  expect(screen.getAllByText(/대상 없음/).length).toBe(2);
});

it("calls a review warning 주의 so it differs from progress evidence states", () => {
  const value = structuredClone(fixture) as Scan;
  value.result.result = "warn";
  render(<App initialScan={value} />);
  expect(screen.getAllByText("주의").length).toBeGreaterThan(0);
  expect(screen.queryByText("확인 필요")).toBeNull();
});

it("keeps context-document changes from claiming the current progress needs resetting", async () => {
  render(<App initialScan={fixture as Scan} />);
  await waitFor(() => expect(screen.getByText("데스크톱 연결됨")).toBeTruthy());
  const { act } = await import("react");
  act(() => emit({ type: "scanImpact", scan_at: fixture.at, version: 1, items: [], documents: [
    { path: "past.md", invalidated: true, kind: "past" },
  ] }));
  expect(screen.getByText("참고 범위 문서 변경")).toBeTruthy();
  expect(screen.getByText("현재 목표 수치에는 영향을 주지 않습니다.")).toBeTruthy();
  expect(screen.queryByText("기준 문서가 바뀌어 현황 전체를 다시 확정해야 합니다.")).toBeNull();
});

const sessionBaseline = {
  repository: "/sample/project", version: 1, documents: { "README.md": "abc" },
  document_kinds: { "README.md": "current" as const }, requirements: [{
    id: "one", title: "기존 제목", criterion: "로그인", area: "계정", included: true,
    source: { path: "README.md", line: 2, excerpt: "로그인", sha256: "abc" },
    implementation_status: "unknown" as const, evidence: null,
    verification_status: "unverified" as const, verification_note: "",
  }],
};
async function openSessionEditor() {
  render(<App />);
  await waitFor(() => expect(screen.getByText("데스크톱 연결됨")).toBeTruthy());
  fireEvent.click(screen.getByRole("button", { name: "프로젝트 현황" }));
  const { act } = await import("react");
  act(() => emit({ type: "progressDocs", requested_path: "/sample/project",
    request_id: api.listProjectDocs.mock.calls.at(-1)?.[1], documents: [], omitted: 0, baseline: sessionBaseline }));
  return act;
}
it("preserves unsaved edits across page navigation", async () => {
  const act = await openSessionEditor();
  fireEvent.change(screen.getByLabelText("기능명"), { target: { value: "저장 전 수정" } });
  fireEvent.click(screen.getByRole("button", { name: "규칙" }));
  const showedWarning = !!screen.queryByText(/현황에 저장하지 않은 변경/);
  fireEvent.click(screen.getByRole("button", { name: "프로젝트 현황" }));
  act(() => emit({ type: "progressDocs", requested_path: "/sample/project", documents: [], omitted: 0, baseline: sessionBaseline }));
  expect((screen.getByLabelText("기능명") as HTMLInputElement).value).toBe("저장 전 수정");
  expect(api.saveProgress).not.toHaveBeenCalled();
  expect(showedWarning).toBe(true);
  expect(api.setProgressDirty).toHaveBeenLastCalledWith(true);
});
it("keeps an outstanding save locked across repository navigation, then ignores its replay after a new edit", async () => {
  const act = await openSessionEditor();
  fireEvent.click(screen.getByRole("button", { name: "기준과 근거 저장" }));
  const earlier = api.saveProgress.mock.calls.at(-1)?.[2];
  act(() => emit({ type: "repository", path: "/sample/other" }));
  act(() => emit({ type: "repository", path: "/sample/project" }));
  const current = api.listProjectDocs.mock.calls.at(-1)?.[1];
  act(() => emit({ type: "progressDocs", requested_path: "/sample/project", request_id: current,
    documents: [], omitted: 0, baseline: sessionBaseline }));
  expect(screen.getByLabelText('기능명').matches(':disabled')).toBe(true);
  act(() => emit({ type: "progressSaved", requested_path: "/sample/project", request_id: earlier,
    request_done: true, baseline: { ...sessionBaseline, version: 2 } }));
  expect(screen.getByLabelText('기능명').matches(':disabled')).toBe(false);
  fireEvent.change(screen.getByLabelText("기능명"), { target: { value: "돌아온 뒤 새 수정" } });
  act(() => emit({ type: "progressSaved", requested_path: "/sample/project", request_id: earlier,
    request_done: true, baseline: { ...sessionBaseline, version: 2 } }));
  expect((screen.getByLabelText("기능명") as HTMLInputElement).value).toBe("돌아온 뒤 새 수정");
  act(() => emit({ type: "repository", path: "/sample/other" }));
  act(() => emit({ type: "repository", path: "/sample/project" }));
  act(() => emit({ type: "progressDocs", requested_path: "/sample/project", request_id: api.listProjectDocs.mock.calls.at(-1)?.[1],
    documents: [], omitted: 0, baseline: sessionBaseline }));
  expect((screen.getByLabelText("기능명") as HTMLInputElement).value).toBe("돌아온 뒤 새 수정");
});
it("only accepts the current save and clears the unsaved-close warning", async () => {
  const act = await openSessionEditor();
  fireEvent.change(screen.getByLabelText("기능명"), { target: { value: "최신 편집" } });
  const unload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(unload);
  expect(unload.defaultPrevented).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "기준과 근거 저장" }));
  const [path, json, request_id] = api.saveProgress.mock.calls.at(-1)!;
  act(() => emit({ type: "progressSaved", requested_path: path, request_id,
    baseline: { ...JSON.parse(json), version: 2 } }));
  expect(api.setProgressDirty).toHaveBeenLastCalledWith(false);
  const cleanUnload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(cleanUnload);
  expect(cleanUnload.defaultPrevented).toBe(false);
});
