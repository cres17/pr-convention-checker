import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, BookOpen, Check, ChevronRight, FileSearch, Plus, RefreshCw } from "lucide-react";
import type { Bridge, LinkReport, ProgressBaseline, ProgressFieldError, ProgressItem, ProgressReport } from "../../bridge";
import { docClaimUnbacked, effectiveStatus, isStaleEvidence } from "./status";

type Document = { path: string; tracked: boolean; bytes: number };
type Event = { type: string; [key: string]: any };
const statusText: Record<ProgressItem["implementation_status"], string> = {
  unknown: "확인 필요",
  partial: "부분 구현",
  implemented: "구현 확인",
  not_implemented: "미구현 확인",
};
function nextAction(item: ProgressItem, report: ProgressReport | null): string {
  if (!item.included) return "이번 범위에서 제외";
  if (isStaleEvidence(item, report)) return "변경된 코드를 다시 확인";
  const status = effectiveStatus(item, report);
  if (status === "unknown") return "코드 근거 확인";
  if (status === "partial") return "남은 완료 조건 구현";
  if (status === "not_implemented") return "기능 구현";
  if (item.verification_status !== "verified") return "동작 검증 기록";
  return "완료 확인";
}

function FieldMessage({ text }: { text?: string }) {
  return text ? <small className="field-error" role="alert">{text}</small> : null;
}

