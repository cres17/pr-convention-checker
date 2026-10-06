import type {
  DocumentKind, EvidenceCandidate, LinkReport, ProgressBaseline, ProgressFieldError,
  ProgressHistory, ProgressItem, ProgressReport, ProjectDocument, RecoveryOption, TestLinks,
} from "../../bridge";
import type { ProgressEvent } from "../../events";
import { mergeProgressPreview } from "./merge";
import { displayStatus, filterProgressItems, inCurrentScope, type ProgressFilter } from "./status";
import { MAX_REQUIREMENTS } from "./limits";
import { manualRequirement, patchRequirement } from "./requirement";
import { rebaseProgress } from "./rebase";
import { activeDocuments, archiveDocument } from "./documents";

import { retainsEditor, type ProgressOperation } from './operations';
export type { ProgressOperation } from './operations';
export type ProgressState = {
  path: string;
  documents: ProjectDocument[];
  selectedDocs: string[];
  documentKinds: Record<string, DocumentKind>;
  draft: ProgressBaseline | null;
  base: ProgressBaseline | null;
  conflict: ProgressBaseline | null;
  report: ProgressReport | null;
  selectedId: string;
  filter: ProgressFilter;
  query: string;
  error: string;
  busy: ProgressOperation;
  candidates: EvidenceCandidate[];
  omitted: number;
  showDocuments: boolean;
  fieldErrors: ProgressFieldError[];
  focusField: string;
  links: LinkReport | null;
  history: ProgressHistory | null;
  tests: TestLinks | null;
  exported: string;
  dirty: boolean;
  inspections: number;
  inspectionId: string;
  recovery: ProgressBaseline | null;
  recoveryWarning: string;
  recoveryKey: string;
  recoveryRevision: string;
  recoveryOptions: RecoveryOption[];
  draftExported: string;
  saveWarning: string;
  draftStatus: "" | "saving" | "cached" | "error";
  draftError: string;
};
export function initialProgressState(path = "", busy: ProgressOperation = ""): ProgressState {
  return {
    path, documents: [], selectedDocs: [], documentKinds: {}, draft: null, base: null, conflict: null, report: null,
    selectedId: "", filter: "all", query: "", error: "", busy, candidates: [], omitted: 0,
    showDocuments: true, fieldErrors: [], focusField: "", links: null, history: null,
    tests: null, exported: "", dirty: false, inspections: 0, inspectionId: "",
    recovery: null, recoveryWarning: "", saveWarning: "", draftStatus: "", draftError: "",
    recoveryKey: '', recoveryRevision: '', recoveryOptions: [], draftExported: '',
  };
}
export type ProgressAction =
  | { type: "reset"; path: string; connected: boolean }
  | { type: "restore"; path: string; retained?: ProgressState; connected: boolean }
  | { type: "event"; event: ProgressEvent }
  | { type: "end"; operation: ProgressOperation }
  | { type: "begin"; operation: Exclude<ProgressOperation, ""> }
  | { type: "edit"; id: string; patch: Partial<ProgressItem> }
  | { type: "kind"; path: string; kind: DocumentKind }
  | { type: "archive-document"; path: string }
  | { type: "document"; path: string; selected: boolean }
  | { type: "filter"; value: ProgressFilter }
  | { type: "query"; value: string }
  | { type: "select"; id: string }
  | { type: "focus-item"; id: string }
  | { type: "first-error" }
  | { type: "start-evidence" }
  | { type: "clear-focus" }
  | { type: "toggle-documents" }
  | { type: "forget-tests" }
  | { type: "remove-item"; id: string }
  | { type: "add-manual"; id: string };
// Recovery copies never change the confirmed baseline until the user saves.
export type DraftAction = { type: "recover-draft" } | { type: "keep-copies" } | { type: "cache-draft" } | { type: "rebase"; choice: 'local' | 'latest' };

