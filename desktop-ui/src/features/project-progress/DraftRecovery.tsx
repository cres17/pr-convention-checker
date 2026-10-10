import { useEffect, useState } from 'react';
import type { RecoveryOption } from '../../bridge';

type Props = {
  options: RecoveryOption[]; selected: string; warning: string; recoverable: boolean; busy: boolean;
  onSelect: (key: string) => void; onRecover: () => void; onDiscard: () => void;
  onDiscardCopies: (options: RecoveryOption[]) => void;
  onKeepCopies: () => void;
};

/** Recovery and explicit cleanup share the same revision-bearing snapshot. */
export default function DraftRecovery({ options, selected, warning, recoverable, busy,
  onSelect, onRecover, onDiscard, onDiscardCopies, onKeepCopies }: Props) {
  const [checked, setChecked] = useState<string[]>([]);
  useEffect(() => setChecked([]), [options]);
  const active = options.find((copy) => copy.key === selected)?.active;
  const chosen = options.filter((copy) => checked.includes(copy.key));
  return <div className="notice" role="status"><div>
    <strong>이전 편집 초안이 있습니다.</strong>
    <p>{warning || '초안을 복구해서 이어서 편집할 수 있습니다. 확정된 기준은 저장 버튼을 누를 때 바뀝니다.'}</p>
    {!!options.length && <p>보관 사본 {options.length}개 · {(options.reduce((sum, copy) => sum + (copy.bytes ?? 0), 0) / 1024).toFixed(1)}KB</p>}
    {options.length >= 20 && <p>초안 사본이 많이 쌓였습니다. 필요한 사본을 확인한 뒤 선택해서 정리해 주세요. 자동 삭제하지 않습니다.</p>}
    {options.length > 1 && <label>복구할 초안{' '}
      <select aria-label="복구할 초안" value={selected} disabled={busy} onChange={(event) => onSelect(event.target.value)}>
        {options.map((copy, index) => <option key={copy.key} value={copy.key}>
          {index === 0 ? '가장 최근' : `이전 사본 ${index}`} · {new Date(copy.updated_at).toLocaleString('ko-KR')}{copy.active ? ' · 실행 중' : ''}
        </option>)}
      </select>
    </label>}
    {active && <p>이 사본은 다른 실행에서 사용 중입니다. 해당 앱을 닫고 목록을 새로고침하면 복구하거나 삭제할 수 있습니다.</p>}
    <div className="progress-actions">
      {recoverable && <button className="primary" disabled={busy || active} onClick={onRecover}>초안 복구</button>}
      <button className="secondary" disabled={busy || active} onClick={onDiscard}>보관된 초안 삭제</button>
      <button className="text-button" disabled={busy} onClick={() => onSelect(selected)}>초안 목록 새로고침</button>
      <button className="text-button" disabled={busy} onClick={onKeepCopies}>초안은 보존하고 기준 편집</button>
    </div>
    {options.length > 1 && <details><summary>초안 사본 선택해서 정리</summary>
      <p>선택한 사본의 미저장 편집이 삭제됩니다. 실행 중인 사본은 선택할 수 없습니다.</p>
      {options.map((copy, index) => <label key={copy.key} style={{ display: 'block' }}>
        <input type="checkbox" aria-label={`정리할 초안 ${index + 1}`} disabled={busy || copy.active || !copy.revision}
          checked={checked.includes(copy.key)} onChange={(event) => setChecked((current) => event.target.checked
            ? [...current, copy.key] : current.filter((key) => key !== copy.key))} />{' '}
        {new Date(copy.updated_at).toLocaleString('ko-KR')} · {((copy.bytes ?? 0) / 1024).toFixed(1)}KB{copy.active ? ' · 실행 중' : ''}
      </label>)}
      <button className="secondary" disabled={busy || !chosen.length}
        onClick={() => onDiscardCopies(chosen)}>선택한 초안 {chosen.length}개 삭제</button>
    </details>}
  </div></div>;
}
