// @vitest-environment jsdom
import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { Scan } from "../../bridge";
import fixture from "../../preview-fixture.json";
import AnalysisNotice from "./AnalysisNotice";
afterEach(cleanup);
it("shows limited analysis and the affected files without changing the gate verdict", () => {
  const scan: Scan = { ...fixture, result: { ...fixture.result, scan_metrics: { analysis_notes: [
    { path: "src/a.py", method: "heuristic", reason: "Tree-sitter unavailable (checksum mismatch)" },
    { path: "src/b.ts", method: "grammar+heuristic", reason: "" },
    { path: "src/c.go", method: "unavailable", reason: "Patch unavailable" },
  ] } } };
  render(<AnalysisNotice scan={scan} />);
  expect(screen.getByRole("status").textContent).toContain("문법 분석을 적용하지 못한 파일 2개");
  expect(screen.getByText("src/a.py")).toBeTruthy();
  expect(screen.getByText(/설치 파일을 다시 확인/)).toBeTruthy();
  expect(screen.queryByText("src/b.ts")).toBeNull();
});
it("adds no warning when every file has grammar analysis or an old report has no notes", () => {
  const scan: Scan = { ...fixture, result: { ...fixture.result, scan_metrics: { analysis_notes: [
    { path: "src/a.py", method: "grammar+heuristic" },
  ] } } };
  const page = render(<AnalysisNotice scan={scan} />);
  expect(screen.queryByRole("status")).toBeNull();
  page.rerender(<AnalysisNotice scan={{ ...scan, result: { ...scan.result, scan_metrics: undefined } }} />);
  expect(screen.queryByRole("status")).toBeNull();
});
it("keeps contract uncertainty visible even with complete grammar analysis", () => {
  const scan: Scan = { ...fixture, result: { ...fixture.result, rule_decisions: [{
    rule_id: "api-schema", status: "undetermined", reason: "missing snapshot",
    decision: "undetermined", verification: "unverified", trigger_files: ["src/api.py"],
    satisfied_groups: [], unsatisfied_groups: [{ name: "API", verification: "unverified", evidence: "complete before/after source is unavailable" }],
  }], scan_metrics: { analysis_notes: [{ path: "src/api.py", method: "grammar+heuristic" }] } } };
  render(<AnalysisNotice scan={scan} />);
  expect(screen.getByRole("status").textContent).toContain("내용 검증이 끝나지 않은 규칙 1개");
  expect(screen.getByText(/판단 보류/)).toBeTruthy();
  expect(screen.getByText(/complete before\/after/)).toBeTruthy();
});
it("explains legacy path fallback on a passing report", () => {
  const scan: Scan = { ...fixture, result: { ...fixture.result, result: "pass", rule_decisions: [{
    rule_id: "legacy", status: "pass", reason: "paths", decision: "satisfied", verification: "unverified",
    trigger_files: [], unsatisfied_groups: [], satisfied_groups: [{ name: "docs", verification: "unverified", evidence: "Legacy auto fallback" }],
  }] } };
  render(<AnalysisNotice scan={scan} />);
  expect(screen.getByRole("status").textContent).toContain("파일 조건 충족 · 내용 미검증");
  expect(screen.getByText(/자동 모드에서는 파일 변경/)).toBeTruthy();
});
