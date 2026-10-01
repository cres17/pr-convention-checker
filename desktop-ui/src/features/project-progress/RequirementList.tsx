import { AlertCircle, ChevronRight } from "lucide-react";
import type { ProgressBaseline, ProgressFieldError, ProgressItem, ProgressReport, TestLinks } from "../../bridge";
import { nextAction, statusText, testSummary } from "./presentation";
import { docClaimUnbacked, displayStatus, inCurrentScope } from "./status";
export default function RequirementList({ visible, draft, report, tests, selectedId, errors, onSelect }: {
  visible: ProgressItem[]; draft: ProgressBaseline; report: ProgressReport | null;
  tests: TestLinks | null; selectedId: string; errors: ProgressFieldError[]; onSelect: (id: string) => void;
}) {
  return (
    <div className="progress-list" aria-label="기능 목록">
      {visible.length ? (
        visible.map((entry) => {
          const included = inCurrentScope(entry, draft);
          const status = included ? displayStatus(entry, report) : "excluded";
          const test = included ? tests?.items[entry.id] : undefined;
          return (
          <button
            key={entry.id}
            className={`progress-row ${selectedId === entry.id ? "active" : ""}`}
            onClick={() => onSelect(entry.id)}
            aria-current={
              selectedId === entry.id ? "true" : undefined
            }
          >
            <span>
              <strong>
                {errors.some((error) => error.id === entry.id) && (
                  <AlertCircle
                    size={13}
                    aria-label="확인이 필요한 입력이 있습니다"
                  />
                )}{" "}
                {entry.title}
              </strong>
              <small>
                {entry.area || entry.source.path} · 다음:{" "}
                {nextAction(entry, report, draft)}
                {entry.duplicates?.length
                  ? ` · 다른 문서 ${entry.duplicates.length}곳에도 있음`
                  : ""}
                {docClaimUnbacked(entry, report)
                  ? " · 문서는 완료 표시, 근거 없음"
                  : ""}
                {test
                  ? ` · 자동 검증: ${testSummary(test)}${test.code_newer ? " (결과가 코드보다 오래됨)" : ""}`
                  : ""}
              </small>
            </span>
            <span
              className={`progress-status ${status}`}
            >
              {status === "excluded" ? "제외" : statusText[status]}
            </span>
            <ChevronRight size={15} />
          </button>
          );
        })
      ) : (
        <div className="empty-inline">
          조건에 맞는 기능이 없습니다.
        </div>
      )}
    </div>
  );
}