function finish(state: ProgressState, operation: ProgressOperation): ProgressOperation {
  return state.busy === operation ? "" : state.busy;
}
function receive(state: ProgressState, event: ProgressEvent): ProgressState {
  if (event.requested_path && event.requested_path !== state.path) return state;
  if (["progressReport", "progressHistory", "progressTests", "progressLinks"].includes(event.type) && event.baseline_version !== undefined) {
    const mismatch = state.dirty || state.draft?.version !== event.baseline_version ||
      (!!state.draft?.baseline_id && state.draft.baseline_id !== event.baseline_id) ||
      (event.type === "progressHistory" && !!state.inspectionId && event.inspection_id !== state.inspectionId);
    if (mismatch) return { ...state, busy: event.type === "progressTests" ? finish(state, "tests") :
      event.type === "progressLinks" ? finish(state, "links") : state.busy };
  }
  switch (event.type) {
    case "progressDocs": {
      const sameBaseline = event.baseline?.version === state.draft?.version &&
        event.baseline?.baseline_id === state.draft?.baseline_id;
      const next = { ...state, documents: event.documents, omitted: event.omitted,
        ...(sameBaseline ? {} : { report: null, tests: null, links: null, history: null, inspectionId: "" }),
        busy: state.busy === "draft-import" ? "" : finish(state, "documents") };
      if (state.dirty) return { ...next, conflict: state.conflict ? event.baseline ?? null : null };
      next.recovery = event.recovery ?? null;
      next.recoveryWarning = event.recovery_warning ?? "";
      next.recoveryKey = event.recovery_key ?? '';
      next.recoveryRevision = event.recovery_revision ?? '';
      next.recoveryOptions = event.recovery_options ?? [];
      if (!event.baseline) {
        const suggested = event.documents.find((doc) => doc.path.toLowerCase() === "readme.md");
        return { ...next, selectedDocs: suggested ? [suggested.path] : [] };
      }
      return {
        ...next, draft: event.baseline, base: event.baseline, selectedDocs: activeDocuments(event.baseline),
        documentKinds: event.baseline.document_kinds ?? {},
        selectedId: event.baseline.requirements[0]?.id ?? "", showDocuments: false,
        inspections: state.inspections + 1,
      };
    }
    case "progressPreview": {
      try {
        const draft = mergeProgressPreview(state.draft, {
          repository: state.path, documents: event.documents,
          document_kinds: event.document_kinds, requirements: event.requirements,
        });
        return {
          ...state, draft, selectedDocs: activeDocuments(draft), documentKinds: draft.document_kinds ?? {},
          dirty: true, busy: finish(state, "extract"), fieldErrors: [], links: null, tests: null,
          exported: "", filter: "all", query: "", report: null, candidates: [],
          selectedId: draft.requirements.some((item) => item.id === state.selectedId)
            ? state.selectedId : draft.requirements[0]?.id ?? "",
        };
      } catch (error) {
        return { ...state, busy: finish(state, "extract"), error: error instanceof Error ? error.message : String(error) };
      }
    }
    case "progressLatestUsed":
    case "progressSaved":
      return {
        ...state, dirty: false, draftStatus: "", draftError: "", recovery: null, recoveryWarning: "", saveWarning: event.warning ?? "",
        report: null, tests: null, links: null, history: null, inspectionId: "",
        busy: "", draftExported: "", recoveryKey: "", recoveryRevision: "", recoveryOptions: [], fieldErrors: [], draft: event.baseline, base: event.baseline, conflict: null,
        selectedDocs: activeDocuments(event.baseline), documentKinds: event.baseline.document_kinds ?? {},
        showDocuments: false, inspections: state.inspections + (event.type === "progressLatestUsed" ? 1 : 0),
      };
    case "progressReport":
      return state.dirty || (state.draft?.version !== undefined && state.draft.version !== event.report.version)
        ? state : { ...state, report: event.report, inspectionId: event.inspection_id ?? "" };
    case "progressTests":
      return { ...state, busy: finish(state, "tests"), tests: state.dirty ? state.tests : event };
    case "progressTestsCancelled":
      return { ...state, busy: finish(state, "tests") };
    case "progressHistory":
      return { ...state, history: { snapshots: event.snapshots, since_save: event.since_save, warning: event.warning } };
    case "progressLinks":
      return { ...state, busy: finish(state, "links"), links: state.dirty ? state.links : event };
    case "progressDraftExported": return { ...state, busy: finish(state, "draft-export"), draftExported: event.file };
    case "progressDraftImportCancelled": return { ...state, busy: finish(state, "draft-import") };
    case "progressDraftExportCancelled": return { ...state, busy: finish(state, "draft-export") };
    case "progressExported":
      return { ...state, exported: `저장했습니다 · ${event.file}` };
    case "progressEvidence":
      return event.id === state.selectedId ? { ...state, candidates: event.candidates } : state;
    case "progressError":
      return { ...state, busy: "", fieldErrors: event.errors ?? [], error: event.current_baseline || event.errors?.length ? "" : event.message,
        conflict: event.current_baseline ?? state.conflict };
    case "progressDraftCached": return state.dirty ? { ...state, draftStatus: "cached", draftError: "" } : state;
    case "progressDraftError": return state.dirty ? { ...state, draftStatus: "error", draftError: event.message } : state;
    case "progressDraftDiscarded": return { ...state, recovery: null, recoveryWarning: "", busy: finish(state, "discard") };
  }
}
function transition(state: ProgressState, action: ProgressAction | DraftAction): ProgressState {
  if (["draft-export", "latest", "draft-import"].includes(state.busy) && ["edit", "kind", "archive-document", "document", "add-manual", "remove-item", "rebase"].includes(action.type)) return state;
  if (!state.dirty && (state.recovery || state.recoveryWarning)
      && ["edit", "kind", "archive-document", "document", "add-manual", "remove-item"].includes(action.type)) return state;
  switch (action.type) {
    case "rebase": {
      if (!state.draft || !state.conflict || state.busy) return state;
      const merged = rebaseProgress(state.base, state.draft, state.conflict, action.choice);
      if (merged.overflow) return { ...state, error: '합친 결과가 문서 10개·기능 120개 상한을 넘습니다. 기존 편집은 유지했습니다.' };
      return { ...state, draft: merged.draft, base: state.conflict, conflict: null, dirty: true,
        selectedDocs: activeDocuments(merged.draft), documentKinds: merged.draft.document_kinds ?? {},
        report: null, tests: null, links: null, candidates: [], error: '', fieldErrors: [],
        recoveryWarning: '', saveWarning: '최신 기준과 편집을 합쳤습니다. 내용을 검토한 뒤 기준과 근거 저장을 눌러 주세요.' };
    }
    case "cache-draft": return { ...state, draftStatus: "saving", draftError: "" };
    case "keep-copies": return state.busy || state.dirty ? state : { ...state, recovery: null, recoveryWarning: '',
      recoveryKey: '', recoveryRevision: '', recoveryOptions: [] };
    case "recover-draft": {
      if (!state.recovery || state.busy || state.dirty || state.recoveryOptions.find((copy) => copy.key === state.recoveryKey)?.active) return state;
      const draft = { ...state.recovery, recovery_key: state.recoveryKey, recovery_revision: state.recoveryRevision };
      const base = draft.edit_base ?? ((draft.version ?? 0) === (state.base?.version ?? 0) ? state.base : null);
      return { ...state, draft, base, recovery: null, recoveryWarning: '', saveWarning: '초안을 복구했습니다. 내용을 검토한 뒤 기준과 근거 저장을 눌러 주세요.', dirty: true, report: null, links: null, tests: null, fieldErrors: [],
        selectedDocs: activeDocuments(draft), documentKinds: draft.document_kinds ?? {},
        selectedId: draft.requirements[0]?.id ?? "", filter: "all", query: "", showDocuments: false };
    }
    case "reset": return initialProgressState(action.path, action.connected && action.path ? "documents" : "");
    case "restore":
      return action.retained
        ? { ...action.retained, path: action.path,
            busy: retainsEditor(action.retained.busy) ? action.retained.busy : action.connected ? "documents" : "",
            candidates: [], inspections: 0 }
        : initialProgressState(action.path, action.connected && action.path ? "documents" : "");
    case "event": return receive(state, action.event);
    case "end": return { ...state, busy: finish(state, action.operation) };
    case "begin":
      if (state.busy) return state;
      return {
        ...state, busy: action.operation, error: "", saveWarning: "",
        ...(action.operation === "save" ? { fieldErrors: [], links: null, exported: "" } : {}),
      };
    case "edit": {
      if (!state.draft || state.busy === "save") return state;
      const keys = Object.keys(action.patch);
      return {
        ...state, dirty: true, report: null, links: null, exported: "",
        tests: keys.some((key) => ["test_patterns", "evidence", "criterion"].includes(key)) ? null : state.tests,
        fieldErrors: state.fieldErrors.filter((error) => error.id !== action.id ||
          !keys.some((key) => error.field === key || error.field.startsWith(`${key}.`))),
        draft: { ...state.draft, requirements: state.draft.requirements.map((item) =>
          item.id === action.id ? patchRequirement(item, action.patch) : item) },
      };
    }
    case "kind": {
      if (state.busy === "save" || state.busy === "extract") return state;
      const documentKinds = { ...state.documentKinds, [action.path]: action.kind };
      if (state.draft?.archived_documents?.includes(action.path)) return { ...state, documentKinds };
      if (!state.draft || !(action.path in state.draft.documents)) return { ...state, documentKinds };
      return {
        ...state, documentKinds, dirty: true, report: null, links: null, exported: "",
        draft: { ...state.draft, document_kinds: { ...state.draft.document_kinds, [action.path]: action.kind } },
      };
    }
    case "archive-document": {
      if (!state.draft || state.busy || !(action.path in state.draft.documents) ||
          (state.draft.archived_documents?.length ?? 0) >= 120) return state;
      const draft = archiveDocument(state.draft, action.path);
      return { ...state, draft, documentKinds: draft.document_kinds ?? {}, selectedDocs: activeDocuments(draft),
        dirty: true, report: null, history: null, links: null, tests: null, exported: "" };
    }
    case "document":
      if (state.busy === "save" || state.busy === "extract") return state;
      return { ...state, selectedDocs: action.selected
        ? [...new Set([...state.selectedDocs, action.path])] : state.selectedDocs.filter((path) => path !== action.path) };
    case "filter": return { ...state, filter: action.value, query: "", candidates: [] };
    case "query": return { ...state, query: action.value };
    case "select": return { ...state, selectedId: action.id, candidates: [] };
    case "focus-item": {
      const item = state.draft?.requirements.find((item) => item.id === action.id);
      if (!item || !state.draft) return state;
      return { ...state, selectedId: item.id, filter: inCurrentScope(item, state.draft) ? "all" : "excluded", query: "", candidates: [] };
    }
    case "first-error": {
      const item = state.draft?.requirements.find((item) => state.fieldErrors.some((error) => error.id === item.id));
      if (!item || !state.draft) return state;
      return { ...state, selectedId: item.id, filter: inCurrentScope(item, state.draft) ? "all" : "excluded",
        query: "", candidates: [], focusField: state.fieldErrors.find((error) => error.id === item.id)?.field ?? "" };
    }
    case "start-evidence": {
      const draft = state.draft;
      const item = draft?.requirements.find((item) =>
        inCurrentScope(item, draft) && displayStatus(item, state.report) === "unknown");
      return { ...state, selectedId: item?.id ?? "", candidates: [], focusField: item ? "evidence.path" : "" };
    }
    case "clear-focus": return { ...state, focusField: "" };
    case "toggle-documents": return { ...state, showDocuments: !state.showDocuments };
    case "forget-tests": return { ...state, tests: null };
    case "remove-item": {
      if (!state.draft || state.busy || !state.draft.requirements.some((item) => item.id === action.id)) return state;
      return { ...state, dirty: true, draft: { ...state.draft,
        requirements: state.draft.requirements.filter((item) => item.id !== action.id) },
        report: null, tests: null, links: null, candidates: [], exported: "", fieldErrors: [] };
    }
    case "add-manual": {
      if (!state.draft || state.busy) return state;
      const item = manualRequirement(action.id, state.draft);
      if (!item) return { ...state, error: `기능은 최대 ${MAX_REQUIREMENTS}개까지 확정할 수 있습니다. 필요한 항목을 정리해 주세요.` };
      return { ...state, dirty: true, draft: { ...state.draft, requirements: [...state.draft.requirements, item] },
        report: null, links: null, exported: "", selectedId: item.id, filter: "all", query: "", candidates: [] };
    }
  }
}
/** React may batch replies: each event must observe the preceding transition. */
export function progressReducer(state: ProgressState, action: ProgressAction | DraftAction): ProgressState {
  let next = transition(state, action);
  if (next === state) return state;
  if (next.dirty && next.draft !== state.draft) next = { ...next, draftStatus: "saving", draftError: "", draftExported: "" };
  const visible = filterProgressItems(next.draft, next.report, next.filter, next.query);
  if (visible.some((item) => item.id === next.selectedId)) return next;
  return { ...next, selectedId: visible[0]?.id ?? "", candidates: [] };
}
export function selectProgressView(state: ProgressState) {
  const draft = state.draft;
  return {
    merge: state.draft && state.conflict ? rebaseProgress(state.base, state.draft, state.conflict) : null,
    recoveryPending: !state.dirty && !!(state.recovery || state.recoveryWarning),
    item: state.draft?.requirements.find((item) => item.id === state.selectedId),
    visible: filterProgressItems(state.draft, state.report, state.filter, state.query),
    currentItems: draft?.requirements.filter((item) => inCurrentScope(item, draft)) ?? [],
    invalidItems: state.draft?.requirements.filter((item) => state.fieldErrors.some((error) => error.id === item.id)) ?? [],
    canAddManual: !!state.draft && state.draft.requirements.length < MAX_REQUIREMENTS && activeDocuments(state.draft).some(
      (path) => (state.draft?.document_kinds?.[path] ?? "current") === "current"),
  };
}
