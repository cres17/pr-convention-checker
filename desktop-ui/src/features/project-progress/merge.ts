import type { DocumentKind, ProgressBaseline, ProgressItem } from "../../bridge";
import { documentReview } from "./requirement";

/** Refresh extracted locations, retain context provenance, and reject overflow atomically. */
function mergeDuplicates(item: ProgressItem, candidate: ProgressItem, kinds: Record<string, DocumentKind>) {
  const locations = [
    ...(candidate.duplicates ?? []),
    ...(item.duplicates ?? []).filter((source) => kinds[source.path] !== "current"),
  ];
  const unique = [...new Map(locations.map((source) => [`${source.path}:${source.line}`, source])).values()];
  if (unique.length > 20)
    throw new Error("기존 문서 출처를 보존한 결과가 상한(중복 출처 20개)을 넘습니다. 기존 항목은 유지했습니다.");
  return unique;
}

/** Extraction adds candidates; it never discards the user's working baseline. */
export function mergeProgressPreview(
  previous: ProgressBaseline | null,
  preview: ProgressBaseline,
): ProgressBaseline {
  if (!previous) return preview;
  const documents = { ...previous.documents, ...preview.documents };
  const document_kinds = { ...preview.document_kinds };
  for (const path of Object.keys(previous.documents)) {
    document_kinds[path] ??= path in preview.documents ? "current" : "reference";
  }
  const candidates = new Map(preview.requirements.map((item) => [item.id, item]));
  const requirements = previous.requirements.map((item): ProgressItem => {
    const candidate = candidates.get(item.id);
    candidates.delete(item.id);
    const reviewed_documents =
      item.reviewed_documents ??
      documentReview(item, previous.documents);
    const changed = Object.entries(reviewed_documents).some(
      ([path, hash]) => documents[path] !== hash,
    );
    return {
      ...item,
      ...(candidate
        ? {
            source: candidate.source,
            ...(candidate.doc_marked_done !== undefined
              ? { doc_marked_done: candidate.doc_marked_done }
              : {}),
            ...(candidate.duplicates || item.duplicates
              ? { duplicates: mergeDuplicates(item, candidate, document_kinds) }
              : {}),
          }
        : {}),
      // Keep the earlier review boundary even across repeated extractions.
      ...(changed || item.reviewed_documents ? { reviewed_documents } : {}),
      ...(changed || item.stale_requirement !== undefined
        ? { stale_requirement: changed }
        : {}),
    };
  });
  requirements.push(...candidates.values());
  if (Object.keys(documents).length > 10 || requirements.length > 120)
    throw new Error(
      "기존 근거를 보존한 목록이 상한(문서 10개·기능 120개)을 넘습니다. 기존 항목은 유지했습니다.",
    );
  return { ...previous, ...preview, documents, document_kinds, requirements };
}
