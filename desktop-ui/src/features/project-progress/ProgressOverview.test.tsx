// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { Bridge, ProgressBaseline, ProgressItem, ProgressReport } from "../../bridge";
import ProjectProgress from "./ProjectProgress";

afterEach(cleanup);
const item = (id: string, path = "README.md"): ProgressItem => ({
  id, title: id, criterion: id, area: "기능", included: true,
  source: { path, line: 1, excerpt: id, sha256: "h" },
  implementation_status: "unknown", evidence: null,
  verification_status: "unverified", verification_note: "",
});

function show(items: ProgressItem[], analysed: ProgressItem[], staleDocuments: string[] = []) {
  const baseline: ProgressBaseline = {
    repository: "/sample", documents: { "README.md": "h", "past.md": "h" },
    document_kinds: { "README.md": "current", "past.md": "past" }, requirements: items,
  };
  const current = analysed.filter((entry) => entry.included && entry.source.path !== "past.md");
  const report: ProgressReport = {
    repository: "/sample", version: 1, at: "2026-10-01", head: "abc",
    stale_documents: staleDocuments, items: analysed, total: current.length, limitations: "수동 근거 기준",
    counts: {
      complete: current.filter((entry) => entry.effective_status === "implemented" && entry.verification_status === "verified").length,
      implemented: current.filter((entry) => entry.effective_status === "implemented").length,
      partial: 0, not_implemented: 0,
      unknown: current.filter((entry) => entry.effective_status === "unknown").length,
      excluded: analysed.length - current.length,
    },
  };
  const bridge = { listProjectDocs: vi.fn(), inspectProgress: vi.fn() } as unknown as Bridge;
  const view = render(<ProjectProgress path="/sample" connected bridge={bridge} events={[]} />);
  view.rerender(<ProjectProgress path="/sample" connected bridge={bridge} events={[
    { type: "progressDocs", _seq: 1, documents: [], omitted: 0, baseline },
  ]} />);
  view.rerender(<ProjectProgress path="/sample" connected bridge={bridge} events={[
    { type: "progressReport", _seq: 2, report },
  ]} />);
  return screen.getByLabelText("기능 목록");
}

it("separates missing evidence and stale evidence cards and matches each count to its filter", () => {
  const payment = item("결제");
  payment.implementation_status = "implemented";
  payment.evidence = { path: "src/pay.py", line: 1, note: "확인", sha256: "old" };
  payment.verification_status = "verified";
  payment.verification_note = "이전 검증";
  const alert = item("알림");
  const ready = { ...payment, id: "완료", title: "완료" };
  const past = { ...payment, id: "과거", title: "과거", source: { ...payment.source, path: "past.md" } };
  const excluded = { ...item("범위 제외"), included: false };
  const items = [payment, alert, ready, past, excluded];
  const list = show(items, items.map((entry) => ({ ...entry,
    stale_evidence: entry.id === "결제" || entry.id === "과거" || entry.id === "범위 제외",
    effective_status: entry.id === "완료" ? "implemented" : entry.id === "과거" || !entry.included ? "excluded" : "unknown",
  })));
  const missingCard = screen.getByRole("button", { name: "근거 없음 1개 보기" });
  const recheckCard = screen.getByRole("button", { name: "재확인 필요 1개 보기" });
  expect(within(missingCard).getByText("1개")).toBeTruthy();
  expect(within(recheckCard).getByText("1개")).toBeTruthy();
  expect(screen.queryByText("근거 없음·재확인")).toBeNull();
  expect(screen.getByTitle("근거 없음 1개")).toBeTruthy();
  expect(screen.getByTitle("재확인 필요 1개")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("기능 검색"), { target: { value: "없는 검색어" } });
  fireEvent.click(recheckCard);
  expect((screen.getByLabelText("기능 검색") as HTMLInputElement).value).toBe("");
  expect((screen.getByLabelText("목록 필터") as HTMLSelectElement).value).toBe("recheck");
  expect(recheckCard.getAttribute("aria-pressed")).toBe("true");
  expect(list.querySelectorAll("button")).toHaveLength(1);
  expect(list.textContent).toContain("결제");
  fireEvent.click(missingCard);
  expect(missingCard.getAttribute("aria-pressed")).toBe("true");
  expect(recheckCard.getAttribute("aria-pressed")).toBe("false");
  expect(list.querySelectorAll("button")).toHaveLength(1);
  expect(list.textContent).toContain("알림");
  expect(list.textContent).not.toContain("결제");
});

