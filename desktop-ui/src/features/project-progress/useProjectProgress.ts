import { useEffect, useMemo, useReducer, useRef } from "react";
import type { Bridge, DocumentKind, ProgressItem } from "../../bridge";
import type { QueuedProgressEvent } from "../../events";
import { isProgressFilter } from "./status";
import { confirmRequirement } from "./requirement";
import { initialProgressState, progressReducer, selectProgressView, type ProgressOperation, type ProgressState } from "./progressState";
import type { ProgressRequest } from "./requestSession";
import { EditorSessions } from "./editorSessions";

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
  const sessions = useRef(new EditorSessions());
  const [sessionRevision, refreshSessions] = useReducer((value: number) => value + 1, 0);
  const latestState = useRef(state);
  latestState.current = state;
  const operation = useRef<ProgressOperation>("");
  const operationToken = useRef("");
  const handledSeq = useRef(events.at(-1)?._seq ?? 0);
  const handledFocus = useRef(0);
  const handledInspection = useRef(0);
  const queuedDraft = useRef<{ path: string; draft: NonNullable<ProgressState["draft"]>; timer: ReturnType<typeof setTimeout> } | null>(null);

  useEffect(() => {
    const previous = latestState.current;
    if (previous.path) {
      sessions.current.keep(previous);
      sessions.current.leave(previous.path);
    }
    operation.current = "";
    handledInspection.current = 0;
    const retained = sessions.current.get(path);
    operationToken.current = retained?.busy ? sessions.current.requests(path).token(retained.busy) ?? '' : '';
    dispatch({ type: "restore", path, retained, connected: connected && !!bridge });
    if (connected && path && bridge) bridge.listProjectDocs(path, sessions.current.requests(path).start("documents"));
  }, [path, connected, bridge]);
  useEffect(() => {
    for (const event of events) {
      if (event._seq <= handledSeq.current) continue;
      handledSeq.current = event._seq;
      if (event.requested_path && event.requested_path !== path) {
        if (sessions.current.receiveInactive(event)) refreshSessions();
        continue;
      }
      const requests = sessions.current.requests(path);
      if (!requests.accepts(event)) {
        if (event.request_done && event.request_id === operationToken.current)
          dispatch({ type: "end", operation: operation.current });
        continue;
      }
      if (event.type === 'progressPreview' || event.type === 'progressSaved') requests.cancel('draft');
      dispatch({ type: "event", event });
      requests.complete(event);
    }
  }, [events, path]);
  useEffect(() => { operation.current = state.busy; }, [state.busy]);
  useEffect(() => {
    if (!connected || !bridge?.cacheProgressDraft || state.path !== path || !state.path || !state.draft || !state.dirty
      || state.busy === "save" || state.draftStatus === "cached") return;
    const requests = sessions.current.requests(state.path);
    if (requests.token('draft')) return;
    dispatch({ type: "cache-draft" });
    const draft = { ...state.draft, edit_base: state.base };
    const timer = setTimeout(() => {
      queuedDraft.current = null;
      bridge.cacheProgressDraft?.(state.path, JSON.stringify(draft), requests.start("draft"));
    }, 650);
    queuedDraft.current = { path: state.path, draft, timer };
    return () => clearTimeout(timer);
  }, [state.draft, state.dirty, state.path, state.busy, state.base, path, connected, bridge]);
  // A repository switch/unmount flushes the last edit; a confirmed save cancels it below.
  useEffect(() => () => {
    const queued = queuedDraft.current;
    if (!queued) return;
    clearTimeout(queued.timer);
    queuedDraft.current = null;
    bridge?.cacheProgressDraft?.(queued.path, JSON.stringify(queued.draft), sessions.current.requests(queued.path).start("draft"));
  }, [path, bridge]);
  useEffect(() => {
    if (state.path !== path) return;
    sessions.current.keep(state);
    sessions.current.prune(path);
    const pending = sessions.current.pending.length > 0;
    bridge?.setProgressDirty?.(pending);
    bridge?.setProgressRecoveryReady?.(sessions.current.pending
      .every((session) => session.draftStatus === "cached"));
    onPendingChange?.(pending);
    if (!pending) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [state, path, sessionRevision, bridge, onPendingChange]);
  useEffect(() => {
    if (handledInspection.current === state.inspections) return;
    handledInspection.current = state.inspections;
    if (connected && state.path === path && state.inspections && !state.dirty)
      bridge?.inspectProgress(path, sessions.current.requests(path).start("inspect"));
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
    if ((view.recoveryPending && purpose !== "discard" && purpose !== 'documents') || (state.conflict && purpose === 'save')) return;
    operation.current = purpose;
    if (purpose === "save" && queuedDraft.current) {
      clearTimeout(queuedDraft.current.timer);
      queuedDraft.current = null;
    }
    const requests = sessions.current.requests(path);
    if (purpose === "save" || purpose === "extract") requests.invalidateReads();
    dispatch({ type: "begin", operation: purpose });
    operationToken.current = requests.start(purpose);
    run(bridge, operationToken.current);
  };
  const request = (purpose: ProgressRequest, run: (bridge: Bridge, id: string) => void) => {
    if (connected && path && bridge && state.path === path) run(bridge, sessions.current.requests(path).start(purpose));
  };
  const edit = (id: string, patch: Partial<ProgressItem>) => {
    if (state.busy === "save") return;
    sessions.current.requests(state.path).invalidateReads();
    sessions.current.requests(state.path).cancel('draft');
    dispatch({ type: "edit", id, patch });
  };
  const actions = {
    recoverDraft: () => dispatch({ type: "recover-draft" }),
    chooseRecovery: (key: string) => begin('documents', (bridge, token) => bridge.listProjectDocs(path, token, key)),
    rebase: (choice: 'local' | 'latest') => {
      sessions.current.requests(state.path).cancel('draft');
      dispatch({ type: 'rebase', choice });
    },
    discardDraft: () => {
      if (!state.dirty && bridge?.discardProgressDraft)
        begin("discard", (bridge, token) => bridge.discardProgressDraft?.(path, token, state.recoveryKey, state.recoveryRevision));
    },
    selectFilter: (value: string) => { if (isProgressFilter(value)) dispatch({ type: "filter", value }); },
    search: (value: string) => dispatch({ type: "query", value }),
    selectItem: (id: string) => dispatch({ type: "select", id }),
    selectDocument: (path: string, selected: boolean) => dispatch({ type: "document", path, selected }),
    changeKind: (path: string, kind: DocumentKind) => {
      sessions.current.requests(state.path).invalidateReads(); sessions.current.requests(state.path).cancel('draft');
      dispatch({ type: "kind", path, kind });
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
    addManual: () => { sessions.current.requests(state.path).invalidateReads(); sessions.current.requests(state.path).cancel('draft'); dispatch({ type: "add-manual", id: crypto.randomUUID() }); },
    goToFirstError: () => dispatch({ type: "first-error" }),
    startEvidence: () => dispatch({ type: "start-evidence" }),
    toggleDocuments: () => dispatch({ type: "toggle-documents" }),
    refreshDocuments: () => begin("documents", (bridge, token) => bridge.listProjectDocs(path, token)),
    checkLinks: () => begin("links", (bridge, token) => bridge.checkProgressLinks(path, token)),
    loadTests: () => begin("tests", (bridge, token) => bridge.loadTestResults(path, token)),
    forgetTests: () => { sessions.current.requests(path).invalidateReads(); bridge?.forgetTestResults(path); dispatch({ type: "forget-tests" }); },
    exportProgress: (kind: "md" | "json") => request("export", (bridge, token) => bridge.exportProgress(path, kind, token)),
  };
  const pendingElsewhere = sessions.current.pending.filter((cached) => cached.path !== state.path).length;
  return { state, view, actions, pendingElsewhere };
}
