import { MAX_REQUIREMENTS } from "./limits";
import type { ProgressBaseline, ProgressItem } from "../../bridge";
import { activeDocuments } from "./documents";

/** Primary and repeated document locations share the same scope/review rules. */
export function requirementSources(item: ProgressItem) {
  return [item.source, ...(item.duplicates ?? [])];
}

export function documentReview(item: ProgressItem, documents: Record<string, string>) {
  return Object.fromEntries(requirementSources(item).map((source) => [source.path, documents[source.path]]));
}

export function confirmRequirement(item: ProgressItem, baseline: ProgressBaseline): Partial<ProgressItem> {
  return {
    source: { ...item.source, sha256: baseline.documents[item.source.path] },
    reviewed_documents: documentReview(item, baseline.documents),
    stale_requirement: false,
    verification_status: "unverified",
  };
}

/** Editing evidence or a condition invalidates only the dependent manual review. */
export function patchRequirement(item: ProgressItem, patch: Partial<ProgressItem>): ProgressItem {
  const conditionChanged = patch.criterion !== undefined && patch.criterion !== item.criterion;
  return {
    ...item,
    ...patch,
    ...(patch.evidence ? { evidence: { ...patch.evidence, sha256: undefined, excerpt: undefined } } : {}),
    ...(conditionChanged ? { implementation_status: "unknown", evidence: null } : {}),
    ...(patch.evidence !== undefined || conditionChanged
      ? { verification_status: "unverified", verification_note: "" }
      : {}),
  };
}

export function manualRequirement(id: string, baseline: ProgressBaseline): ProgressItem | null {
  if (baseline.requirements.length >= MAX_REQUIREMENTS) return null;
  const path = activeDocuments(baseline).find(
    (path) => (baseline.document_kinds?.[path] ?? "current") === "current",
  );
  if (!path) return null;
  return {
    id, title: "새 기능", criterion: "완료 조건을 입력하세요", area: "직접 추가", included: true,
    source: { path, line: 0, excerpt: "사용자가 직접 추가", sha256: baseline.documents[path] },
    implementation_status: "unknown", evidence: null, verification_status: "unverified", verification_note: "",
  };
}