export default function ProjectProgress({
  path, connected, bridge, events, focus = null,
}: { path: string; connected: boolean; bridge: Bridge | null; events: Event[]; focus?: { id: string; n: number } | null }) {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [selectedDocs, setSelectedDocs] = useState<string[]>([]);
  const [draft, setDraft] = useState<ProgressBaseline | null>(null);
  const [report, setReport] = useState<ProgressReport | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [candidates, setCandidates] = useState<{ path: string; line: number; excerpt: string }[]>([]);
  const [omitted, setOmitted] = useState(0);
  const [showDocuments, setShowDocuments] = useState(true);
  const [fieldErrors, setFieldErrors] = useState<ProgressFieldError[]>([]);
  const [focusField, setFocusField] = useState("");
  const [links, setLinks] = useState<LinkReport | null>(null);
  const [exported, setExported] = useState("");

  useEffect(() => {
    setDocuments([]);
    setSelectedDocs([]);
    setDraft(null);
    setReport(null);
    setSelectedId("");
    setCandidates([]);
    setFieldErrors([]);
    setLinks(null);
    setExported("");
    setShowDocuments(true);
    if (connected && path && bridge) {
      setBusy("documents");
      bridge.listProjectDocs(path);
    }
  }, [path, connected, bridge]);

  // Events from before this screen mounted are history, not input.
  // Select the item another screen pointed at, once per request.
  const handledFocus = useRef(0);
  useEffect(() => {
    if (!focus || !focus.id || focus.n === handledFocus.current) return;
    if (!draft?.requirements.some((entry) => entry.id === focus.id)) return;
    handledFocus.current = focus.n;
    setFilter("all");
    setQuery("");
    setSelectedId(focus.id);
  }, [focus, draft]);
  const handledSeq = useRef(events.at(-1)?._seq ?? 0);
  useEffect(() => {
    for (const event of events) {
      if (event._seq <= handledSeq.current) continue;
      handledSeq.current = event._seq;
      handle(event);
    }
  }, [events]);

  const handle = (event: Event) => {
    if (event.requested_path && event.requested_path !== path) return;
    switch (event.type) {
      case "progressDocs":
        setBusy("");
        setDocuments(event.documents);
        setOmitted(event.omitted);
        if (event.baseline) {
          setDraft(event.baseline);
          setSelectedDocs(Object.keys(event.baseline.documents));
          setSelectedId(event.baseline.requirements[0]?.id ?? "");
          setShowDocuments(false);
          bridge?.inspectProgress(path);
        } else {
          const suggested = event.documents.find((doc: Document) => doc.path.toLowerCase() === "readme.md");
          setSelectedDocs(suggested ? [suggested.path] : []);
        }
        break;
      case "progressPreview":
        setBusy("");
        setDraft({ repository: path, documents: event.documents, requirements: event.requirements });
        setReport(null);
        setSelectedId(event.requirements[0]?.id ?? "");
        setCandidates([]);
        break;
      case "progressSaved":
        setBusy("");
        setFieldErrors([]);
        setDraft(event.baseline);
        setShowDocuments(false);
        break;
      case "progressReport":
        setBusy("");
        setReport(event.report);
        break;
      case "progressLinks":
        setBusy("");
        setLinks(event as unknown as LinkReport);
        break;
      case "progressExported":
        setBusy("");
        setExported(`저장했습니다 · ${event.file}`);
        break;
      case "progressEvidence":
        if (event.id === selectedId) setCandidates(event.candidates);
        break;
      case "progressError":
        setBusy("");
        setFieldErrors(Array.isArray(event.errors) ? event.errors : []);
        setError(Array.isArray(event.errors) && event.errors.length ? "" : event.message);
        break;
    }
  };

  const edit = (id: string, patch: Partial<ProgressItem>) => {
    setReport(null);
    setFieldErrors((old) => old.filter((entry) => entry.id !== id
      || !Object.keys(patch).some((key) => entry.field === key || entry.field.startsWith(`${key}.`))));
    setDraft((old) => old && ({ ...old, requirements: old.requirements.map((item) =>
      item.id === id ? { ...item, ...patch,
        ...(patch.criterion !== undefined && patch.criterion !== item.criterion
          ? { implementation_status: "unknown" as const, evidence: null } : {}),
        ...(patch.evidence !== undefined || (patch.criterion !== undefined && patch.criterion !== item.criterion)
          ? { verification_status: "unverified" as const, verification_note: "" } : {}) } : item) }));
  };
  const item = draft?.requirements.find((value) => value.id === selectedId);
  const errorsOf = (id: string) => fieldErrors.filter((entry) => entry.id === id);
  const invalidItems = draft?.requirements.filter((entry) => errorsOf(entry.id).length) ?? [];
  const fieldError = (field: string) => fieldErrors.find((entry) => entry.id === item?.id && entry.field === field)?.message;
  const mark = (field: string) => ({ "data-field": field, "aria-invalid": fieldError(field) ? true : undefined });
  const goToFirstError = () => {
    const first = invalidItems[0];
    if (!first) return;
    setFilter(first.included ? "all" : "excluded");
    setQuery("");
    setSelectedId(first.id);
    setCandidates([]);
    setFocusField(errorsOf(first.id)[0].field);
  };
  useEffect(() => {
    if (!focusField) return;
    document.querySelector<HTMLElement>(`[data-field="${focusField}"]`)?.focus();
    setFocusField("");
  }, [focusField, selectedId]);
  const visible = useMemo(() => (draft?.requirements ?? []).filter((entry) => {
    if (filter === "remaining" && entry.included && effectiveStatus(entry, report) === "implemented" && entry.verification_status === "verified") return false;
    if (filter === "unknown" && effectiveStatus(entry, report) !== "unknown") return false;
    if (filter === "claims" && !docClaimUnbacked(entry, report)) return false;
    if (filter === "excluded" && entry.included) return false;
    if (filter !== "excluded" && !entry.included) return false;
    return `${entry.title} ${entry.area} ${entry.criterion}`.toLowerCase().includes(query.toLowerCase());
  }), [draft, report, filter, query]);
  const count = report?.counts;
  const percentage = (value: number) => report?.total ? `${Math.round(value / report.total * 100)}%` : "대상 없음";
  const extract = () => {
    if (!selectedDocs.length) return;
    setBusy("extract"); setError("");
    bridge?.previewProgress(path, JSON.stringify(selectedDocs));
  };
  const save = () => {
    if (!draft) return;
    setBusy("save"); setError(""); setFieldErrors([]); setLinks(null); setExported("");
    bridge?.saveProgress(path, JSON.stringify(draft));
  };
  const addManual = () => {
    if (!draft) return;
    const sourcePath = Object.keys(draft.documents)[0];
    if (!sourcePath) return;
    const id = crypto.randomUUID();
    const newItem: ProgressItem = {
      id, title: "새 기능", criterion: "완료 조건을 입력하세요", area: "직접 추가", included: true,
      source: { path: sourcePath, line: 0, excerpt: "사용자가 직접 추가", sha256: draft.documents[sourcePath] },
      implementation_status: "unknown", evidence: null,
      verification_status: "unverified", verification_note: "",
    };
    setDraft({ ...draft, requirements: [...draft.requirements, newItem] });
    setReport(null);
    setSelectedId(id);
  };

  if (!connected) return <section className="card progress-empty"><BookOpen size={28} /><h2>데스크톱 앱에서 프로젝트를 연결해 주세요.</h2><p>브라우저 미리보기에서는 로컬 문서를 읽지 않습니다.</p></section>;
  return <div className="progress-page">
    <section className="card progress-setup">
      <div className="section-heading"><h2><BookOpen size={19} /> 기준 문서</h2><div className="progress-actions">{showDocuments && <button className="secondary" onClick={() => bridge?.listProjectDocs(path)} disabled={!path || !!busy}><RefreshCw size={15} /> 문서 새로고침</button>}{draft && <button className="secondary" onClick={() => setShowDocuments(!showDocuments)}>{showDocuments ? "문서 목록 접기" : "기준 문서 변경"}</button>}</div></div>
      {!showDocuments && <p>{Object.keys(draft?.documents ?? {}).join(", ")} · 요구사항 {draft?.requirements.length ?? 0}개</p>}
      {showDocuments && <><p>이번 버전에 포함할 Markdown을 선택하세요. 체크 표시와 표의 완료 조건, 제목은 기능 후보일 뿐이며, 아래에서 확인한 뒤 기준을 저장합니다.</p>
      {!path ? <div className="empty-inline">왼쪽에서 프로젝트 폴더를 선택해 주세요.</div> : documents.length ? <>
        <div className="progress-doc-list" role="group" aria-label="기준 Markdown 선택">
          {documents.map((doc) => <label key={doc.path} className="progress-doc"><input type="checkbox" checked={selectedDocs.includes(doc.path)} onChange={(e) => setSelectedDocs((old) => e.target.checked ? [...old, doc.path] : old.filter((value) => value !== doc.path))} /><span>{doc.path}</span>{!doc.tracked && <small>미추적 파일</small>}</label>)}
        </div>
        {omitted > 0 && <p className="hint">크기 제한·제외 경로·목록 상한으로 {omitted}개 문서를 생략했습니다.</p>}
        <div className="progress-actions"><button className="primary" disabled={!selectedDocs.length || selectedDocs.length > 10 || !!busy} onClick={extract}><FileSearch size={16} /> {busy === "extract" ? "후보 추출 중…" : "기능 후보 추출"}</button><span className="hint">최대 10개 문서 · 기존 기준을 다시 추출하면 편집 전 목록으로 바뀝니다.</span></div>
      </> : <div className="empty-inline">{busy ? "Markdown 목록을 읽는 중…" : "읽을 수 있는 Markdown이 없습니다."}</div>}</>}
    </section>

    {(error || invalidItems.length > 0) && <div className="notice error" role="alert"><AlertCircle size={18} /> {invalidItems.length ? `${invalidItems.length}개 항목을 확인하세요.` : error}{invalidItems.length > 0 && <button className="text-button" onClick={goToFirstError}>첫 항목으로 이동</button>}</div>}
    {draft && <>
      <section className="progress-overview" aria-label="구현 현황 요약">
        <div className="progress-stat"><span>완료 확인</span><strong>{count ? `${count.complete} / ${report?.total}` : "기준 저장 필요"}</strong><small>{count ? `${percentage(count.complete)} · 구현과 수동 검증 확인` : "수정한 기준을 저장해 주세요"}</small></div>
        <div className="progress-stat"><span>구현 확인</span><strong>{count ? `${count.implemented} / ${report?.total}` : "—"}</strong><small>{count ? `${percentage(count.implemented)} · 코드 근거 확인` : "코드 근거를 검토해 주세요"}</small></div>
        <div className="progress-stat"><span>확인 필요</span><strong>{count ? `${count.unknown}개` : "—"}</strong><small>근거 부족·기준 변경 포함</small></div>
      </section>
      {count && report && report.total > 0 && <div className="progress-segments" role="img" aria-label={`구현 확인 ${count.implemented}개, 부분 구현 ${count.partial}개, 미구현 확인 ${count.not_implemented}개, 확인 필요 ${count.unknown}개, 총 ${report.total}개`}>
        {(["implemented", "partial", "not_implemented", "unknown"] as const).map((key) => count[key] > 0 && <div key={key} className={`progress-segment ${key}`} style={{ width: `${count[key] / report.total * 100}%` }} title={`${key}: ${count[key]}개`} />)}
      </div>}
      {count && <p className="progress-legend">구현 확인 {count.implemented} · 부분 구현 {count.partial} · 미구현 확인 {count.not_implemented} · 확인 필요 {count.unknown} · 제외 {count.excluded}</p>}
      {!!report?.stale_documents.length && <div className="notice error" role="alert">기준 문서가 변경됐습니다: {report.stale_documents.join(", ")}. 기능 후보를 다시 추출하고 확정해 주세요. 이전 확인은 현황 집계에서 제외했습니다.</div>}
      {!!report?.doc_claims_unbacked && <div className="notice" role="status">문서에는 완료로 표시했지만 코드 근거가 확인되지 않은 항목이 {report.doc_claims_unbacked}개 있습니다. 체크 표시는 구현 근거로 쓰지 않습니다. <button className="text-button" onClick={() => setFilter("claims")}>해당 항목 보기</button></div>}
      <section className="card progress-workspace">
        <div className="section-heading"><h2>기능별 현황 <span>{draft.requirements.length}</span></h2><div className="progress-actions"><button className="secondary" onClick={addManual} disabled={!!busy}><Plus size={15} /> 직접 추가</button><button className="primary" onClick={save} disabled={!!busy}>{busy === "save" ? "저장 중…" : "기준과 근거 저장"}</button></div></div>
        <div className="progress-actions"><button className="secondary" disabled={!report || !!busy} onClick={() => { setBusy("links"); bridge?.checkProgressLinks(path); }}>{busy === "links" ? "점검 중…" : "문서 링크 점검"}</button><button className="secondary" disabled={!report || !!busy} onClick={() => bridge?.exportProgress(path, "md")}>Markdown 저장</button><button className="secondary" disabled={!report || !!busy} onClick={() => bridge?.exportProgress(path, "json")}>JSON 저장</button>{exported && <span className="hint" role="status">{exported}</span>}</div>
        {links && <div className="progress-links" aria-label="문서 링크 점검 결과">
          <h3>문서 링크 점검 <span>{links.checked}개 확인</span></h3>
          {(() => {
            const sure = links.issues.filter((entry) => entry.confidence !== "low");
            const hints = links.issues.filter((entry) => entry.confidence === "low");
            return <>
              {sure.length ? <ul>{sure.map((entry) => <li key={`${entry.path}:${entry.line}:${entry.target}`}><code>{entry.path}:{entry.line}</code> {entry.target} · {entry.message}</li>)}</ul> : <p className="hint">깨진 링크가 없습니다.</p>}
              {hints.length > 0 && <details><summary>확인이 필요한 파일 경로 {hints.length}개 (예시 경로일 수 있음)</summary><ul>{hints.map((entry) => <li key={`${entry.path}:${entry.line}:${entry.target}`}><code>{entry.path}:{entry.line}</code> {entry.target} · {entry.message}</li>)}</ul></details>}
              <p className="hint">{links.limitations}{links.truncated ? " 결과가 많아 일부만 표시합니다." : ""}</p>
            </>;
          })()}
        </div>}
        <p className="hint">{report ? `요구사항 v${report.version} · 분석 ${new Date(report.at).toLocaleString("ko-KR")} · 코드 ${report.head.slice(0, 8)}` : "변경 사항이 저장되면 현황 수치를 다시 계산합니다."}</p>
        <div className="progress-toolbar"><label>목록 필터 <select value={filter} onChange={(e) => setFilter(e.target.value)}><option value="all">전체</option><option value="remaining">남은 작업</option><option value="unknown">확인 필요</option><option value="claims">문서와 불일치</option><option value="excluded">제외</option></select></label><label>기능 검색 <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="기능명·조건" /></label></div>
        <div className="progress-grid"><div className="progress-list" aria-label="기능 목록">
          {visible.length ? visible.map((entry) => <button key={entry.id} className={`progress-row ${selectedId === entry.id ? "active" : ""}`} onClick={() => { setSelectedId(entry.id); setCandidates([]); }} aria-current={selectedId === entry.id ? "true" : undefined}><span><strong>{errorsOf(entry.id).length > 0 && <AlertCircle size={13} aria-label="확인이 필요한 입력이 있습니다" />} {entry.title}</strong><small>{entry.area || entry.source.path} · 다음: {nextAction(entry, report)}{entry.duplicates?.length ? ` · 다른 문서 ${entry.duplicates.length}곳에도 있음` : ""}{docClaimUnbacked(entry, report) ? " · 문서는 완료 표시, 근거 없음" : ""}</small></span><span className={`progress-status ${effectiveStatus(entry, report)}`}>{isStaleEvidence(entry, report) || (entry.included && report?.stale_documents.length) ? "재확인 필요" : statusText[effectiveStatus(entry, report)]}</span><ChevronRight size={15} /></button>) : <div className="empty-inline">조건에 맞는 기능이 없습니다.</div>}
        </div><div className="progress-detail">
          {item ? <>
            <div className="section-heading"><h3>기능과 완료 조건</h3><label className="progress-include"><input type="checkbox" checked={item.included} onChange={(e) => edit(item.id, { included: e.target.checked })} /> 이번 범위에 포함</label></div>
            <label className="field">기능명<input {...mark("title")} value={item.title} onChange={(e) => edit(item.id, { title: e.target.value })} maxLength={500} /><FieldMessage text={fieldError("title")} /></label>
            <label className="field">완료 조건<textarea {...mark("criterion")} value={item.criterion} onChange={(e) => edit(item.id, { criterion: e.target.value })} rows={3} maxLength={500} /><FieldMessage text={fieldError("criterion")} /></label>
            <p className="progress-source"><strong>문서 출처</strong> {item.source.path}{item.source.line ? `:${item.source.line}` : " · 직접 추가"}<br /><span>{item.source.excerpt}</span>{item.duplicates?.map((place) => <span key={`${place.path}:${place.line}`} className="progress-duplicate"><br />같은 항목: {place.path}:{place.line} · {place.excerpt}</span>)}<FieldMessage text={fieldError("source")} /></p>
            {docClaimUnbacked(item, report) && <p className="notice" role="status">이 항목은 문서에서 완료(<code>[x]</code>)로 표시됐지만 현재 확인된 코드 근거가 없습니다.</p>}
            <p className="progress-next"><strong>다음 할 일</strong> {report?.stale_documents.length ? "변경된 기준 문서 다시 확인" : nextAction(item, report)}</p>
            <label className="field">구현 상태<select {...mark("implementation_status")} value={item.implementation_status} onChange={(e) => edit(item.id, { implementation_status: e.target.value as ProgressItem["implementation_status"], verification_status: "unverified" })}><option value="unknown">확인 필요</option><option value="partial">부분 구현</option><option value="implemented">구현 확인</option><option value="not_implemented">미구현 확인</option></select><FieldMessage text={fieldError("implementation_status")} /></label>
            {item.implementation_status !== "not_implemented" && <div className="progress-evidence"><div className="section-heading"><h3>코드 근거</h3><button className="text-button" onClick={() => bridge?.suggestProgressEvidence(path, JSON.stringify(item))}>문서에 명시된 파일 찾기</button></div><p className="hint">후보는 파일 존재만 확인합니다. 완료 조건과의 연결은 직접 검토해 주세요. 근거를 저장하려면 구현 상태를 선택하세요.</p>{candidates.map((candidate) => <button key={candidate.path} className="progress-candidate" onClick={() => edit(item.id, { evidence: { path: candidate.path, line: candidate.line, note: item.evidence?.note ?? "" } })}>{candidate.path}:{candidate.line} · {candidate.excerpt}</button>)}<div className="progress-evidence-input"><label className="field">코드 파일 경로<input {...mark("evidence.path")} value={item.evidence?.path ?? ""} onChange={(e) => edit(item.id, { evidence: { path: e.target.value, line: item.evidence?.line ?? 1, note: item.evidence?.note ?? "" } })} placeholder="src/login.py" /><FieldMessage text={fieldError("evidence.path")} /></label><label className="field">줄 번호<input {...mark("evidence.line")} type="number" min={1} value={item.evidence?.line ?? 1} onChange={(e) => edit(item.id, { evidence: { path: item.evidence?.path ?? "", line: Number(e.target.value), note: item.evidence?.note ?? "" } })} /><FieldMessage text={fieldError("evidence.line")} /></label></div><label className="field">이 코드가 조건을 충족하는 이유<textarea {...mark("evidence.note")} rows={2} value={item.evidence?.note ?? ""} onChange={(e) => edit(item.id, { evidence: { path: item.evidence?.path ?? "", line: item.evidence?.line ?? 1, note: e.target.value } })} /><FieldMessage text={fieldError("evidence.note")} /></label>{item.evidence?.excerpt && <code className="progress-code">{item.evidence.excerpt}</code>}{isStaleEvidence(item, report) && <p className="notice error">코드가 바뀌었습니다. 근거를 다시 확인해 저장하세요.</p>}</div>}
            {item.implementation_status === "not_implemented" && <label className="field">미구현을 확인한 이유<textarea {...mark("implementation_note")} rows={2} value={item.implementation_note ?? ""} onChange={(e) => edit(item.id, { implementation_note: e.target.value })} /><FieldMessage text={fieldError("implementation_note")} /></label>}
            <label className="field">검증 상태<select {...mark("verification_status")} value={item.verification_status} disabled={item.implementation_status !== "implemented"} onChange={(e) => edit(item.id, { verification_status: e.target.value as ProgressItem["verification_status"] })}><option value="unverified">미검증</option><option value="verified">수동 확인</option></select><FieldMessage text={fieldError("verification_status")} /></label>
            {item.verification_status === "verified" && <label className="field">검증 기록<textarea {...mark("verification_note")} rows={2} value={item.verification_note} onChange={(e) => edit(item.id, { verification_note: e.target.value })} placeholder="검증 방법·대상·결과를 적어 주세요" /><FieldMessage text={fieldError("verification_note")} /></label>}
            <p className="hint">수동 확인은 검증 기록을 남긴 경우에만 완료로 집계합니다. 자동 테스트 실행·CI 연결은 후속 단계입니다.</p>
          </> : <div className="empty-inline">기능을 선택하면 출처와 근거를 확인할 수 있습니다.</div>}
        </div></div>
      </section>
      <p className="hint">{report?.limitations ?? "분석 전에 기준을 저장해 주세요."}</p>
    </>}
  </div>;
}
