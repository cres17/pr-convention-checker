import { useEffect, useMemo, useReducer, useRef } from "react";
import type { Bridge, DocumentKind, ProgressItem } from "../../bridge";
import type { QueuedProgressEvent } from "../../events";
import { isProgressFilter } from "./status";
import { confirmRequirement } from "./requirement";
import { initialProgressState, progressReducer, selectProgressView, type ProgressOperation } from "./progressState";

export type ProjectProgressProps = {
  path: string;
  connected: boolean;
  bridge: Bridge | null;
  events: QueuedProgressEvent[];
  focus?: { id: string; n: number } | null;
};
/** Own the local editor session. Only this boundary talks to Qt or focuses DOM fields. */
export default function useProjectProgress({ path, connected, bridge, events, focus = null }: ProjectProgressProps) {
  const [state, dispatch] = useReducer(progressReducer, path, initialProgressState);
  const view = useMemo(() => selectProgressView(state), [state]);
  const handledSeq = useRef(events.at(-1)?._seq ?? 0);
  const handledFocus = useRef(0);
  const handledInspection = useRef(0);

  useEffect(() => {
    dispatch({ type: "reset", path, connected: connected && !!bridge });
    if (connected && path && bridge) bridge.listProjectDocs(path);
  }, [path, connected, bridge]);
  useEffect(() => {
    for (const event of events) {
      if (event._seq <= handledSeq.current) continue;
      handledSeq.current = event._seq;
      dispatch({ type: "event", event });
    }
  }, [events]);
  useEffect(() => {
    if (handledInspection.current === state.inspections) return;
    handledInspection.current = state.inspections;
    if (connected && state.path === path && state.inspections && !state.dirty)
      bridge?.inspectProgress(path);
  }, [state.inspections, state.path, state.dirty, connected, bridge, path]);
  useEffect(() => {
    if (!focus?.id || focus.n === handledFocus.current || !state.draft?.requirements.some((item) => item.id === focus.id)) return;
    handledFocus.current = focus.n;
    dispatch({ type: "focus-item", id: focus.id });
  }, [focus, state.draft]);
  useEffect(() => {
    if (!state.focusField) return;
    document.querySelector<HTMLElement>(`[data-field="${state.focusField}"]`)?.focus();
    dispatch({ type: "clear-focus" });
  }, [state.focusField, state.selectedId]);

  const begin = (operation: Exclude<ProgressOperation, "">, run: (bridge: Bridge) => void) => {
    if (!connected || !path || !bridge || state.busy) return;
    dispatch({ type: "begin", operation });
    run(bridge);
  };
  const actions = {
    selectFilter: (value: string) => {
      if (isProgressFilter(value)) dispatch({ type: "filter", value });
    },
    search: (value: string) => dispatch({ type: "query", value }),
    selectItem: (id: string) => dispatch({ type: "select", id }),
    selectDocument: (path: string, selected: boolean) => dispatch({ type: "document", path, selected }),
    changeKind: (path: string, kind: DocumentKind) => dispatch({ type: "kind", path, kind }),
    edit: (id: string, patch: Partial<ProgressItem>) => dispatch({ type: "edit", id, patch }),
    confirmRequirement: (id: string) => {
      const item = state.draft?.requirements.find((item) => item.id === id);
      if (item && state.draft) dispatch({ type: "edit", id, patch: confirmRequirement(item, state.draft) });
    },
    findEvidence: (id: string) => {
      const item = state.draft?.requirements.find((item) => item.id === id);
      if (item && state.busy !== "save") bridge?.suggestProgressEvidence(path, JSON.stringify(item));
    },
    extract: () => {
      if (!state.selectedDocs.length) return;
      begin("extract", (bridge) => bridge.previewProgress(path, JSON.stringify(
        state.selectedDocs.map((path) => ({ path, kind: state.documentKinds[path] ?? "current" })),
      )));
    },
    save: () => {
      if (state.draft) begin("save", (bridge) => bridge.saveProgress(path, JSON.stringify(state.draft)));
    },
    addManual: () => dispatch({ type: "add-manual", id: crypto.randomUUID() }),
    goToFirstError: () => dispatch({ type: "first-error" }),
    startEvidence: () => dispatch({ type: "start-evidence" }),
    toggleDocuments: () => dispatch({ type: "toggle-documents" }),
    refreshDocuments: () => begin("documents", (bridge) => bridge.listProjectDocs(path)),
    checkLinks: () => begin("links", (bridge) => bridge.checkProgressLinks(path)),
    loadTests: () => begin("tests", (bridge) => bridge.loadTestResults(path)),
    forgetTests: () => { bridge?.forgetTestResults(path); dispatch({ type: "forget-tests" }); },
    exportProgress: (kind: "md" | "json") => bridge?.exportProgress(path, kind),
  };
  return { state, view, actions };
}
