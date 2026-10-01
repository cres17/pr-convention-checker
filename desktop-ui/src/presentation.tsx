export const statusLabels: Record<string, string> = {
    pass: "통과",
    fail: "수정 필요",
    warn: "주의",
    skipped: "제외",
    unmatched: "대상 아님",
    "rejected-ignore": "예외 거절",
    uncertain: "판단 유보",
};
export function Badge({ value }: {
    value: string;
}) {
    return <span className={`badge ${value}`}>{statusLabels[value] ?? value}</span>;
}
export function projectName(path: string) {
    return path.split(/[\\/]/).filter(Boolean).at(-1) || "프로젝트 연결";
}
