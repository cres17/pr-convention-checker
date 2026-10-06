import type { ProgressBaseline } from "../../bridge";

/** Archived paths keep their original hash and goals, but consume no active binding. */
export function activeDocuments(baseline: ProgressBaseline): string[] {
  return Object.keys(baseline.documents).filter((path) => !baseline.archived_documents?.includes(path));
}

export function archiveDocument(baseline: ProgressBaseline, path: string): ProgressBaseline {
  return {
    ...baseline,
    archived_documents: [...new Set([...(baseline.archived_documents ?? []), path])].sort(),
    document_kinds: { ...baseline.document_kinds, [path]: "reference" },
  };
}
