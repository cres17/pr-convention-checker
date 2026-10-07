import type { Decision, Scan, Violation } from "../../bridge";

export function findViolation(scan: Scan | null, decision: Decision | undefined): Violation | undefined {
  return decision ? scan?.result.violations?.find((v) => v.rule_id === decision.rule_id) : undefined;
}

/** Problem sentence for the list: the policy's own message when the rule has one. */
export function problemTitle(decision: Decision, violation?: Violation): string {
  return violation?.message?.trim() || decision.rule_id;
}

/** Replaces the engine's English default reason with what is actually missing. */
export function problemSummary(decision: Decision): string {
  const groups = decision.unsatisfied_groups;
  const unknown = groups.filter((g) => g.decision === "undetermined");
  if (decision.status === "undetermined") return `내용을 확인하지 못해 판단을 보류했습니다: ${unknown.map((g) => g.name).join(", ")}`;
  if ((decision.status === "fail" || decision.status === "rejected-ignore") && groups.length) {
    if (unknown.length) return `확인된 미충족 조건 ${groups.length - unknown.length}개 · 판단 보류 ${unknown.length}개: ${groups.map((g) => g.name).join(", ")}`;
    return `이번 변경에서 반영되지 않은 문서 조건 ${groups.length}개: ${groups.map((g) => g.name).join(", ")}`;
  }
  return decision.reason || "상세 근거를 확인하세요.";
}

const confidenceText: Record<string, string> = { high: "경로 매칭 구체성 높음", medium: "경로 매칭 구체성 보통", low: "경로 매칭 구체성 낮음" };
export const confidenceLabel = (value?: string) => (value ? confidenceText[value] ?? value : "");

/** Concrete files only; globs cannot be opened. */
export const openablePaths = (required: string[] = []) => required.filter((r) => !/[*?[]/.test(r));
