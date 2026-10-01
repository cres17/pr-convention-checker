import { useEffect, useMemo, useReducer, useRef } from "react";
import type { Bridge, DocumentKind, ProgressItem } from "../../bridge";
import type { QueuedProgressEvent } from "../../events";
import { isProgressFilter } from "./status";
import { confirmRequirement } from "./requirement";
import { initialProgressState, progressReducer, selectProgressView, type ProgressOperation, type ProgressState } from "./progressState";
import { ProgressRequests, type ProgressRequest } from "./requestSession";

export type ProjectProgressProps = {
  path: string;
  connected: boolean;
  bridge: Bridge | null;
  events: QueuedProgressEvent[];
  focus?: { id: string; n: number } | null;
  active?: boolean;
  onPendingChange?: (pending: boolean) => void;
};
/** Own editor sessions and Qt requests. Leaving a page or repository never discards a draft. */
export default function useProjectProgress({ path, connected, bridge, events, focus = null, active = true, onPendingChange }: ProjectProgressProps) {
  const [state, dispatch] = useReducer(progressReducer, path, initialProgressState);
  const view = useMemo(() => selectProgressView(state), [state]);
  const sessions = useRef(new Map<string, ProgressState>());
  const latestState = useRef(state);
  latestState.current = state;
  const requests = useRef(new ProgressRequests());
  const operation = useRef<ProgressOperation>("");
  const operationToken = useRef("");
  const handledSeq = useRef(events.at(-1)?._seq ?? 0);
  const handledFocus = useRef(0);
  const handledInspection = useRef(0);

  useEffect(() => {
    const previous = latestState.current;
    if (previous.path) {
      if (previous.dirty) sessions.current.set(previous.path, previous);
      else sessions.current.delete(previous.path);
    }
    requests.current.reset();
    operation.current = "";
    operationToken.current = "";
    handledInspection.current = 0;
    const retained = sessions.current.get(path);
    dispatch({ type: "restore", path, retained, connected: connected && !!bridge });
    if (connected && path && bridge) bridge.listProjectDocs(path, requests.current.start("documents"));
  }, [path, connected, bridge]);
  useEffect(() => {
    for (const event of events) {
      if (event._seq <= handledSeq.current) continue;
      handledSeq.current = event._seq;
      if (!requests.current.accepts(event)) {
        if (event.request_done && event.request_id === operationToken.current)
          dispatch({ type: "end", operation: operation.current });
        continue;
      }
      dispatch({ type: "event", event });
      requests.current.complete(event);
    }
  }, [events]);
  useEffect(() => { operation.current = state.busy; }, [state.busy]);
  useEffect(() => {
    if (!connected || !bridge?.cacheProgressDraft || !state.path || !state.draft || !state.dirty) return;
    const token = requests.current.start("draft");
    dispatch({ type: "cache-draft" });
    bridge.cacheProgressDraft(state.path, JSON.stringify(state.draft), token);
  }, [state.draft, state.dirty, state.path, connected, bridge]);
  useEffect(() => {
    if (state.path) sessions.current.set(state.path, state);
    for (const [repository, cached] of sessions.current)
      if (repository !== state.path && !cached.dirty) sessions.current.delete(repository);
    const pending = [...sessions.current.values()].some((session) => session.dirty);
    bridge?.setProgressDirty?.(pending);
    onPendingChange?.(pending);
    if (!pending) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [state, bridge, onPendingChange]);
  useEffect(() => {
    if (handledInspection.current === state.inspections) return;
    handledInspection.current = state.inspections;
    if (connected && state.path === path && state.inspections && !state.dirty)
      bridge?.inspectProgress(path, requests.current.start("inspect"));
  }, [state.inspections, state.path, state.dirty, connected, bridge, path]);
  useEffect(() => {
    if (!active || !focus?.id || focus.n === handledFocus.current || !state.draft?.requirements.some((item) => item.id === focus.id)) return;
    handledFocus.current = focus.n;
    dispatch({ type: "focus-item", id: focus.id });
  }, [focus, state.draft, active]);
  useEffect(() => {
    if (!active || !state.focusField) return;
    document.querySelector<HTMLElement>(`[data-field="${state.focusField}"]`)?.focus();
    dispatch({ type: "clear-focus" });
  }, [state.focusField, state.selectedId, active]);

  const begin = (purpose: Exclude<ProgressOperation, "">, run: (bridge: Bridge, requestId: string) => void) => {
    if (!connected || !path || !bridge || state.path !== path || state.busy || operation.current) return;
    if (view.recoveryPending && purpose !== "discard") return;
    operation.current = purpose;
    if (purpose === "save" || purpose === "extract") requests.current.invalidateReads();
    dispatch({ type: "begin", operation: purpose });
    operationToken.current = requests.current.start(purpose);
    run(bridge, operationToken.current);
  };
  const request = (purpose: ProgressRequest, run: (bridge: Bridge, id: string) => void) => {
    if (connected && path && bridge && state.path === path) run(bridge, requests.current.start(purpose));
  };
  const edit = (id: string, patch: Partial<ProgressItem>) => {
    if (state.busy === "save") return;
    requests.current.invalidateReads();
    dispatch({ type: "edit", id, patch });
  };
  const actions = {
    recoverDraft: () => dispatch({ type: "recover-draft" }),
    discardDraft: () => {
      if (!state.dirty && bridge?.discardProgressDraft)
        begin("discard", (bridge, token) => bridge.discardProgressDraft?.(path, token));
    },
    selectFilter: (value: string) => { if (isProgressFilter(value)) dispatch({ type: "filter", value }); },
    search: (value: string) => dispatch({ type: "query", value }),
    selectItem: (id: string) => dispatch({ type: "select", id }),
    selectDocument: (path: string, selected: boolean) => dispatch({ type: "document", path, selected }),
    changeKind: (path: string, kind: DocumentKind) => {
      requests.current.invalidateReads(); dispatch({ type: "kind", path, kind });
    },
    edit,
    confirmRequirement: (id: string) => {
      const item = state.draft?.requirements.find((item) => item.id === id);
      if (item && state.draft) edit(id, confirmRequirement(item, state.draft));
    },
    findEvidence: (id: string) => {
      const item = state.draft?.requirements.find((item) => item.id === id);
      if (item && state.busy !== "save") request("evidence", (bridge, token) => bridge.suggestProgressEvidence(path, JSON.stringify(item), token));
    },
    extract: () => {
      if (!state.selectedDocs.length) return;
      begin("extract", (bridge, token) => bridge.previewProgress(path, JSON.stringify(
        state.selectedDocs.map((path) => ({ path, kind: state.documentKinds[path] ?? "current" })),
      ), token));
    },
    save: () => { if (state.draft) begin("save", (bridge, token) => bridge.saveProgress(path, JSON.stringify(state.draft), token)); },
    addManual: () => { requests.current.invalidateReads(); dispatch({ type: "add-manual", id: crypto.randomUUID() }); },
    goToFirstError: () => dispatch({ type: "first-error" }),
    startEvidence: () => dispatch({ type: "start-evidence" }),
    toggleDocuments: () => dispatch({ type: "toggle-documents" }),
    refreshDocuments: () => begin("documents", (bridge, token) => bridge.listProjectDocs(path, token)),
    checkLinks: () => begin("links", (bridge, token) => bridge.checkProgressLinks(path, token)),
    loadTests: () => begin("tests", (bridge, token) => bridge.loadTestResults(path, token)),
    forgetTests: () => { requests.current.invalidateReads(); bridge?.forgetTestResults(path); dispatch({ type: "forget-tests" }); },
    exportProgress: (kind: "md" | "json") => request("export", (bridge, token) => bridge.exportProgress(path, kind, token)),
  };
  const pendingElsewhere = [...sessions.current.values()].filter((cached) => cached.path !== state.path && cached.dirty).length;
  return { state, view, actions, pendingElsewhere };
}
