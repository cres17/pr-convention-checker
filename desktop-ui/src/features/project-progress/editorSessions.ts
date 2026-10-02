import type { ProgressEvent } from '../../events';
import { progressReducer, type ProgressState } from './progressState';
import { ProgressRequests } from './requestSession';

/** State and write requests share the lifetime of each repository's editor. */
export class EditorSessions {
  private states = new Map<string, ProgressState>();
  private requestSets = new Map<string, ProgressRequests>();
  get(path: string) { return this.states.get(path); }
  keep(state: ProgressState) { if (state.path) this.states.set(state.path, state); }
  requests(path: string) {
    let requests = this.requestSets.get(path);
    if (!requests) { requests = new ProgressRequests(); this.requestSets.set(path, requests); }
    return requests;
  }
  leave(path: string) {
    this.requests(path).leave();
    const state = this.get(path);
    if (state && !['save', 'extract', 'discard'].includes(state.busy))
      this.keep({ ...state, busy: '' });
  }
  receiveInactive(event: ProgressEvent) {
    const path = event.requested_path;
    if (!path || !event.request_id) return false;
    const state = this.get(path), requests = this.requestSets.get(path);
    if (!state || !requests?.accepts(event)) return false;
    if (event.type === 'progressPreview' || event.type === 'progressSaved') requests.cancel('draft');
    this.keep(progressReducer(state, { type: 'event', event }));
    requests.complete(event);
    return true;
  }
  prune(active: string) {
    for (const [path, state] of this.states) {
      const requests = this.requests(path);
      if (path !== active && !state.dirty && !(['save', 'extract', 'discard'] as const).some(
        (purpose) => requests.token(purpose))) {
        this.states.delete(path); this.requestSets.delete(path);
      }
    }
  }
  get pending() { return [...this.states.values()].filter((state) => state.dirty); }
}
