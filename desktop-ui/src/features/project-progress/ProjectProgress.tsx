import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, BookOpen, ChevronRight, FileSearch, Plus, RefreshCw } from "lucide-react";
import type { Bridge, DocumentKind, LinkReport, ProgressHistory, TestLinks, ProgressBaseline, ProgressFieldError, ProgressItem, ProgressReport } from "../../bridge";
import History from "./History";
import { docClaimUnbacked, effectiveStatus, inCurrentScope, isStaleEvidence } from "./status";

type Document = { path: string; tracked: boolean; bytes: number };
type Event = { type: string; [key: string]: any };
const statusText: Record<ProgressItem["implementation_status"], string> = {
  unknown: "근거 없음",
  partial: "부분 구현",
  implemented: "구현 확인",
  not_implemented: "미구현 확인",
};
const documentKindText: Record<DocumentKind, string> = {
  current: "현재 목표", future: "향후 계획", past: "과거 결과", reference: "참고",
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

function testSummary(link: { matched: number; passed: number; failed: number; skipped: number; no_match: boolean }): string {
  if (link.no_match) return "일치하는 테스트 없음";
  return [`통과 ${link.passed}`, link.failed ? `실패 ${link.failed}` : "", link.skipped ? `건너뜀 ${link.skipped}` : ""].filter(Boolean).join(" · ");
}

function FieldMessage({ text }: { text?: string }) {
  return text ? <small className="field-error" role="alert">{text}</small> : null;
}

export default function ProjectProgress({
  path, connected, bridge, events, focus = null,
}: { path: string; connected: boolean; bridge: Bridge | null; events: Event[]; focus?: { id: string; n: number } | null }) {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [selectedDocs, setSelectedDocs] = useState<string[]>([]);
  const [documentKinds, setDocumentKinds] = useState<Record<string, DocumentKind>>({});
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
  const [history, setHistory] = useState<ProgressHistory | null>(null);
  const [tests, setTests] = useState<TestLinks | null>(null);
  const [exported, setExported] = useState("");

  useEffect(() => {
    setDocuments([]);
    setSelectedDocs([]);
    setDocumentKinds({});
    setFilter("all");
    setQuery("");
    setDraft(null);
    setReport(null);
    setSelectedId("");
    setCandidates([]);
    setFieldErrors([]);
    setLinks(null);
    setHistory(null);
    setTests(null);
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
    const focusedItem = draft?.requirements.find((entry) => entry.id === focus.id);
    if (!draft || !focusedItem) return;
    handledFocus.current = focus.n;
    setFilter(inCurrentScope(focusedItem, draft) ? "all" : "excluded");
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
          setDocumentKinds(event.baseline.document_kinds ?? {});
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
        setDraft({ repository: path, documents: event.documents, document_kinds: event.document_kinds, requirements: event.requirements });
        setDocumentKinds(event.document_kinds ?? {});
        setFilter("all");
        setQuery("");
        setReport(null);
        setSelectedId(event.requirements[0]?.id ?? "");
        setCandidates([]);
        break;
      case "progressSaved":
        setBusy("");
        setFieldErrors([]);
        setDraft(event.baseline);
        setSelectedDocs(Object.keys(event.baseline.documents));
        setDocumentKinds(event.baseline.document_kinds ?? {});
        setShowDocuments(false);
        break;
      case "progressReport":
        setBusy("");
        setReport(event.report);
        break;
      case "progressTests":
        setBusy("");
        setTests(event as unknown as TestLinks);
        break;
      case "progressHistory":
        setHistory({ snapshots: event.snapshots, since_save: event.since_save } as ProgressHistory);
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
    setFilter(draft && inCurrentScope(first, draft) ? "all" : "excluded");
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
    const included = draft ? inCurrentScope(entry, draft) : false;
    if (filter === "complete" && !(effectiveStatus(entry, report) === "implemented" && entry.verification_status === "verified")) return false;
    if (filter === "implemented" && effectiveStatus(entry, report) !== "implemented") return false;
    if (filter === "remaining" && entry.included && effectiveStatus(entry, report) === "implemented" && entry.verification_status === "verified") return false;
    if (filter === "unknown" && effectiveStatus(entry, report) !== "unknown") return false;
    if (filter === "claims" && !docClaimUnbacked(entry, report)) return false;
    if (filter === "excluded" && included) return false;
    if (filter !== "excluded" && !included) return false;
    return `${entry.title} ${entry.area} ${entry.criterion}`.toLowerCase().includes(query.toLowerCase());
  }), [draft, report, filter, query]);
  useEffect(() => {
    if (!visible.some((entry) => entry.id === selectedId)) setSelectedId(visible[0]?.id ?? "");
  }, [visible, selectedId]);
  const count = report?.counts;
  const currentItems = draft?.requirements.filter((entry) => inCurrentScope(entry, draft)) ?? [];
  const allUnknown = !!report?.total && count?.unknown === report.total;
  const noEvidence = allUnknown && !report?.stale_documents.length && currentItems.every((entry) => !entry.evidence && !isStaleEvidence(entry, report));
  const selectFilter = (value: string) => { setFilter(value); setQuery(""); setCandidates([]); };
  const changeKind = (relative: string, kind: DocumentKind) => {
    setDocumentKinds((old) => ({ ...old, [relative]: kind }));
    if (draft && relative in draft.documents) {
      setDraft({ ...draft, document_kinds: { ...draft.document_kinds, [relative]: kind } });
      setReport(null);
      setExported("");
    }
  };
  const percentage = (value: number) => report?.total ? `${Math.round(value / report.total * 100)}%` : "대상 없음";
  const extract = () => {
    if (!selectedDocs.length) return;
    setBusy("extract"); setError("");
    bridge?.previewProgress(path, JSON.stringify(selectedDocs.map((relative) => ({ path: relative, kind: documentKinds[relative] ?? "current" }))));
  };
  const save = () => {
    if (!draft) return;
    setBusy("save"); setError(""); setFieldErrors([]); setLinks(null); setExported("");
    bridge?.saveProgress(path, JSON.stringify(draft));
  };
  const addManual = () => {
    if (!draft) return;
    const sourcePath = Object.keys(draft.documents).find((relative) => (draft.document_kinds?.[relative] ?? "current") === "current");
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
      {!showDocuments && <p>{Object.keys(draft?.documents ?? {}).map((relative) => `${relative} (${documentKindText[draft?.document_kinds?.[relative] ?? "current"]})`).join(", ")} · 현재 목표 {currentItems.length}개</p>}
      {showDocuments && <><p>문서를 선택하고 종류를 지정하세요. 현재 목표에서만 기능 후보를 추출합니다. 향후 계획·과거 결과·참고는 보관과 링크 점검에 사용하며 현황에 집계하지 않습니다.</p>
      {!path ? <div className="empty-inline">왼쪽에서 프로젝트 폴더를 선택해 주세요.</div> : documents.length ? <>
        <div className="progress-doc-list" role="group" aria-label="기준 Markdown 선택">
          {documents.map((doc) => <div key={doc.path} className="progress-doc"><label><input type="checkbox" checked={selectedDocs.includes(doc.path)} onChange={(e) => setSelectedDocs((old) => e.target.checked ? [...old, doc.path] : old.filter((value) => value !== doc.path))} /><span title={doc.path}>{doc.path}</span>{!doc.tracked && <small>미추적 파일</small>}</label><select aria-label={`${doc.path}의 문서 종류`} disabled={!selectedDocs.includes(doc.path)} value={documentKinds[doc.path] ?? "current"} onChange={(e) => changeKind(doc.path, e.target.value as DocumentKind)}>{Object.entries(documentKindText).map(([kind, text]) => <option key={kind} value={kind}>{text}</option>)}</select></div>)}
        </div>
        {omitted > 0 && <p className="hint">크기 제한·제외 경로·목록 상한으로 {omitted}개 문서를 생략했습니다.</p>}
        <div className="progress-actions"><button className="primary" disabled={!selectedDocs.length || selectedDocs.length > 10 || !!busy} onClick={extract}><FileSearch size={16} /> {busy === "extract" ? "후보 추출 중…" : "기능 후보 추출"}</button><span className="hint">최대 10개 문서 · 재추출은 기존 근거를 초기화합니다. 저장된 문서의 종류만 바꾸면 근거는 유지됩니다. 새 현재 목표의 기능을 추가하려면 재추출하세요.</span></div>
      </> : <div className="empty-inline">{busy ? "Markdown 목록을 읽는 중…" : "읽을 수 있는 Markdown이 없습니다."}</div>}</>}
    </section>

    {(error || invalidItems.length > 0) && <div className="notice error" role="alert"><AlertCircle size={18} /> {invalidItems.length ? `${invalidItems.length}개 항목을 확인하세요.` : error}{invalidItems.length > 0 && <button className="text-button" onClick={goToFirstError}>첫 항목으로 이동</button>}</div>}
    {draft && <>
      <section className="progress-overview" aria-label="구현 현황 요약">
        <button className="progress-stat" disabled={!count} aria-label={count ? `완료 확인 ${count.complete}개 보기` : "완료 확인 기준 저장 필요"} aria-pressed={filter === "complete"} onClick={() => selectFilter("complete")}><span>완료 확인</span><strong>{count ? `${count.complete} / ${report?.total}` : "기준 저장 필요"}</strong><small>{count ? `${percentage(count.complete)} · 구현과 수동 검증 확인` : "수정한 기준을 저장해 주세요"}</small></button>
        <button className="progress-stat" disabled={!count} aria-label={count ? `구현 확인 ${count.implemented}개 보기` : "구현 확인 기준 저장 필요"} aria-pressed={filter === "implemented"} onClick={() => selectFilter("implemented")}><span>구현 확인</span><strong>{count ? `${count.implemented} / ${report?.total}` : "—"}</strong><small>{count ? `${percentage(count.implemented)} · 코드 근거 확인` : "코드 근거를 검토해 주세요"}</small></button>
        <button className="progress-stat" disabled={!count} aria-label={count ? `근거 없음·재확인 ${count.unknown}개 보기` : "근거 없음·재확인 기준 저장 필요"} aria-pressed={filter === "unknown"} onClick={() => selectFilter("unknown")}><span>근거 없음·재확인</span><strong>{count ? `${count.unknown}개` : "—"}</strong><small>근거 입력 또는 변경 사항 재확인</small></button>
      </section>
      {allUnknown && <div className="progress-guidance" role="status"><strong>{noEvidence ? "아직 코드 근거가 연결되지 않았습니다." : "현재 목표의 근거를 다시 확인해 주세요."}</strong><p>{noEvidence ? "이 수치는 실제 개발률이 아닙니다. 첫 기능의 코드를 연결하고 조건을 충족하는지 검토한 뒤 저장하세요." : "기준이나 코드 변경으로 이전 확인을 사용할 수 없습니다. 기능별 출처와 근거를 점검하세요."}</p><button className="secondary" onClick={() => { selectFilter("unknown"); if (noEvidence) { setSelectedId(currentItems[0]?.id ?? ""); setFocusField("evidence.path"); } }}>{noEvidence ? "첫 기능의 코드 근거 연결" : "재확인할 기능 보기"}</button></div>}
      {count && report && report.total > 0 && !allUnknown && <div className="progress-segments" role="img" aria-label={`구현 확인 ${count.implemented}개, 부분 구현 ${count.partial}개, 미구현 확인 ${count.not_implemented}개, 근거 없음·재확인 ${count.unknown}개, 총 ${report.total}개`}>
        {(["implemented", "partial", "not_implemented", "unknown"] as const).map((key) => count[key] > 0 && <div key={key} className={`progress-segment ${key}`} style={{ width: `${count[key] / report.total * 100}%` }} title={`${key === "unknown" ? "근거 없음·재확인" : statusText[key]} ${count[key]}개`} />)}
      </div>}
      {count && <p className="progress-legend">현재 목표 기준 · 구현 확인 {count.implemented} · 부분 구현 {count.partial} · 미구현 확인 {count.not_implemented} · 근거 없음·재확인 {count.unknown} · 제외 {count.excluded} · 요약 카드를 눌러 목록을 좁힐 수 있습니다.</p>}
      {report?.total === 0 && <p className="notice" role="status">집계할 현재 목표가 없습니다. 기준 문서에서 현재 목표를 선택하고 기능 후보를 확인해 주세요.</p>}
      {!!report?.stale_context_documents?.length && <p className="hint" role="status">참고 범위 문서 변경: {report.stale_context_documents.join(", ")}. 현재 목표 수치는 유지됩니다.</p>}
      {!!report?.stale_documents.length && <div className="notice error" role="alert">기준 문서가 변경됐습니다: {report.stale_documents.join(", ")}. 기능 후보를 다시 추출하고 확정해 주세요. 이전 확인은 현황 집계에서 제외했습니다.</div>}
      {!!report?.doc_claims_unbacked && <div className="notice" role="status">문서에는 완료로 표시했지만 코드 근거가 확인되지 않은 항목이 {report.doc_claims_unbacked}개 있습니다. 체크 표시는 구현 근거로 쓰지 않습니다. <button className="text-button" onClick={() => selectFilter("claims")}>해당 항목 보기</button></div>}
      {history && <History history={history} />}
      <section className="card progress-workspace">
        <div className="section-heading"><h2>기능별 현황 <span>{visible.length}</span></h2><div className="progress-actions"><button className="secondary" onClick={addManual} disabled={!!busy || !Object.keys(draft.documents).some((relative) => (draft.document_kinds?.[relative] ?? "current") === "current")}><Plus size={15} /> 직접 추가</button><button className="primary" onClick={save} disabled={!!busy}>{busy === "save" ? "저장 중…" : "기준과 근거 저장"}</button></div></div>
        <div className="progress-actions"><button className="secondary" disabled={!report || !!busy} onClick={() => { setBusy("links"); bridge?.checkProgressLinks(path); }}>{busy === "links" ? "점검 중…" : "문서 링크 점검"}</button><button className="secondary" disabled={!report || !!busy} onClick={() => { setBusy("tests"); bridge?.loadTestResults(path); }}>{busy === "tests" ? "읽는 중…" : "테스트 결과 불러오기"}</button><button className="secondary" disabled={!report || !!busy} onClick={() => bridge?.exportProgress(path, "md")}>Markdown 저장</button><button className="secondary" disabled={!report || !!busy} onClick={() => bridge?.exportProgress(path, "json")}>JSON 저장</button>{exported && <span className="hint" role="status">{exported}</span>}</div>
        {tests && <p className="hint" role="status">테스트 결과: {tests.file} · {tests.format === "junit" ? "JUnit XML" : "Jest/Vitest JSON"} · 테스트 {tests.total}개 · 파일 시각 {new Date(tests.modified).toLocaleString("ko-KR")}. 앱이 테스트를 실행한 것이 아니며, 현황 수치에는 반영하지 않습니다.{tests.remembered ? " 이전에 선택한 파일을 다시 읽었습니다." : ""} <button className="text-button" onClick={() => { bridge?.forgetTestResults(path); setTests(null); }}>파일 기억 해제</button></p>}
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
        <div className="progress-toolbar"><label>목록 필터 <select value={filter} onChange={(e) => setFilter(e.target.value)}><option value="all">전체</option><option value="complete">완료 확인</option><option value="implemented">구현 확인</option><option value="remaining">남은 작업</option><option value="unknown">근거 없음·재확인</option><option value="claims">문서와 불일치</option><option value="excluded">제외</option></select></label><label>기능 검색 <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="기능명·조건" /></label></div>
        <div className="progress-grid"><div className="progress-list" aria-label="기능 목록">
          {visible.length ? visible.map((entry) => <button key={entry.id} className={`progress-row ${selectedId === entry.id ? "active" : ""}`} onClick={() => { setSelectedId(entry.id); setCandidates([]); }} aria-current={selectedId === entry.id ? "true" : undefined}><span><strong>{errorsOf(entry.id).length > 0 && <AlertCircle size={13} aria-label="확인이 필요한 입력이 있습니다" />} {entry.title}</strong><small>{entry.area || entry.source.path} · 다음: {inCurrentScope(entry, draft) ? nextAction(entry, report) : "현재 목표 집계에서 제외"}{entry.duplicates?.length ? ` · 다른 문서 ${entry.duplicates.length}곳에도 있음` : ""}{docClaimUnbacked(entry, report) ? " · 문서는 완료 표시, 근거 없음" : ""}{tests?.items[entry.id] ? ` · 자동 검증: ${testSummary(tests.items[entry.id])}${tests.items[entry.id].code_newer ? " (결과가 코드보다 오래됨)" : ""}` : ""}</small></span><span className={`progress-status ${effectiveStatus(entry, report)}`}>{!inCurrentScope(entry, draft) ? "제외" : isStaleEvidence(entry, report) || report?.stale_documents.length ? "재확인 필요" : statusText[effectiveStatus(entry, report)]}</span><ChevronRight size={15} /></button>) : <div className="empty-inline">조건에 맞는 기능이 없습니다.</div>}
        </div><div className="progress-detail">
          {item ? <>
            <div className="section-heading"><h3>기능과 완료 조건</h3><label className="progress-include"><input type="checkbox" checked={item.included} onChange={(e) => edit(item.id, { included: e.target.checked })} /> 이번 범위에 포함</label></div>
            <label className="field">기능명<input {...mark("title")} value={item.title} onChange={(e) => edit(item.id, { title: e.target.value })} maxLength={500} /><FieldMessage text={fieldError("title")} /></label>
            <label className="field">완료 조건<textarea {...mark("criterion")} value={item.criterion} onChange={(e) => edit(item.id, { criterion: e.target.value })} rows={3} maxLength={500} /><FieldMessage text={fieldError("criterion")} /></label>
            <p className="progress-source"><strong>문서 출처</strong> {documentKindText[draft.document_kinds?.[item.source.path] ?? "current"]} · {item.source.path}{item.source.line ? `:${item.source.line}` : " · 직접 추가"}<br /><span>{item.source.excerpt}</span>{item.duplicates?.map((place) => <span key={`${place.path}:${place.line}`} className="progress-duplicate"><br />같은 항목: {place.path}:{place.line} · {place.excerpt}</span>)}<FieldMessage text={fieldError("source")} /></p>
            {docClaimUnbacked(item, report) && <p className="notice" role="status">이 항목은 문서에서 완료(<code>[x]</code>)로 표시됐지만 현재 확인된 코드 근거가 없습니다.</p>}
            <p className="progress-next"><strong>다음 할 일</strong> {!inCurrentScope(item, draft) ? "현재 목표 집계에서 제외 (기존 근거 유지)" : report?.stale_documents.length ? "변경된 기준 문서 다시 확인" : nextAction(item, report)}</p>
            <label className="field">구현 상태<select {...mark("implementation_status")} value={item.implementation_status} onChange={(e) => edit(item.id, { implementation_status: e.target.value as ProgressItem["implementation_status"], verification_status: "unverified" })}><option value="unknown">근거 없음</option><option value="partial">부분 구현</option><option value="implemented">구현 확인</option><option value="not_implemented">미구현 확인</option></select><FieldMessage text={fieldError("implementation_status")} /></label>
            {item.implementation_status !== "not_implemented" && <div className="progress-evidence"><div className="section-heading"><h3>코드 근거</h3><button className="text-button" onClick={() => bridge?.suggestProgressEvidence(path, JSON.stringify(item))}>문서에 명시된 파일 찾기</button></div><p className="hint">후보는 파일 존재만 확인합니다. 완료 조건과의 연결은 직접 검토해 주세요. 근거를 저장하려면 구현 상태를 선택하세요.</p>{candidates.map((candidate) => <button key={candidate.path} className="progress-candidate" onClick={() => edit(item.id, { evidence: { path: candidate.path, line: candidate.line, note: item.evidence?.note ?? "" } })}>{candidate.path}:{candidate.line} · {candidate.excerpt}</button>)}<div className="progress-evidence-input"><label className="field">코드 파일 경로<input {...mark("evidence.path")} value={item.evidence?.path ?? ""} onChange={(e) => edit(item.id, { evidence: { path: e.target.value, line: item.evidence?.line ?? 1, note: item.evidence?.note ?? "" } })} placeholder="src/login.py" /><FieldMessage text={fieldError("evidence.path")} /></label><label className="field">줄 번호<input {...mark("evidence.line")} type="number" min={1} value={item.evidence?.line ?? 1} onChange={(e) => edit(item.id, { evidence: { path: item.evidence?.path ?? "", line: Number(e.target.value), note: item.evidence?.note ?? "" } })} /><FieldMessage text={fieldError("evidence.line")} /></label></div><label className="field">이 코드가 조건을 충족하는 이유<textarea {...mark("evidence.note")} rows={2} value={item.evidence?.note ?? ""} onChange={(e) => edit(item.id, { evidence: { path: item.evidence?.path ?? "", line: item.evidence?.line ?? 1, note: e.target.value } })} /><FieldMessage text={fieldError("evidence.note")} /></label>{item.evidence?.excerpt && <code className="progress-code">{item.evidence.excerpt}</code>}{isStaleEvidence(item, report) && <p className="notice error">코드가 바뀌었습니다. 근거를 다시 확인해 저장하세요.</p>}</div>}
            {item.implementation_status === "not_implemented" && <label className="field">미구현을 확인한 이유<textarea {...mark("implementation_note")} rows={2} value={item.implementation_note ?? ""} onChange={(e) => edit(item.id, { implementation_note: e.target.value })} /><FieldMessage text={fieldError("implementation_note")} /></label>}
            <label className="field">검증 상태<select {...mark("verification_status")} value={item.verification_status} disabled={item.implementation_status !== "implemented"} onChange={(e) => edit(item.id, { verification_status: e.target.value as ProgressItem["verification_status"] })}><option value="unverified">미검증</option><option value="verified">수동 확인</option></select><FieldMessage text={fieldError("verification_status")} /></label>
            {item.verification_status === "verified" && <label className="field">검증 기록<textarea {...mark("verification_note")} rows={2} value={item.verification_note} onChange={(e) => edit(item.id, { verification_note: e.target.value })} placeholder="검증 방법·대상·결과를 적어 주세요" /><FieldMessage text={fieldError("verification_note")} /></label>}
            <label className="field">관련 테스트 이름 (쉼표로 구분, 이름의 일부)<input {...mark("test_patterns")} value={(item.test_patterns ?? []).join(",")} onChange={(e) => edit(item.id, { test_patterns: e.target.value.split(",") })} placeholder="test_login" /><FieldMessage text={fieldError("test_patterns")} /></label>
            {!!report?.test_pattern_hints?.[item.id]?.length && <p className="notice" role="status">저장소의 테스트 파일에서 찾지 못한 이름: {report.test_pattern_hints[item.id].join(", ")}. 오타인지 확인해 주세요.</p>}
            <p className="hint">테스트 이름에 <code>req-{item.id.slice(0, 8)}</code>를 넣으면 이 기능에 자동으로 연결됩니다.</p>
            {tests?.items[item.id] && <div className="progress-tests" aria-label="자동 검증 기록">
              <h3>자동 검증 기록 <small>{tests.file}</small></h3>
              <p>{tests.items[item.id].no_match ? `입력한 이름과 일치하는 테스트가 결과 파일에 없습니다: ${tests.items[item.id].patterns.join(", ")}` : `연결된 테스트 ${tests.items[item.id].matched}개 · ${testSummary(tests.items[item.id])}`}</p>
              {tests.items[item.id].code_newer && <p className="notice" role="status">결과 파일보다 근거 코드가 나중에 바뀌었습니다. 테스트를 다시 실행해 결과 파일을 새로 만들어 주세요.</p>}
              {tests.items[item.id].failing.length > 0 && <ul>{tests.items[item.id].failing.map((name) => <li key={name}><code>{name}</code></li>)}</ul>}
              {item.verification_status === "verified" && tests.items[item.id].failed > 0 && <p className="notice error" role="alert">수동 확인으로 기록됐지만 연결된 테스트가 실패했습니다. 결과가 최신인지 확인해 주세요.</p>}
            </div>}
            <p className="hint">수동 확인은 검증 기록을 남긴 경우에만 완료로 집계합니다. 자동 테스트 실행·CI 연결은 후속 단계입니다.</p>
          </> : <div className="empty-inline">기능을 선택하면 출처와 근거를 확인할 수 있습니다.</div>}
        </div></div>
      </section>
      <p className="hint">{report?.limitations ?? "분석 전에 기준을 저장해 주세요."}</p>
    </>}
  </div>;
}
