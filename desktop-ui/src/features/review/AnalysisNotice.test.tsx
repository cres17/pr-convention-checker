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
