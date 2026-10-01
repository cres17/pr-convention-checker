import type { ProgressItem, ProgressReport } from "../../bridge";
import { statusText } from "./presentation";
import { isStaleEvidence } from "./status";

type Props = {
  report: ProgressReport | null;
  currentItems: ProgressItem[];
  filter: string;
  onFilter: (value: string) => void;
  onStartEvidence: () => void;
};
export default function ProgressOverview({
  report,
  currentItems,
  filter,
  onFilter,
  onStartEvidence,
}: Props) {
  const count = report?.counts;
  const allUnknown = !!report?.total && count?.unknown === report.total;
  const noEvidence =
    allUnknown &&
    !report?.stale_documents.length &&
    currentItems.every(
      (entry) => !entry.evidence && !isStaleEvidence(entry, report),
    );
  const percentage = (value: number) =>
    report?.total
      ? `${Math.round((value / report.total) * 100)}%`
      : "대상 없음";
  return (
    <>
      <section className="progress-overview" aria-label="구현 현황 요약">
        <button
          className="progress-stat"
          disabled={!count}
          aria-label={
            count
              ? `완료 확인 ${count.complete}개 보기`
              : "완료 확인 기준 저장 필요"
          }
          aria-pressed={filter === "complete"}
          onClick={() => onFilter("complete")}
        >
          <span>완료 확인</span>
          <strong>
            {count ? `${count.complete} / ${report?.total}` : "기준 저장 필요"}
          </strong>
          <small>
            {count
              ? `${percentage(count.complete)} · 구현과 수동 검증 확인`
              : "수정한 기준을 저장해 주세요"}
          </small>
        </button>
        <button
          className="progress-stat"
          disabled={!count}
          aria-label={
            count
              ? `구현 확인 ${count.implemented}개 보기`
              : "구현 확인 기준 저장 필요"
          }
          aria-pressed={filter === "implemented"}
          onClick={() => onFilter("implemented")}
        >
          <span>구현 확인</span>
          <strong>
            {count ? `${count.implemented} / ${report?.total}` : "—"}
          </strong>
          <small>
            {count
              ? `${percentage(count.implemented)} · 코드 근거 확인`
              : "코드 근거를 검토해 주세요"}
          </small>
        </button>
        <button
          className="progress-stat"
          disabled={!count}
          aria-label={
            count
              ? `근거 없음·재확인 ${count.unknown}개 보기`
              : "근거 없음·재확인 기준 저장 필요"
          }
          aria-pressed={filter === "unknown"}
          onClick={() => onFilter("unknown")}
        >
          <span>근거 없음·재확인</span>
          <strong>{count ? `${count.unknown}개` : "—"}</strong>
          <small>근거 입력 또는 변경 사항 재확인</small>
        </button>
      </section>
      {allUnknown && (
        <div className="progress-guidance" role="status">
          <strong>
            {noEvidence
              ? "아직 코드 근거가 연결되지 않았습니다."
              : "현재 목표의 근거를 다시 확인해 주세요."}
          </strong>
          <p>
            {noEvidence
              ? "이 수치는 실제 개발률이 아닙니다. 첫 기능의 코드를 연결하고 조건을 충족하는지 검토한 뒤 저장하세요."
              : "기준이나 코드 변경으로 이전 확인을 사용할 수 없습니다. 기능별 출처와 근거를 점검하세요."}
          </p>
          <button
            className="secondary"
            onClick={() => {
              onFilter("unknown");
              if (noEvidence) onStartEvidence();
            }}
          >
            {noEvidence ? "첫 기능의 코드 근거 연결" : "재확인할 기능 보기"}
          </button>
        </div>
      )}
      {count && report && report.total > 0 && !allUnknown && (
        <div
          className="progress-segments"
          role="img"
          aria-label={`구현 확인 ${count.implemented}개, 부분 구현 ${count.partial}개, 미구현 확인 ${count.not_implemented}개, 근거 없음·재확인 ${count.unknown}개, 총 ${report.total}개`}
        >
          {(
            ["implemented", "partial", "not_implemented", "unknown"] as const
          ).map(
            (key) =>
              count[key] > 0 && (
                <div
                  key={key}
                  className={`progress-segment ${key}`}
                  style={{ width: `${(count[key] / report.total) * 100}%` }}
                  title={`${key === "unknown" ? "근거 없음·재확인" : statusText[key]} ${count[key]}개`}
                />
              ),
          )}
        </div>
      )}
      {count && (
        <p className="progress-legend">
          현재 목표 기준 · 구현 확인 {count.implemented} · 부분 구현{" "}
          {count.partial} · 미구현 확인 {count.not_implemented} · 근거
          없음·재확인 {count.unknown} · 제외 {count.excluded} · 요약 카드를 눌러
          목록을 좁힐 수 있습니다.
        </p>
      )}
      {report?.total === 0 && (
        <p className="notice" role="status">
          집계할 현재 목표가 없습니다. 기준 문서에서 현재 목표를 선택하고 기능
          후보를 확인해 주세요.
        </p>
      )}
      {!!report?.stale_context_documents?.length && (
        <p className="hint" role="status">
          참고 범위 문서 변경: {report.stale_context_documents.join(", ")}. 현재
          목표 수치는 유지됩니다.
        </p>
      )}
      {!!report?.stale_documents.length && (
        <div className="notice error" role="alert">
          기준 문서가 변경됐습니다: {report.stale_documents.join(", ")}. 기능
          후보를 다시 추출하고 확정해 주세요. 이전 확인은 현황 집계에서
          제외했습니다.
        </div>
      )}
      {!!report?.doc_claims_unbacked && (
        <div className="notice" role="status">
          문서에는 완료로 표시했지만 코드 근거가 확인되지 않은 항목이{" "}
          {report.doc_claims_unbacked}개 있습니다. 체크 표시는 구현 근거로 쓰지
          않습니다.{" "}
          <button className="text-button" onClick={() => onFilter("claims")}>
            해당 항목 보기
          </button>
        </div>
      )}
    </>
  );
}
