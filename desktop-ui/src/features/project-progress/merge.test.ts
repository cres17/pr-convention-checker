import { expect, it } from "vitest";
import type { ProgressBaseline, ProgressItem } from "../../bridge";
import { mergeProgressPreview } from "./merge";

const item = (id: string, path = "plan.md"): ProgressItem => ({
  id, title: id, criterion: id, area: "기능", included: true,
  source: { path, line: 1, excerpt: id, sha256: "old" },
  implementation_status: "unknown", evidence: null,
  verification_status: "unverified", verification_note: "",
});
const baseline = (requirements: ProgressItem[]): ProgressBaseline => ({
  repository: "/repo", documents: { "plan.md": "old", "past.md": "old" },
  document_kinds: { "plan.md": "current", "past.md": "past" }, requirements,
});

it("preserves all user fields and adds newly current document candidates once", () => {
  const old = item("login");
  Object.assign(old, {
    title: "사용자가 수정한 이름", criterion: "수정한 완료 조건", included: false,
    implementation_status: "implemented", implementation_note: "개인 기록",
    evidence: { path: "src/login.py", line: 1, sha256: "code", note: "구현 확인" },
    verification_status: "verified", verification_note: "수동 검증 기록",
    test_patterns: ["test_login"],
  });
  const previous = baseline([old]);
  const preview = baseline([item("login"), item("new", "past.md")]);
  preview.document_kinds!["past.md"] = "current";
  const merged = mergeProgressPreview(previous, preview);
  expect(merged.requirements[0]).toMatchObject(old);
  expect(merged.requirements.map((entry) => entry.id)).toEqual(["login", "new"]);
  expect(mergeProgressPreview(merged, preview)).toEqual(merged);
  expect(previous.requirements).toEqual([old]);
});

it("retains manual and absent candidates and moves deselected documents out of scope", () => {
  const manual = item("manual");
  manual.source.line = 0;
  manual.source.excerpt = "사용자가 직접 추가";
  const previous = baseline([manual, item("removed", "past.md")]);
  const preview = baseline([]);
  delete preview.documents["past.md"];
  delete preview.document_kinds!["past.md"];
  const merged = mergeProgressPreview(previous, preview);
  expect(merged.requirements.map((entry) => entry.id)).toEqual(["manual", "removed"]);
  expect(merged.documents["past.md"]).toBe("old");
  expect(merged.document_kinds!["past.md"]).toBe("reference");
});

it("refreshes candidate locations but preserves the earlier document review across repeated extractions", () => {
  const old = item("login");
  old.implementation_status = "implemented";
  const preview = baseline([item("login")]);
  preview.documents["plan.md"] = "new";
  preview.requirements[0].source.sha256 = "new";
  const merged = mergeProgressPreview(baseline([old]), preview);
  expect(merged.requirements[0].implementation_status).toBe("implemented");
  expect(merged.requirements[0].source.sha256).toBe("new");
  expect(merged.requirements[0].reviewed_documents).toEqual({ "plan.md": "old" });
  expect(merged.requirements[0].stale_requirement).toBe(true);
  expect(mergeProgressPreview(merged, preview)).toEqual(merged);
});

it("refuses overflow instead of silently dropping reviewed items", () => {
  const previous = baseline(Array.from({ length: 120 }, (_, n) => item(`old-${n}`)));
  expect(() => mergeProgressPreview(previous, baseline([item("new")]))).toThrow(/상한/);
  expect(previous.requirements).toHaveLength(120);
  const manyDocs = baseline([]);
  manyDocs.documents = Object.fromEntries(Array.from({ length: 10 }, (_, n) => [`doc-${n}.md`, "h"]));
  expect(() => mergeProgressPreview(manyDocs, baseline([]))).toThrow(/상한/);
});

it("refreshes current duplicate locations while retaining context document provenance", () => {
  const old = item("goal");
  old.duplicates = [
    { path: "other.md", line: 1, excerpt: "goal", criterion: "goal" },
    { path: "past.md", line: 2, excerpt: "goal", criterion: "goal" },
  ];
  const previous = baseline([old]);
  previous.documents["other.md"] = "old";
  previous.document_kinds!["other.md"] = "current";
  const preview = baseline([item("goal")]);
  preview.documents["other.md"] = "new";
  preview.document_kinds!["other.md"] = "current";
  const merged = mergeProgressPreview(previous, preview);
  expect(merged.requirements[0].duplicates).toEqual([old.duplicates[1]]);
  expect(merged.requirements[0].source).toEqual(old.source);
  expect(previous.requirements[0].duplicates).toHaveLength(2);
});

it("rejects duplicate provenance overflow instead of dropping preserved context locations", () => {
  const old = item("goal");
  old.duplicates = Array.from({ length: 20 }, (_, n) => ({ path: "past.md", line: n + 1, excerpt: "goal", criterion: "goal" }));
  const candidate = item("goal");
  candidate.duplicates = [{ path: "other.md", line: 1, excerpt: "goal", criterion: "goal" }];
  const preview = baseline([candidate]);
  preview.documents["other.md"] = "new";
  preview.document_kinds!["other.md"] = "current";
  const previous = baseline([old]);
  expect(() => mergeProgressPreview(previous, preview)).toThrow(/중복 출처 20개/);
  expect(previous.requirements[0].duplicates).toHaveLength(20);
});
