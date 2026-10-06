import { expect, it } from 'vitest';
import { decodeDesktopEvent } from '../../eventSchema';
import type { ProgressBaseline, ProgressItem } from '../../bridge';
import { initialProgressState, progressReducer, type ProgressState } from './progressState';
import { MAX_REQUIREMENTS, MAX_RECOVERY_REQUIREMENTS } from './limits';
import contract from '../../../../drift_gate/tests/contracts/progress.json';

const item: ProgressItem = { id: 'a', title: 'a', criterion: 'a', area: '', included: true,
 source: { path: 'README.md', line: 0, excerpt: '', sha256: 'h' }, implementation_status: 'unknown',
 evidence: null, verification_status: 'unverified', verification_note: '' };
const baseline: ProgressBaseline = { repository:'/fixture', version:1, baseline_id:'one', documents:{'README.md':'h'}, requirements:[item] };

it('checks reducer capacity even when two actions arrive before a render', () => {
 let state: ProgressState = { ...initialProgressState('/fixture'), draft: { ...baseline,
 requirements:Array.from({length:119}, (_, n) => ({...item, id:String(n)})) } };
 state = progressReducer(state, {type:'add-manual', id:'first'});
 state = progressReducer(state, {type:'add-manual', id:'second'});
 expect(state.draft?.requirements).toHaveLength(120);
 expect(state.draft?.requirements.some((value) => value.id === 'second')).toBe(false);
});

it('rejects derived history, tests and links from a replaced baseline', () => {
 const state = {...initialProgressState('/fixture'), draft:baseline};
 const meta = {baseline_version:2, baseline_id:'two', inspection_id:'later'};
 const history = progressReducer(state, {type:'event', event:{type:'progressHistory', snapshots:[], since_save:null, ...meta}});
 const tests = progressReducer(state, {type:'event', event:{type:'progressTests', format:'junit', file:'x', modified:'', total:0, items:{}, ...meta}});
 const links = progressReducer(state, {type:'event', event:{type:'progressLinks', documents:[], checked:0, issues:[], truncated:false, limitations:'', ...meta}});
 expect(history.history).toBeNull(); expect(tests.tests).toBeNull(); expect(links.links).toBeNull();
 // Equal numeric version does not make a different baseline identity acceptable.
 expect(progressReducer(state, {type:'event', event:{type:'progressHistory', snapshots:[], since_save:null, ...meta, baseline_version:1}}).history).toBeNull();
});

it('preserves the baseline context on the real wire and permits bounded overflow recovery only', () => {
 const meta = { requested_path:'/fixture', request_id:'checked', request_done:true, baseline_version:1, baseline_id:'one', inspection_id:'scan' };
 const event = decodeDesktopEvent(JSON.stringify({type:'progressHistory', snapshots:[], since_save:null, ...meta}));
 expect(event).toMatchObject(meta);
 const recovery = {...baseline, requirements:Array.from({length:121}, (_,n) => ({...item,id:String(n)}))};
 const decoded = decodeDesktopEvent(JSON.stringify({type:'progressDocs', documents:[], omitted:0, recovery, requested_path:'/fixture', request_id:'r'}));
 expect(decoded.type).toBe('progressDocs');
 if(decoded.type === 'progressDocs') expect(decoded.recovery?.requirements).toHaveLength(121);
 const invalid = decodeDesktopEvent(JSON.stringify({type:'progressSaved', baseline:recovery, requested_path:'/fixture', request_id:'r'}));
 expect(invalid.type).toBe('progressError');
});

it('uses the same recovery fixture and capacity values as the Python boundary', () => {
 expect(contract.limits).toEqual({confirmed:MAX_REQUIREMENTS, recovery:MAX_RECOVERY_REQUIREMENTS});
 const payload = {type:'progressDocs', documents:[], omitted:0, recovery:contract.recovery,
   requested_path:'/fixture', request_id:'shared'};
 const event = decodeDesktopEvent(JSON.stringify(payload));
 expect(event.type).toBe('progressDocs');
 if (event.type === 'progressDocs') expect(event.recovery).toEqual(contract.recovery);
 const invalid = structuredClone(payload);
 Object.assign(invalid.recovery.requirements[0].evidence, {line:'invalid'});
 const rejected = decodeDesktopEvent(JSON.stringify(invalid));
 if (rejected.type === 'progressDocs') expect(rejected.recovery).toBeNull();
 else throw new Error('Expected the confirmed document context to remain available');
});

it('preserves archived provenance and reactivates only explicitly extracted paths', async () => {
 const { mergeProgressPreview } = await import('./merge');
 const { activeDocuments } = await import('./documents');
 const archived = { ...baseline, archived_documents: ['README.md'], document_kinds: {'README.md':'reference' as const} };
 const refreshed = mergeProgressPreview(archived, { repository:baseline.repository,
   documents:{'PLAN.md':'new'}, document_kinds:{'PLAN.md':'current'}, requirements:[] });
 expect(activeDocuments(refreshed)).toEqual(['PLAN.md']);
 expect(refreshed.requirements).toEqual(baseline.requirements);
 expect(refreshed.baseline_id).toBe(baseline.baseline_id);
 const reactivated = mergeProgressPreview(refreshed, { repository:baseline.repository,
   documents:{'README.md':'h'}, document_kinds:{'README.md':'current'}, requirements:[item] });
 expect(reactivated.archived_documents).toEqual([]);
 expect(reactivated.requirements).toHaveLength(1);
 const event = decodeDesktopEvent(JSON.stringify({type:'progressSaved', baseline:refreshed,
   requested_path:'/fixture', request_id:'archive'}));
 expect(event.type).toBe('progressSaved');
 if (event.type === 'progressSaved') expect(event.baseline.archived_documents).toEqual(['README.md']);
});

it('does not let archive actions bypass pending recovery protection', () => {
 const state = {...initialProgressState('/fixture'), draft:baseline, recovery:baseline};
 expect(progressReducer(state, {type:'archive-document', path:'README.md'})).toBe(state);
});

it('allows ten active bindings plus archived provenance when merging extraction', async () => {
 const { mergeProgressPreview } = await import('./merge');
 const documents = {...baseline.documents, ...Object.fromEntries(Array.from({length:9}, (_,n) => [`doc${n}.md`, 'h']))};
 const previous = {...baseline, documents, archived_documents:['README.md'], document_kinds:{'README.md':'reference' as const}};
 const result = mergeProgressPreview(previous, {repository:baseline.repository, documents:{'PLAN.md':'h'}, requirements:[]});
 expect(Object.keys(result.documents)).toHaveLength(11);
 expect(result.archived_documents).toEqual(['README.md']);
});
