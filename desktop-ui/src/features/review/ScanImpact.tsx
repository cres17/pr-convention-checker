import { ChartNoAxesCombined } from "lucide-react";
import type { ScanImpact as Impact } from "../../bridge";

const changeText: Record<string, string> = { modified: "수정", added: "추가", deleted: "삭제", renamed: "이름 변경" };

/** Links a review scan to the saved project progress: changed files that were recorded as evidence. */
export default function ScanImpact({ impact, onOpen }: { impact: Impact; onOpen: (id: string) => void }) {
  const voided = impact.items.filter((item) => item.invalidated).length;
  return (
    <section className="card scan-impact" aria-label="프로젝트 현황 영향">
      <div className="section-heading">
        <h2>프로젝트 현황에 미치는 영향</h2>
        <button className="secondary" onClick={() => onOpen("")}><ChartNoAxesCombined size={14} /> 프로젝트 현황 열기</button>
      </div>
      {impact.items.length > 0 && (
        <p className="hint">
          이번 변경에 포함된 파일이 저장한 코드 근거로 쓰이고 있습니다.
          {voided > 0 ? ` ${voided}개 기능은 저장된 근거와 현재 코드가 달라 현황에서 재확인 필요로 집계됩니다.` : " 모두 저장된 근거와 내용이 같습니다."}
        </p>
      )}
      <ul className="impact-list">
        {impact.items.map((item) => (
          <li key={item.id}>
            <span className={`badge ${item.invalidated ? "fail" : "pass"}`}>{item.invalidated ? "근거 무효" : "근거와 동일"}</span>
            <strong>{item.title}</strong>
            <code>{item.path}{item.line ? `:${item.line}` : ""}</code>
            <small>{changeText[item.change] ?? item.change}</small>
            <button className="text-button" onClick={() => onOpen(item.id)}>현황에서 보기</button>
          </li>
        ))}
        {impact.documents.map((doc) => (
          <li key={doc.path}>
            <span className={`badge ${doc.invalidated ? "fail" : "pass"}`}>{doc.invalidated ? "기준 문서 변경" : "기준 문서 동일"}</span>
            <code>{doc.path}</code>
            <small>{doc.invalidated ? "기준 문서가 바뀌어 현황 전체를 다시 확정해야 합니다." : "저장된 기준과 내용이 같습니다."}</small>
          </li>
        ))}
      </ul>
    </section>
  );
}
