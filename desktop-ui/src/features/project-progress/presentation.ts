import type {
  DocumentKind, ProgressBaseline, ProgressItem, ProgressReport,
} from "../../bridge";
import {
  effectiveStatus, inCurrentScope, isStaleEvidence, isStaleRequirement,
  type DisplayStatus,
} from "./status";

export const statusText: Record<DisplayStatus, string> =
  {
    unknown: "근거 없음",
    recheck: "재확인 필요",
    partial: "부분 구현",
    implemented: "구현 확인",
    not_implemented: "미구현 확인",
  };
export const documentKindText: Record<DocumentKind, string> = {
  current: "현재 목표",
  future: "향후 계획",
  past: "과거 결과",
  reference: "참고",
};
export function nextAction(
  item: ProgressItem,
  report: ProgressReport | null,
  baseline: ProgressBaseline,
): string {
  if (!inCurrentScope(item, baseline))
    return "현재 목표 집계에서 제외 (기존 근거 유지)";
  if (
    report?.stale_documents.length || isStaleRequirement(item, baseline, report)
  )
    return "변경된 기준 문서 다시 확인";
  if (isStaleEvidence(item, report)) return "변경된 코드를 다시 확인";
  const status = effectiveStatus(item, report);
  if (status === "unknown") return "코드 근거 확인";
  if (status === "partial") return "남은 완료 조건 구현";
  if (status === "not_implemented") return "기능 구현";
  if (item.verification_status !== "verified") return "동작 검증 기록";
  return "완료 확인";
}

export function testSummary(link: {
  matched: number;
  passed: number;
  failed: number;
  skipped: number;
  no_match: boolean;
}): string {
  if (link.no_match) return "일치하는 테스트 없음";
  return [
    `통과 ${link.passed}`,
    link.failed ? `실패 ${link.failed}` : "",
    link.skipped ? `건너뜀 ${link.skipped}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}
