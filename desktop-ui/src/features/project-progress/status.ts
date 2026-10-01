import type {
  ProgressBaseline,
  ProgressItem,
  ProgressReport,
} from "../../bridge";

export function inCurrentScope(
  item: ProgressItem,
  baseline: ProgressBaseline,
): boolean {
  return (
    item.included &&
    [item.source, ...(item.duplicates ?? [])].some(
      (source) =>
        (baseline.document_kinds?.[source.path] ?? "current") === "current",
    )
  );
}

export type EffectiveStatus = ProgressItem["implementation_status"];

/** The status counted by the summary cards; list badges and filters must use the same value. */
export function effectiveStatus(
  item: ProgressItem,
  report: ProgressReport | null,
): EffectiveStatus {
  const analysed = report?.items.find((entry) => entry.id === item.id);
  if (analysed?.effective_status && analysed.effective_status !== "excluded")
    return analysed.effective_status;
  return item.implementation_status;
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
    const status = effectiveStatus(item, report);
    const complete =
      status === "implemented" && item.verification_status === "verified";
    if (filter === "complete" && !complete) return false;
    if (filter === "remaining" && complete) return false;
    if (filter === "implemented" && status !== "implemented") return false;
    if (filter === "unknown" && status !== "unknown") return false;
    if (filter === "claims" && !docClaimUnbacked(item, report)) return false;
    return `${item.title} ${item.area} ${item.criterion}`
      .toLowerCase()
      .includes(query.toLowerCase());
  });
}
