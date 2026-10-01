import { expect, it } from "vitest";
import type { DocumentKind, ProgressBaseline, ProgressItem } from "../../bridge";
import { nextAction } from "./presentation";

const item: ProgressItem = {
  id: "goal", title: "기능", criterion: "조건", area: "기능", included: true,
  source: { path: "plan.md", line: 1, excerpt: "조건", sha256: "h" },
  implementation_status: "unknown", evidence: null,
  verification_status: "unverified", verification_note: "", stale_evidence: true,
};
const baseline = (kind: DocumentKind): ProgressBaseline => ({
  repository: "/sample", documents: { "plan.md": "h", "other.md": "h" },
  document_kinds: { "plan.md": kind, "other.md": "current" }, requirements: [item],
});

it.each(["past", "future", "reference"] as DocumentKind[])(
  "returns scope exclusion before evidence actions for a %s document",
  (kind) => expect(nextAction(item, null, baseline(kind)))
    .toBe("현재 목표 집계에서 제외 (기존 근거 유지)"),
);

it("keeps a goal with a current duplicate eligible but respects manual exclusion", () => {
  const shared = { ...item, stale_evidence: false, duplicates: [
    { path: "other.md", line: 1, excerpt: "조건", criterion: "조건" },
  ] };
  expect(nextAction(shared, null, baseline("past"))).toBe("코드 근거 확인");
  expect(nextAction({ ...shared, included: false }, null, baseline("past")))
    .toContain("제외");
});