it("classifies stale document review separately even without code evidence and directs both next actions", () => {
  const items = [item("문서 변경"), item("첫 근거")];
  const list = show(items, items.map((entry) => ({ ...entry,
    effective_status: "unknown", stale_requirement: entry.id === "문서 변경",
  })));
  expect(screen.getByRole("button", { name: "근거 없음 1개 보기" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "재확인 필요 1개 보기" })).toBeTruthy();
  expect(screen.getByText("근거가 없는 기능과 재확인할 기능이 있습니다.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "재확인할 기능 보기" }));
  expect(list.textContent).toContain("문서 변경");
  expect(list.textContent).not.toContain("첫 근거");
  fireEvent.click(screen.getByRole("button", { name: "근거 없는 기능 보기" }));
  expect(list.textContent).toContain("첫 근거");
  expect(list.textContent).not.toContain("문서 변경");
});

it("puts all items invalidated by a current document change into recheck and allows a zero-count filter", () => {
  const items = [item("문서 기준 기능")];
  const list = show(items, items.map((entry) => ({ ...entry, effective_status: "unknown" })), ["README.md"]);
  expect(screen.getByRole("button", { name: "재확인 필요 1개 보기" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "근거 없음 0개 보기" })).toBeTruthy();
  expect(within(list).getByText("재확인 필요")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "근거 없음 0개 보기" }));
  expect(list.querySelectorAll("button")).toHaveLength(0);
  expect(list.textContent).toContain("조건에 맞는 기능이 없습니다.");
});

it("shows zero for both cards when there are no current goals and excludes stale context items", () => {
  const past = item("과거 기능", "past.md");
  show([past], [{ ...past, effective_status: "excluded", stale_evidence: true }]);
  expect(screen.getByRole("button", { name: "근거 없음 0개 보기" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "재확인 필요 0개 보기" })).toBeTruthy();
  expect(screen.getByText(/집계할 현재 목표가 없습니다/)).toBeTruthy();
  expect(screen.queryByRole("img", { name: /총 0개/ })).toBeNull();
});

it.each([
  ["완료 확인", "complete"], ["구현 확인", "implemented"],
  ["근거 없음", "unknown"], ["재확인 필요", "recheck"],
])("toggles the %s card back to all items and clears search", (label, filter) => {
  const ready = { ...item("완료"), implementation_status: "implemented" as const,
    evidence: { path: "src/ready.py", line: 1, note: "확인" },
    verification_status: "verified" as const, verification_note: "검증 기록" };
  const stale = { ...ready, id: "변경", title: "변경" };
  const missing = item("미입력");
  const list = show([ready, stale, missing], [
    { ...ready, effective_status: "implemented" },
    { ...stale, effective_status: "unknown", stale_evidence: true },
    { ...missing, effective_status: "unknown" },
  ]);
  const card = screen.getByRole("button", { name: `${label} 1개 보기` });
  fireEvent.click(card);
  expect(card.getAttribute("aria-pressed")).toBe("true");
  expect((screen.getByLabelText("목록 필터") as HTMLSelectElement).value).toBe(filter);
  expect(list.querySelectorAll("button")).toHaveLength(1);
  fireEvent.change(screen.getByLabelText("기능 검색"), { target: { value: "없는 검색어" } });
  fireEvent.click(card);
  expect(card.getAttribute("aria-pressed")).toBe("false");
  expect((screen.getByLabelText("목록 필터") as HTMLSelectElement).value).toBe("all");
  expect((screen.getByLabelText("기능 검색") as HTMLInputElement).value).toBe("");
  expect(list.querySelectorAll("button")).toHaveLength(3);
});

it("also releases a zero-count card without creating a current-scope item", () => {
  const past = item("과거 기능", "past.md");
  const list = show([past], [{ ...past, effective_status: "excluded" }]);
  const card = screen.getByRole("button", { name: "근거 없음 0개 보기" });
  fireEvent.click(card);
  expect(card.getAttribute("aria-pressed")).toBe("true");
  fireEvent.click(card);
  expect(card.getAttribute("aria-pressed")).toBe("false");
  expect((screen.getByLabelText("목록 필터") as HTMLSelectElement).value).toBe("all");
  expect(list.querySelectorAll("button")).toHaveLength(0);
});
