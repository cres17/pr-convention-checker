import { MAX_REQUIREMENTS } from "./limits";
import type { DocumentKind, ProgressBaseline, ProgressItem } from "../../bridge";
import { documentReview } from "./requirement";
import { activeDocuments } from "./documents";

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

function sameExtractedGoal(previous: ProgressItem, candidate: ProgressItem) {
  if (!previous.source.line || !candidate.source.line) return false;
  if (previous.source_key) return previous.source_key === candidate.source_key;
  const content = (item: ProgressItem) => item.source.excerpt
    .replace(/<!--\s*progress-id:\s*[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\s*-->/g, "")
    .replace(/^\s*[-*+]\s+\[[ xX]\]\s*/, "").trim();
  return previous.source.path === candidate.source.path && content(previous) === content(candidate);
}

/** Extraction adds candidates; it never discards the user's working baseline. */
export function mergeProgressPreview(
  previous: ProgressBaseline | null,
  preview: ProgressBaseline,
): ProgressBaseline {
  if (!previous) return preview;
  const documents = { ...previous.documents, ...preview.documents };
  const archived_documents = (previous.archived_documents ?? []).filter((path) => !(path in preview.documents));
  const document_kinds = { ...preview.document_kinds };
  for (const path of Object.keys(previous.documents)) {
    document_kinds[path] ??= path in preview.documents ? "current" : "reference";
  }
  for (const path of archived_documents) document_kinds[path] = "reference";
  const candidates = new Map(preview.requirements.map((item) => [item.id, item]));
  const previousIds = new Set(previous.requirements.map((item) => item.id));
  const unmatched = previous.requirements.filter((item) => !candidates.has(item.id));
  const requirements = previous.requirements.map((item): ProgressItem => {
    let candidate = candidates.get(item.id);
    if (!candidate) {
      const matches = [...candidates.values()].filter((entry) => !previousIds.has(entry.id) && sameExtractedGoal(item, entry));
      if (matches.length === 1 && unmatched.filter((old) => sameExtractedGoal(old, matches[0])).length === 1)
        candidate = matches[0];
    }
    if (candidate) candidates.delete(candidate.id);
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
            ...(candidate.source_key ? { source_key: candidate.source_key } : {}),
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
  const merged = { ...previous, ...preview, documents, document_kinds, archived_documents, requirements };
  if (activeDocuments(merged).length > 10 || archived_documents.length > 120 || requirements.length > MAX_REQUIREMENTS)
    throw new Error(
      "기존 근거를 보존한 목록이 상한(문서 10개·기능 120개)을 넘습니다. 기존 항목은 유지했습니다.",
    );
  return merged;
}
