import type { ProgressItem, ProgressReport } from "../../bridge";
import { statusText } from "./presentation";
import { displayStatus, type ProgressFilter } from "./status";

type Props = {
  report: ProgressReport | null;
  currentItems: ProgressItem[];
  filter: ProgressFilter;
  onFilter: (value: ProgressFilter) => void;
  onStartEvidence: () => void;
};
function SummaryCard({ label, value, total, filter, selectedFilter, onFilter, caption, placeholder = "—" }: {
  label: string;
  value: number | null;
  total?: number;
  filter: ProgressFilter;
  selectedFilter: ProgressFilter;
  onFilter: (value: ProgressFilter) => void;
  caption: string;
  placeholder?: string;
}) {
  const selected = selectedFilter === filter;
  return (
    <button
      className="progress-stat"
      disabled={value === null}
      aria-label={value === null ? `${label} 기준 저장 필요` : `${label} ${value}개 보기`}
      aria-pressed={selected}
      onClick={() => onFilter(selected ? "all" : filter)}
    >
      <span>{label}</span>
      <strong>{value === null ? placeholder : total === undefined ? `${value}개` : `${value} / ${total}`}</strong>
      <small>{caption}</small>
    </button>
  );
}

export default function ProgressOverview({
  report,
  currentItems,
  filter,
  onFilter,
  onStartEvidence,
}: Props) {
  const count = report?.counts;
  const allUnknown = !!report?.total && count?.unknown === report.total;
  const statuses = report?.total
    ? currentItems.map((item) => displayStatus(item, report))
    : [];
  const unknown = statuses.filter((status) => status === "unknown").length;
  const recheck = statuses.filter((status) => status === "recheck").length;
  const noEvidence = allUnknown && recheck === 0;
  const mixedUnknown = unknown > 0 && recheck > 0;
  const segments = count
    ? {
        implemented: count.implemented,
        partial: count.partial,
        not_implemented: count.not_implemented,
        unknown,
        recheck,
      }
    : null;
  const percentage = (value: number) =>
    report?.total
      ? `${Math.round((value / report.total) * 100)}%`
      : "대상 없음";
  return (
    <>
      <section className="progress-overview" aria-label="구현 현황 요약">
        <SummaryCard
          label="완료 확인" filter="complete" selectedFilter={filter} onFilter={onFilter}
          value={count?.complete ?? null} total={report?.total} placeholder="기준 저장 필요"
          caption={count ? `${percentage(count.complete)} · 구현과 수동 검증 확인` : "수정한 기준을 저장해 주세요"}
        />
        <SummaryCard
          label="구현 확인" filter="implemented" selectedFilter={filter} onFilter={onFilter}
          value={count?.implemented ?? null} total={report?.total}
          caption={count ? `${percentage(count.implemented)} · 코드 근거 확인` : "코드 근거를 검토해 주세요"}
        />
        <SummaryCard
          label="근거 없음" filter="unknown" selectedFilter={filter} onFilter={onFilter}
          value={count ? unknown : null} caption="아직 확인된 근거가 없는 기능"
        />
        <SummaryCard
          label="재확인 필요" filter="recheck" selectedFilter={filter} onFilter={onFilter}
          value={count ? recheck : null} caption="문서·코드 변경으로 이전 확인이 오래된 기능"
        />
      </section>
      {allUnknown && (
        <div className="progress-guidance" role="status">
          <strong>
            {noEvidence
              ? "아직 코드 근거가 연결되지 않았습니다."
              : mixedUnknown
                ? "근거가 없는 기능과 재확인할 기능이 있습니다."
                : "현재 목표의 근거를 다시 확인해 주세요."}
          </strong>
          <p>
            {noEvidence
              ? "이 수치는 실제 개발률이 아닙니다. 첫 기능의 코드를 연결하고 조건을 충족하는지 검토한 뒤 저장하세요."
              : "이 수치는 실제 개발률이 아닙니다. 근거가 없는 기능은 코드를 연결하고, 재확인할 기능은 변경된 출처와 근거를 점검하세요."}
          </p>
          <button
            className="secondary"
            onClick={() => {
              onFilter(noEvidence ? "unknown" : "recheck");
              if (noEvidence) onStartEvidence();
            }}
          >
            {noEvidence ? "첫 기능의 코드 근거 연결" : "재확인할 기능 보기"}
          </button>
          {mixedUnknown && (
            <button className="secondary" onClick={() => onFilter("unknown")}>
              근거 없는 기능 보기
            </button>
          )}
        </div>
      )}
      {segments && report && report.total > 0 && !allUnknown && (
        <div
          className="progress-segments"
          role="img"
          aria-label={`구현 확인 ${segments.implemented}개, 부분 구현 ${segments.partial}개, 미구현 확인 ${segments.not_implemented}개, 근거 없음 ${unknown}개, 재확인 필요 ${recheck}개, 총 ${report.total}개`}
        >
          {(
            ["implemented", "partial", "not_implemented", "unknown", "recheck"] as const
          ).map(
            (key) =>
              segments[key] > 0 && (
                <div
                  key={key}
                  className={`progress-segment ${key}`}
                  style={{ width: `${(segments[key] / report.total) * 100}%` }}
                  title={`${statusText[key]} ${segments[key]}개`}
                />
              ),
          )}
        </div>
      )}
      {count && (
        <p className="progress-legend">
          현재 목표 기준 · 구현 확인 {count.implemented} · 부분 구현{" "}
          {count.partial} · 미구현 확인 {count.not_implemented} · 근거 없음{" "}
          {unknown} · 재확인 필요 {recheck} · 제외 {count.excluded} · 요약 카드를 눌러
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
