import { describe, expect, it } from 'vitest';
import type { ProgressBaseline, ProgressItem } from '../../bridge';
import { rebaseProgress } from './rebase';

const item = (id: string): ProgressItem => ({ id, title: id, criterion: 'original', area: 'feature', included: true,
  source: { path: 'README.md', line: 1, excerpt: id, sha256: 'old' },
  implementation_status: 'unknown', evidence: null, verification_status: 'unverified', verification_note: '' });
const baseline = (): ProgressBaseline => ({ repository: '/repo', version: 1,
  documents: { 'README.md': 'old' }, requirements: [item('one'), item('two')] });
const copy = (value: ProgressBaseline) => structuredClone(value);

it('preserves independent edits and additions from both editors without mutating inputs', () => {
  const base = baseline(), local = copy(base), latest = copy(base);
  local.requirements[0].title = 'my title';
  local.requirements.push(item('my addition'));
  latest.version = 2;
  latest.requirements[0].area = 'latest area';
  latest.requirements[1].criterion = 'latest condition';
  latest.requirements.push(item('their addition'));
  const originals = [copy(base), copy(local), copy(latest)];
  const merged = rebaseProgress(base, local, latest);
  expect(merged.conflicts).toEqual([]);
  expect(merged.draft.version).toBe(2);
  expect(merged.draft.requirements[0]).toMatchObject({ title: 'my title', area: 'latest area' });
  expect(merged.draft.requirements[1].criterion).toBe('latest condition');
  expect(merged.draft.requirements.map((i) => i.id)).toEqual(['one', 'two', 'their addition', 'my addition']);
  expect([base, local, latest]).toEqual(originals);
});

it('requires an explicit choice for overlapping fields and preserves unrelated edits', () => {
  const base = baseline(), local = copy(base), latest = copy(base);
  local.requirements[0].title = 'mine'; latest.requirements[0].title = 'theirs';
  local.requirements[1].area = 'my area'; latest.requirements[1].title = 'their title';
  for (const choice of ['local', 'latest'] as const) {
    const result = rebaseProgress(base, local, latest, choice);
    expect(result.conflicts).toEqual(['mine · 기능명']);
    expect(result.draft.requirements[0].title).toBe(choice === 'local' ? 'mine' : 'theirs');
    expect(result.draft.requirements[1]).toMatchObject({ title: 'their title', area: 'my area' });
  }
});

describe('manual review remains bound to the condition and evidence it actually reviewed', () => {
  it('does not attach another editor’s verification to a newly edited condition', () => {
    const base = baseline(), local = copy(base), latest = copy(base);
    local.requirements[0].criterion = 'new condition';
    latest.requirements[0] = { ...latest.requirements[0], implementation_status: 'implemented',
      evidence: { path: 'src/api.py', line: 1, note: 'reviewed' }, verification_status: 'verified', verification_note: 'tested old condition' };
    const mine = rebaseProgress(base, local, latest, 'local');
    expect(mine.conflicts).toEqual(['one · 완료 조건·근거·검증']);
    expect(mine.draft.requirements[0]).toMatchObject({ criterion: 'new condition', implementation_status: 'unknown', evidence: null, verification_status: 'unverified' });
    const theirs = rebaseProgress(base, local, latest, 'latest');
    expect(theirs.draft.requirements[0]).toMatchObject({ criterion: 'original', verification_status: 'verified' });
  });
  it('does not create a code location from different editors’ evidence fields', () => {
    const base = baseline();
    base.requirements[0].implementation_status = 'implemented';
    base.requirements[0].evidence = { path: 'a.py', line: 1, note: 'old' };
    const local = copy(base), latest = copy(base);
    local.requirements[0].evidence!.path = 'b.py'; latest.requirements[0].evidence!.line = 5;
    expect(rebaseProgress(base, local, latest, 'local').draft.requirements[0].evidence).toMatchObject({ path: 'b.py', line: 1 });
    expect(rebaseProgress(base, local, latest, 'latest').draft.requirements[0].evidence).toMatchObject({ path: 'a.py', line: 5 });
  });
  it('keeps an earlier document review boundary when newer documents are merged', () => {
    const base = baseline(); base.requirements[0].implementation_status = 'not_implemented';
    const local = copy(base), latest = copy(base);
    latest.documents['README.md'] = 'new';
    local.requirements[0].title = 'my edit';
    expect(rebaseProgress(base, local, latest).draft.requirements[0].reviewed_documents).toEqual({ 'README.md': 'old' });
  });
});

it('treats unknown recovery ancestry conservatively and does not truncate overflow', () => {
  const local = baseline(), latest = copy(local);
  latest.requirements[0].title = 'newer title';
  expect(rebaseProgress(null, local, latest).conflicts).toContain('one · 기능명');
  for (let n = 0; n < 119; n++) local.requirements.push(item(`local-${n}`));
  expect(rebaseProgress(null, local, latest).overflow).toBe(true);
  expect(rebaseProgress(null, local, latest).draft.requirements).toHaveLength(121);
});

it('preserves IDs that coincide with object prototype names', () => {
  const local = baseline(), latest = copy(local);
  local.requirements.push(item('__proto__'));
  const result = rebaseProgress(local, local, latest);
  expect(result.draft.requirements.map((i) => i.id)).toEqual(['one', 'two']);
  const added = rebaseProgress(baseline(), local, latest);
  expect(added.draft.requirements.at(-1)?.id).toBe('__proto__');
});
