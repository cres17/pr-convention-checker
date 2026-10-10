import { MAX_REQUIREMENTS } from "./limits";
import type { ProgressBaseline, ProgressItem } from '../../bridge';
import { activeDocuments } from './documents';

type Choice = 'local' | 'latest';
type Value = unknown;
const object = (value: Value): value is Record<string, Value> =>
  !!value && typeof value === 'object' && !Array.isArray(value);
function equal(a: Value, b: Value): boolean {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => equal(v, b[i]));
  if (object(a) && object(b)) return Object.keys(a).length === Object.keys(b).length &&
    Object.keys(a).every((key) => Object.hasOwn(b, key) && equal(a[key], b[key]));
  return false;
}
const fieldLabels: Record<string, string> = { title: '기능명', criterion: '완료 조건', area: '영역', included: '범위 포함',
  implementation_status: '구현 상태', implementation_note: '구현 기록', verification_status: '검증 상태',
  verification_note: '검증 기록', evidence: '코드 근거', source: '문서 출처', path: '경로', line: '줄 번호',
  sha256: '내용 변경', excerpt: '원문', note: '확인 기록', reviewed_documents: '검토한 문서', test_patterns: '테스트 연결',
  duplicates: '추가 출처', doc_marked_done: '문서 완료 표시', source_key: '문서 항목 식별자' };

/** Preserve both editors' independent edits. Only overlapping edits need a choice. */
export function rebaseProgress(base: ProgressBaseline | null, local: ProgressBaseline,
  latest: ProgressBaseline, choice: Choice = 'latest') {
  const conflicts: string[] = [];
  function merge(before: Value, mine: Value, theirs: Value, label: string, atomic = false): Value {
    if (equal(mine, before) || equal(mine, theirs)) return theirs;
    if (equal(theirs, before)) return mine;
    if (!atomic && object(mine) && object(theirs) && (before === undefined || object(before))) {
      const result: Record<string, Value> = Object.create(null);
      for (const key of new Set([...Object.keys(before ?? {}), ...Object.keys(mine), ...Object.keys(theirs)])) {
        const value = merge(before?.[key], mine[key], theirs[key], `${label} · ${fieldLabels[key] ?? key}`);
        if (value !== undefined) result[key] = value;
      }
      return result;
    }
    conflicts.push(label);
    return choice === 'local' ? mine : theirs;
  }
  const byId = (items: ProgressItem[]) => new Map(items.map((item) => [item.id, item]));
  const oldItems = byId(base?.requirements ?? []), mine = byId(local.requirements), theirs = byId(latest.requirements);
  // Never combine a new condition/evidence with a verification of the old one.
  const assessment = new Set(['criterion', 'implementation_status', 'implementation_note', 'evidence',
    'verification_status', 'verification_note', 'reviewed_documents', 'stale_requirement', 'stale_evidence']);
  const provenance = new Set(['source', 'source_key', 'duplicates', 'doc_marked_done']);
  const pick = (item: ProgressItem | undefined, fields: Set<string>, inside: boolean) => item &&
    Object.fromEntries(Object.entries(item).filter(([key]) => fields.has(key) === inside));
  const requirements: ProgressItem[] = [];
  for (const id of new Set([...theirs.keys(), ...mine.keys(), ...oldItems.keys()])) {
    const before = oldItems.get(id), ours = mine.get(id), other = theirs.get(id);
    const label = ours?.title ?? other?.title ?? id;
    let item: Value;
    if (!ours || !other) item = merge(before, ours, other, label, true);
    else {
      const coupled = new Set([...assessment, ...provenance]);
      item = {
        ...merge(pick(before, coupled, false), pick(ours, coupled, false), pick(other, coupled, false), label) as object,
        ...merge(pick(before, assessment, true), pick(ours, assessment, true), pick(other, assessment, true), `${label} · 완료 조건·근거·검증`, true) as object,
        ...merge(pick(before, provenance, true), pick(ours, provenance, true), pick(other, provenance, true), `${label} · 문서 출처`, true) as object,
      };
      const result = item as ProgressItem;
      if (!result.reviewed_documents && result.implementation_status !== 'unknown') {
        const donor = equal(pick(result, assessment, true), pick(ours, assessment, true)) ? ours : other;
        const documents = donor === ours ? local.documents : latest.documents;
        result.reviewed_documents = { ...Object.fromEntries((donor.duplicates ?? []).map((source) => [source.path, documents[source.path]])),
          [donor.source.path]: donor.source.sha256 };
      }
    }
    if (item) requirements.push(item as ProgressItem);
  }
  const draft: ProgressBaseline = {
    ...latest, repository: local.repository, requirements,
    recovery_key: local.recovery_key, recovery_revision: local.recovery_revision,
    documents: merge(base?.documents ?? {}, local.documents, latest.documents, '기준 문서') as ProgressBaseline['documents'],
    document_kinds: merge(base?.document_kinds ?? {}, local.document_kinds ?? {}, latest.document_kinds ?? {}, '문서 종류') as ProgressBaseline['document_kinds'],
    archived_documents: merge(base?.archived_documents ?? [], local.archived_documents ?? [], latest.archived_documents ?? [], '보관 문서', true) as string[],
  };
  // Extra documents/items require explicit cleanup, never silently truncate edits.
  for (const path of draft.archived_documents ?? []) {
    draft.document_kinds = { ...draft.document_kinds, [path]: 'reference' };
  }
  const overflow = activeDocuments(draft).length > 10 || (draft.archived_documents?.length ?? 0) > 120 || requirements.length > MAX_REQUIREMENTS;
  return { draft, conflicts, overflow };
}
