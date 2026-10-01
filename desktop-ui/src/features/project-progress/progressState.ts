import type {
  DocumentKind, EvidenceCandidate, LinkReport, ProgressBaseline, ProgressFieldError,
  ProgressHistory, ProgressItem, ProgressReport, ProjectDocument, TestLinks,
} from "../../bridge";
import type { ProgressEvent } from "../../events";
import { mergeProgressPreview } from "./merge";
import { displayStatus, filterProgressItems, inCurrentScope, type ProgressFilter } from "./status";
import { manualRequirement, patchRequirement } from "./requirement";

export type ProgressOperation = "" | "documents" | "extract" | "save" | "links" | "tests";
export type ProgressState = {
  path: string;
  documents: ProjectDocument[];
  selectedDocs: string[];
  documentKinds: Record<string, DocumentKind>;
  draft: ProgressBaseline | null;
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
};
export function initialProgressState(path = "", busy: ProgressOperation = ""): ProgressState {
  return {
    path, documents: [], selectedDocs: [], documentKinds: {}, draft: null, report: null,
    selectedId: "", filter: "all", query: "", error: "", busy, candidates: [], omitted: 0,
    showDocuments: true, fieldErrors: [], focusField: "", links: null, history: null,
    tests: null, exported: "", dirty: false, inspections: 0,
  };
}
export type ProgressAction =
  | { type: "reset"; path: string; connected: boolean }
  | { type: "event"; event: ProgressEvent }
  | { type: "begin"; operation: Exclude<ProgressOperation, ""> }
  | { type: "edit"; id: string; patch: Partial<ProgressItem> }
  | { type: "kind"; path: string; kind: DocumentKind }
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
  | { type: "add-manual"; id: string };

function finish(state: ProgressState, operation: ProgressOperation): ProgressOperation {
  return state.busy === operation ? "" : state.busy;
}
function receive(state: ProgressState, event: ProgressEvent): ProgressState {
  if (event.requested_path && event.requested_path !== state.path) return state;
  switch (event.type) {
    case "progressDocs": {
      const next = { ...state, documents: event.documents, omitted: event.omitted, busy: finish(state, "documents") };
      if (state.dirty) return next;
      if (!event.baseline) {
        const suggested = event.documents.find((doc) => doc.path.toLowerCase() === "readme.md");
        return { ...next, selectedDocs: suggested ? [suggested.path] : [] };
      }
      return {
        ...next, draft: event.baseline, selectedDocs: Object.keys(event.baseline.documents),
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
          ...state, draft, selectedDocs: Object.keys(draft.documents), documentKinds: draft.document_kinds ?? {},
          dirty: true, busy: finish(state, "extract"), fieldErrors: [], links: null, tests: null,
          exported: "", filter: "all", query: "", report: null, candidates: [],
          selectedId: draft.requirements.some((item) => item.id === state.selectedId)
            ? state.selectedId : draft.requirements[0]?.id ?? "",
        };
      } catch (error) {
        return { ...state, busy: finish(state, "extract"), error: error instanceof Error ? error.message : String(error) };
      }
    }
    case "progressSaved":
      return {
        ...state, dirty: false, busy: state.busy === "documents" ? "" : finish(state, "save"), fieldErrors: [], draft: event.baseline,
        selectedDocs: Object.keys(event.baseline.documents), documentKinds: event.baseline.document_kinds ?? {},
        showDocuments: false,
      };
    case "progressReport":
      return state.dirty ? state : { ...state, report: event.report };
    case "progressTests":
      return { ...state, busy: finish(state, "tests"), tests: state.dirty ? state.tests : event };
    case "progressTestsCancelled":
      return { ...state, busy: finish(state, "tests") };
    case "progressHistory":
      return { ...state, history: { snapshots: event.snapshots, since_save: event.since_save } };
    case "progressLinks":
      return { ...state, busy: finish(state, "links"), links: state.dirty ? state.links : event };
    case "progressExported":
      return { ...state, exported: `저장했습니다 · ${event.file}` };
    case "progressEvidence":
      return event.id === state.selectedId ? { ...state, candidates: event.candidates } : state;
    case "progressError":
      return { ...state, busy: "", fieldErrors: event.errors ?? [], error: event.errors?.length ? "" : event.message };
  }
}
function transition(state: ProgressState, action: ProgressAction): ProgressState {
  switch (action.type) {
    case "reset": return initialProgressState(action.path, action.connected && action.path ? "documents" : "");
    case "event": return receive(state, action.event);
    case "begin":
      if (state.busy) return state;
      return {
        ...state, busy: action.operation, error: "",
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
      if (!state.draft || !(action.path in state.draft.documents)) return { ...state, documentKinds };
      return {
        ...state, documentKinds, dirty: true, report: null, links: null, exported: "",
        draft: { ...state.draft, document_kinds: { ...state.draft.document_kinds, [action.path]: action.kind } },
      };
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
    case "add-manual": {
      if (!state.draft || state.busy) return state;
      const item = manualRequirement(action.id, state.draft);
      if (!item) return state;
      return { ...state, dirty: true, draft: { ...state.draft, requirements: [...state.draft.requirements, item] },
        report: null, links: null, exported: "", selectedId: item.id, filter: "all", query: "", candidates: [] };
    }
  }
}
/** React may batch replies: each event must observe the preceding transition. */
export function progressReducer(state: ProgressState, action: ProgressAction): ProgressState {
  const next = transition(state, action);
  if (next === state) return state;
  const visible = filterProgressItems(next.draft, next.report, next.filter, next.query);
  if (visible.some((item) => item.id === next.selectedId)) return next;
  return { ...next, selectedId: visible[0]?.id ?? "", candidates: [] };
}
export function selectProgressView(state: ProgressState) {
  const draft = state.draft;
  return {
    item: state.draft?.requirements.find((item) => item.id === state.selectedId),
    visible: filterProgressItems(state.draft, state.report, state.filter, state.query),
    currentItems: draft?.requirements.filter((item) => inCurrentScope(item, draft)) ?? [],
    invalidItems: state.draft?.requirements.filter((item) => state.fieldErrors.some((error) => error.id === item.id)) ?? [],
    canAddManual: !!state.draft && Object.keys(state.draft.documents).some(
      (path) => (state.draft?.document_kinds?.[path] ?? "current") === "current"),
  };
}
