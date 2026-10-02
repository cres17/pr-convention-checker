import type {
  ProgressBaseline,
  ProgressItem,
  ProgressReport,
} from "../../bridge";

import { requirementSources } from "./requirement";

export const progressFilterLabels = {
  all: "전체", complete: "완료 확인", implemented: "구현 확인", remaining: "남은 작업",
  unknown: "근거 없음", recheck: "재확인 필요", claims: "문서와 불일치", excluded: "제외",
} as const;
export type ProgressFilter = keyof typeof progressFilterLabels;
export function isProgressFilter(value: string): value is ProgressFilter {
  return Object.hasOwn(progressFilterLabels, value);
}

export function inCurrentScope(
  item: ProgressItem,
  baseline: ProgressBaseline,
): boolean {
  return (
    item.included &&
    requirementSources(item).some(
      (source) =>
        (baseline.document_kinds?.[source.path] ?? "current") === "current",
    )
  );
}

export type EffectiveStatus = ProgressItem["implementation_status"];
export type DisplayStatus = EffectiveStatus | "recheck";

/** Latest inspected implementation status; displayStatus separates rechecks. */
export function effectiveStatus(
  item: ProgressItem,
  report: ProgressReport | null,
): EffectiveStatus {
  const analysed = report?.items.find((entry) => entry.id === item.id);
  if (analysed?.effective_status && analysed.effective_status !== "excluded")
    return analysed.effective_status;
  return item.stale_requirement ? "unknown" : item.implementation_status;
}

export function isStaleRequirement(
  item: ProgressItem,
  baseline: ProgressBaseline,
  report: ProgressReport | null,
): boolean {
  return (
    report?.items.find((entry) => entry.id === item.id)?.stale_requirement ??
    Object.entries(
      item.reviewed_documents ?? { [item.source.path]: item.source.sha256 },
    ).some(([path, hash]) => baseline.documents[path] !== hash)
  );
}

export function isStaleEvidence(
  item: ProgressItem,
  report: ProgressReport | null,
): boolean {
  return (
    report?.items.find((entry) => entry.id === item.id)?.stale_evidence ??
    item.stale_evidence ??
    false
  );
}

/** Separate missing evidence from an earlier review invalidated by a change. */
export function displayStatus(
  item: ProgressItem,
  report: ProgressReport | null,
): DisplayStatus {
  const analysed = report?.items.find((entry) => entry.id === item.id);
  if (
    isStaleEvidence(item, report) ||
    report?.stale_documents.length ||
    (analysed?.stale_requirement ?? item.stale_requirement)
  )
    return "recheck";
  return effectiveStatus(item, report);
}

/** The document ticked this item as done, but no current code evidence backs it. */
export function docClaimUnbacked(
  item: ProgressItem,
  report: ProgressReport | null,
): boolean {
  return (
    (report?.items.find((entry) => entry.id === item.id)?.doc_claim ?? null) ===
    "unbacked"
  );
}

/** One scope and effective-status rule for all list entry points. */
export function filterProgressItems(
  baseline: ProgressBaseline | null,
  report: ProgressReport | null,
  filter: string,
  query: string,
): ProgressItem[] {
  if (!baseline) return [];
  return baseline.requirements.filter((item) => {
    const included = inCurrentScope(item, baseline);
    if (filter === "excluded" ? included : !included) return false;
    const status = displayStatus(item, report);
    const complete =
      status === "implemented" && item.verification_status === "verified";
    if (filter === "complete" && !complete) return false;
    if (filter === "remaining" && complete) return false;
    if (filter === "implemented" && status !== "implemented") return false;
    if (filter === "unknown" && status !== "unknown") return false;
    if (filter === "recheck" && status !== "recheck") return false;
    if (filter === "claims" && !docClaimUnbacked(item, report)) return false;
    return `${item.title} ${item.area} ${item.criterion}`
      .toLowerCase()
      .includes(query.toLowerCase());
  });
}
