import type {
  EvidenceCandidate, LinkReport, PolicyPreview, ProgressBaseline,
  ProgressFieldError, ProgressHistory, ProgressItem, ProgressReport,
  ProjectDocument, Review, Scan, ScanImpact, TestLinks,
} from "./bridge";

type Requested = { requested_path?: string };
export type ProgressEvent = Requested & (
  | { type: "progressDocs"; documents: ProjectDocument[]; omitted: number; repository?: string; baseline?: ProgressBaseline | null }
  | ({ type: "progressPreview"; repository?: string; truncated?: boolean } & Pick<ProgressBaseline, "documents" | "document_kinds" | "requirements">)
  | { type: "progressTestsCancelled" }
  | { type: "progressSaved"; baseline: ProgressBaseline }
  | { type: "progressReport"; report: ProgressReport }
  | ({ type: "progressTests" } & TestLinks)
  | ({ type: "progressHistory" } & ProgressHistory)
  | ({ type: "progressLinks" } & LinkReport)
  | { type: "progressExported"; file: string }
  | { type: "progressEvidence"; id: ProgressItem["id"]; candidates: EvidenceCandidate[] }
  | { type: "progressError"; message: string; errors?: ProgressFieldError[] }
);
export type QueuedProgressEvent = ProgressEvent & { _seq: number };
export type DesktopEvent = ProgressEvent | (Requested & (
  | { type: "ready"; repository: string; base: string; installed: Record<string, string> }
  | { type: "repository"; path: string }
  | { type: "scanning" }
  | { type: "scanned"; scan: Scan }
  | { type: "policyMissing"; repository: string }
  | ({ type: "policyPreview" } & PolicyPreview)
  | { type: "policyCreated"; path: string; repository?: string; preset?: string }
  | ({ type: "scanImpact" } & ScanImpact)
  | { type: "preview"; prompt: string }
  | { type: "reviewing" }
  | { type: "reviewed"; review: Review }
  | { type: "error" | "reviewError"; message: string }
  | { type: "saved"; path: string }
));
export function isProgressEvent(event: DesktopEvent): event is ProgressEvent {
  switch (event.type) {
    case "progressDocs": case "progressPreview": case "progressSaved":
    case "progressReport": case "progressTests": case "progressHistory":
    case "progressLinks": case "progressExported": case "progressEvidence":
    case "progressError": case "progressTestsCancelled": return true;
    default: return false;
  }
}
