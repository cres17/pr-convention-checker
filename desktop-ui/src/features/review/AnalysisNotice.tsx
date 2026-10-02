import type { Scan } from "../../bridge";

function explanation(reason = "") {
  if (reason.startsWith("Tree-sitter unavailable") || reason.startsWith("Grammar unavailable"))
    return "문법 분석기를 사용할 수 없어 코드 변경의 텍스트 패턴으로 분석했습니다. 설치 파일을 다시 확인해 주세요.";
  if (reason.startsWith("Partial or invalid")) return "변경된 코드 조각을 문법으로 완전히 읽을 수 없어 텍스트 패턴도 함께 사용했습니다.";
  if (reason.startsWith("Patch unavailable")) return "변경 내용을 읽지 못해 경로 정보로 판단했습니다.";
  return "문법 분석을 지원하지 않거나 분석할 코드가 없어 텍스트 패턴으로 판단했습니다.";
}

export default function AnalysisNotice({ scan }: { scan: Scan }) {
  const notes = scan.result.scan_metrics?.analysis_notes ?? [];
  const limited = notes.filter((note) => note.method !== "grammar+heuristic");
  if (!limited.length) return null;
  return <div className="notice" role="status">
    <div>
      <strong>문법 분석을 적용하지 못한 파일 {limited.length}개</strong>
      <p>이 파일은 텍스트 패턴 또는 경로 정보로 검사했습니다. 규칙 판정과 함께 분석 범위를 확인해 주세요.</p>
      <details><summary>파일별 분석 방식 보기</summary>
        <ul>{limited.map((note) => <li key={note.path}><code>{note.path}</code> · {explanation(note.reason)}</li>)}</ul>
      </details>
    </div>
  </div>;
}
