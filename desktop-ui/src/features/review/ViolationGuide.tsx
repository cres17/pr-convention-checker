import { useState } from "react";
import { Check, Copy, FilePen, RefreshCw } from "lucide-react";
import type { Decision, Violation } from "../../bridge";
import { confidenceLabel, openablePaths } from "./violations";

/** Shows what the engine already computed: what changed, why it matters and how to fix it. */
export default function ViolationGuide({ decision, violation, onOpen, onRescan }: {
  decision: Decision;
  violation?: Violation;
  onOpen?: (relative: string) => void;
  onRescan?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const draft = violation?.docs_update_draft?.trim();
  const docs = [...new Set(decision.unsatisfied_groups.flatMap((g) => openablePaths(g.required)))];
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(draft ?? "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
  if (!violation && !docs.length) return null;
  return (
    <section className="fix-guide" aria-label="고치는 방법">
      {violation?.confidence && <span className="confidence">{confidenceLabel(violation.confidence)}</span>}
      {violation?.changed_contract_summary && <><h3>바뀐 계약</h3><p>{violation.changed_contract_summary}</p></>}
      {violation?.missing_docs_explanation && <><h3>왜 문제인가</h3><p>{violation.missing_docs_explanation}</p></>}
      {!!violation?.checklist?.length && <><h3>고치는 방법</h3>
        <ul className="fix-checklist">{violation.checklist.map((item) => <li key={item}>{item}</li>)}</ul></>}
      {draft && <><h3>문서 초안</h3><pre className="fix-draft">{draft}</pre>
        <button className="secondary" onClick={copy}>{copied ? <Check size={14} /> : <Copy size={14} />} {copied ? "복사했습니다" : "초안 복사"}</button></>}
      {(onOpen && docs.length > 0) || onRescan ? <div className="fix-actions">
        {onOpen && docs.map((doc) => <button key={doc} className="secondary" onClick={() => onOpen(doc)}><FilePen size={14} /> {doc} 열기</button>)}
        {onRescan && <button className="secondary" onClick={onRescan}><RefreshCw size={14} /> 문서 수정 후 다시 검사</button>}
      </div> : null}
      {violation?.false_positive_note && <p className="hint">{violation.false_positive_note}</p>}
    </section>
  );
}
