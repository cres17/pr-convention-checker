import type { ChangeCounts, ProgressHistory } from "../../bridge";

const labels: [keyof ChangeCounts, string][] = [
  ["gained", "새로 구현 확인"],
  ["regressed", "회귀(구현 확인 → 아님)"],
  ["excluded", "범위에서 제외"],
  ["reincluded", "다시 포함"],
  ["added", "추가"],
  ["removed", "삭제"],
];

export function changeText(counts?: ChangeCounts): string {
  return labels.filter(([key]) => counts?.[key]).map(([key, label]) => `${label} ${counts![key]}`).join(" · ");
}

/** What changed since the last saved baseline, and the list of past saves. */
export default function History({ history }: { history: ProgressHistory }) {
  const since = history.since_save;
  return (
    <>
      {since && (
        <div className={`notice ${since.counts.regressed ? "error" : ""}`} role="status">
          마지막 저장(기준 v{since.version}) 이후 변화: {changeText(since.counts) || "완료 확인 수만 달라졌습니다"}
          {since.complete_delta !== 0 && ` · 완료 확인 ${since.complete_delta > 0 ? "+" : ""}${since.complete_delta}`}
          {since.regressed.length > 0 && <> — 회귀: {since.regressed.slice(0, 5).map((item) => item.title).join(", ")}{since.regressed.length > 5 ? " 외" : ""}</>}
        </div>
      )}
      {history.snapshots.length > 0 && (
        <details className="progress-history">
          <summary>진행 이력 {history.snapshots.length}개</summary>
          <ul>
            {history.snapshots.map((row) => (
              <li key={`${row.version}:${row.at}`}>
                <strong>기준 v{row.version}</strong>
                <span>{new Date(row.at).toLocaleString("ko-KR")}</span>
                <span>완료 {row.counts.complete ?? 0} / {row.total} · 구현 확인 {row.counts.implemented ?? 0}</span>
                <small>{row.changes ? changeText(row.changes) || "상태 변화 없음(문서·범위만 변경)" : "첫 기록"}</small>
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}
