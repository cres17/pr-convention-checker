// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, renderHook } from '@testing-library/react';
import type { Bridge, ProgressBaseline } from '../../bridge';
import type { ProgressEvent, QueuedProgressEvent } from '../../events';
import useProjectProgress from './useProjectProgress';
afterEach(() => { cleanup(); vi.useRealTimers(); });
const baseline = (path: string): ProgressBaseline => ({
  repository: path, version: 1, documents: { 'README.md': 'h' },
  requirements: [{
    id: 'one', title: 'old', criterion: 'criterion', area: 'feature', included: true,
    source: { path: 'README.md', line: 1, excerpt: 'old', sha256: 'h' },
    implementation_status: 'unknown', evidence: null, verification_status: 'unverified', verification_note: '',
  }],
});
function page() {
  const bridge = {
    listProjectDocs: vi.fn(), inspectProgress: vi.fn(), saveProgress: vi.fn(), cacheProgressDraft: vi.fn(),
    setProgressDirty: vi.fn(), setProgressRecoveryReady: vi.fn(),
  } as unknown as Bridge;
  let path = '/one'; let events: QueuedProgressEvent[] = [];
  const hook = renderHook(() => useProjectProgress({path,events,bridge,connected:true}));
  const emit = (event: ProgressEvent) => act(() => {events=[...events,{...event,_seq:events.length+1}];hook.rerender();});
  const move = (next: string) => act(() => {path=next;hook.rerender();});
  emit({type:'progressDocs',documents:[],omitted:0,baseline:baseline(path)});
  return {bridge,hook,emit,move};
}
it('marks an inactive repository cache as ready after its completed response', () => {
  vi.useFakeTimers(); const p=page();
  act(() => p.hook.result.current.actions.edit('one',{title:'edited'}));
  act(() => vi.advanceTimersByTime(650));
  const [path,,request_id] = vi.mocked(p.bridge.cacheProgressDraft!).mock.calls.at(-1)!;
  p.move('/two');
  p.emit({type:'progressDraftCached',requested_path:path,request_id,request_done:true});
  p.emit({type:'progressDocs',documents:[],omitted:0,baseline:baseline('/two')});
  expect(vi.mocked(p.bridge.setProgressRecoveryReady!).mock.calls.at(-1)?.[0]).toBe(true);
});
it('retains a successful background save when returning to its repository', () => {
  vi.useFakeTimers(); const p=page();
  act(() => p.hook.result.current.actions.edit('one',{title:'saved title'}));
  act(() => p.hook.result.current.actions.save());
  const [path,payload,request_id] = vi.mocked(p.bridge.saveProgress).mock.calls.at(-1)!;
  const saved = {...JSON.parse(payload),version:2};
  p.move('/two');
  p.emit({type:'progressSaved',requested_path:path,request_id,request_done:true,baseline:saved});
  p.emit({type:'progressDocs',documents:[],omitted:0,baseline:baseline('/two')});
  p.move('/one');
  p.emit({type:'progressDocs',documents:[],omitted:0,baseline:saved});
  act(() => vi.advanceTimersByTime(650));
  expect(p.hook.result.current.state.dirty).toBe(false);
  expect(p.hook.result.current.state.draft?.version).toBe(2);
  act(() => vi.advanceTimersByTime(650));
  expect(p.bridge.cacheProgressDraft).not.toHaveBeenCalled();
});

it('locks fields after returning before the outstanding save finishes', () => {
  const p = page();
  act(() => p.hook.result.current.actions.edit('one', { title: 'submitted' }));
  act(() => p.hook.result.current.actions.save());
  const [path, payload, request_id] = vi.mocked(p.bridge.saveProgress).mock.calls.at(-1)!;
  p.move('/two');
  p.move('/one');
  expect(p.hook.result.current.state.busy).toBe('save');
  act(() => p.hook.result.current.actions.edit('one', { title: 'must stay locked' }));
  act(() => p.hook.result.current.actions.save());
  expect(p.hook.result.current.state.draft?.requirements[0].title).toBe('submitted');
  expect(p.bridge.saveProgress).toHaveBeenCalledOnce();
  p.emit({ type: 'progressSaved', requested_path: path, request_id, request_done: true,
    baseline: { ...JSON.parse(payload), version: 2 } });
  expect(p.hook.result.current.state.dirty).toBe(false);
});

