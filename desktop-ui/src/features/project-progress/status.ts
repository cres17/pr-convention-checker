import type { ProgressItem, ProgressReport } from "../../bridge";

export type EffectiveStatus = ProgressItem["implementation_status"];

/** The status counted by the summary cards; list badges and filters must use the same value. */
export function effectiveStatus(item: ProgressItem, report: ProgressReport | null): EffectiveStatus {
  const analysed = report?.items.find((entry) => entry.id === item.id);
  if (analysed?.effective_status && analysed.effective_status !== "excluded") return analysed.effective_status;
  return item.implementation_status;
}

export function isStaleEvidence(item: ProgressItem, report: ProgressReport | null): boolean {
  return report?.items.find((entry) => entry.id === item.id)?.stale_evidence ?? item.stale_evidence ?? false;
}

/** The document ticked this item as done, but no current code evidence backs it. */
export function docClaimUnbacked(item: ProgressItem, report: ProgressReport | null): boolean {
  return (report?.items.find((entry) => entry.id === item.id)?.doc_claim ?? null) === "unbacked";
}