it('retains a background save failure and the editable draft on return', () => {
  const p = page();
  act(() => p.hook.result.current.actions.edit('one', { title: 'keep this edit' }));
  act(() => p.hook.result.current.actions.save());
  const [path, , request_id] = vi.mocked(p.bridge.saveProgress).mock.calls.at(-1)!;
  p.move('/two');
  p.emit({ type: 'progressError', requested_path: path, request_id, request_done: true, message: 'disk full' });
  p.move('/one');
  p.emit({ type: 'progressDocs', documents: [], omitted: 0, baseline: baseline(path) });
  expect(p.hook.result.current.state.error).toBe('disk full');
  expect(p.hook.result.current.state.dirty).toBe(true);
  expect(p.hook.result.current.state.draft?.requirements[0].title).toBe('keep this edit');
  act(() => p.hook.result.current.actions.edit('one', { title: 'still editable' }));
  expect(p.hook.result.current.state.draft?.requirements[0].title).toBe('still editable');
});

it('does not mark a later edit cached when an older autosave completes', () => {
  vi.useFakeTimers();
  const p = page();
  act(() => p.hook.result.current.actions.edit('one', { title: 'earlier' }));
  act(() => vi.advanceTimersByTime(650));
  const [path, , request_id] = vi.mocked(p.bridge.cacheProgressDraft!).mock.calls.at(-1)!;
  act(() => p.hook.result.current.actions.edit('one', { title: 'latest' }));
  p.move('/two');
  p.emit({ type: 'progressDraftCached', requested_path: path, request_id, request_done: true });
  expect(vi.mocked(p.bridge.setProgressRecoveryReady!).mock.calls.at(-1)?.[0]).toBe(false);
  const current = vi.mocked(p.bridge.cacheProgressDraft!).mock.calls.at(-1)!;
  expect(JSON.parse(current[1]).requirements[0].title).toBe('latest');
  p.emit({ type: 'progressDraftCached', requested_path: current[0], request_id: current[2], request_done: true });
  expect(vi.mocked(p.bridge.setProgressRecoveryReady!).mock.calls.at(-1)?.[0]).toBe(true);
});

it('merges a conflict against the baseline originally read and preserves recovery ancestry', () => {
  vi.useFakeTimers();
  const p = page();
  act(() => p.hook.result.current.actions.edit('one', { title: 'my title' }));
  act(() => p.hook.result.current.actions.save());
  const [path, , request_id] = vi.mocked(p.bridge.saveProgress).mock.calls.at(-1)!;
  const latest = baseline(path);
  latest.version = 2; latest.requirements[0].area = 'their area';
  p.emit({ type: 'progressError', requested_path: path, request_id, request_done: true,
    message: 'conflict', current_baseline: latest });
  act(() => p.hook.result.current.actions.save());
  expect(p.bridge.saveProgress).toHaveBeenCalledOnce();
  expect(p.hook.result.current.view.merge?.conflicts).toEqual([]);
  act(() => p.hook.result.current.actions.rebase('latest'));
  expect(p.hook.result.current.state.draft?.requirements[0]).toMatchObject({ title: 'my title', area: 'their area' });
  act(() => vi.advanceTimersByTime(650));
  const recovery = JSON.parse(vi.mocked(p.bridge.cacheProgressDraft!).mock.calls.at(-1)![1]);
  expect(recovery.edit_base).toEqual(latest);
  act(() => p.hook.result.current.actions.save());
  expect(JSON.parse(vi.mocked(p.bridge.saveProgress).mock.calls.at(-1)![1]).version).toBe(2);
});

it('keeps a background extraction and schedules its recovery copy when returning', () => {
  vi.useFakeTimers();
  const p = page();
  act(() => p.hook.result.current.actions.edit('one', { title: 'existing edit' }));
  p.bridge.previewProgress = vi.fn();
  act(() => p.hook.result.current.actions.extract());
  const [path, , request_id] = vi.mocked(p.bridge.previewProgress).mock.calls.at(-1)!;
  p.move('/two');
  const extra = { ...baseline(path).requirements[0], id: 'extra', title: 'new extracted goal' };
  p.emit({ type: 'progressPreview', requested_path: path, request_id, request_done: true,
    documents: { 'README.md': 'h' }, requirements: [baseline(path).requirements[0], extra] });
  p.move('/one');
  p.emit({ type: 'progressDocs', documents: [], omitted: 0, baseline: baseline(path) });
  expect(p.hook.result.current.state.draft?.requirements.map((item) => item.title)).toEqual(['existing edit', 'new extracted goal']);
  act(() => vi.advanceTimersByTime(650));
  expect(JSON.parse(vi.mocked(p.bridge.cacheProgressDraft!).mock.calls.at(-1)![1]).requirements).toHaveLength(2);
});
