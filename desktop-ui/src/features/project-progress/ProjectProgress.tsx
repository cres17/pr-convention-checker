import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, BookOpen, ChevronRight, Plus } from "lucide-react";
import type {
  Bridge,
  DocumentKind,
  LinkReport,
  ProgressHistory,
  TestLinks,
  ProgressBaseline,
  ProgressFieldError,
  ProgressItem,
  ProgressReport,
} from "../../bridge";
import History from "./History";
import DocumentSetup, { type ProjectDocument } from "./DocumentSetup";
import ProgressOverview from "./ProgressOverview";
import RequirementDetail from "./RequirementDetail";
import { nextAction, statusText, testSummary } from "./presentation";
import {
  docClaimUnbacked,
  effectiveStatus,
  filterProgressItems,
  inCurrentScope,
  isStaleEvidence,
} from "./status";

type Event = { type: string; [key: string]: any };
export default function ProjectProgress({
  path,
  connected,
  bridge,
  events,
  focus = null,
}: {
  path: string;
  connected: boolean;
  bridge: Bridge | null;
  events: Event[];
  focus?: { id: string; n: number } | null;
}) {
  const [documents, setDocuments] = useState<ProjectDocument[]>([]);
  const [selectedDocs, setSelectedDocs] = useState<string[]>([]);
  const [documentKinds, setDocumentKinds] = useState<
    Record<string, DocumentKind>
  >({});
  const [draft, setDraft] = useState<ProgressBaseline | null>(null);
  const [report, setReport] = useState<ProgressReport | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [candidates, setCandidates] = useState<
    { path: string; line: number; excerpt: string }[]
  >([]);
  const [omitted, setOmitted] = useState(0);
  const [showDocuments, setShowDocuments] = useState(true);
  const [fieldErrors, setFieldErrors] = useState<ProgressFieldError[]>([]);
  const [focusField, setFocusField] = useState("");
  const [links, setLinks] = useState<LinkReport | null>(null);
  const [history, setHistory] = useState<ProgressHistory | null>(null);
  const [tests, setTests] = useState<TestLinks | null>(null);
  const [exported, setExported] = useState("");
  const draftDirty = useRef(false);

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
    setError("");
    setBusy("");
    setOmitted(0);
    setFocusField("");
    draftDirty.current = false;
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
    const focusedItem = draft?.requirements.find(
      (entry) => entry.id === focus.id,
    );
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
    const finishRead = () =>
      setBusy((current) => (current === "save" ? current : ""));
    switch (event.type) {
      case "progressDocs":
        finishRead();
        setDocuments(event.documents);
        setOmitted(event.omitted);
        if (event.baseline && !draftDirty.current) {
          draftDirty.current = false;
          setDraft(event.baseline);
          setSelectedDocs(Object.keys(event.baseline.documents));
          setDocumentKinds(event.baseline.document_kinds ?? {});
          setSelectedId(event.baseline.requirements[0]?.id ?? "");
          setShowDocuments(false);
          bridge?.inspectProgress(path);
        } else if (!draftDirty.current) {
          const suggested = event.documents.find(
            (doc: ProjectDocument) => doc.path.toLowerCase() === "readme.md",
          );
          setSelectedDocs(suggested ? [suggested.path] : []);
        }
        break;
      case "progressPreview":
        draftDirty.current = true;
        setBusy("");
        setDraft({
          repository: path,
          documents: event.documents,
          document_kinds: event.document_kinds,
          requirements: event.requirements,
        });
        setDocumentKinds(event.document_kinds ?? {});
        setFilter("all");
        setQuery("");
        setReport(null);
        setSelectedId(event.requirements[0]?.id ?? "");
        setCandidates([]);
        break;
      case "progressSaved":
        draftDirty.current = false;
        setBusy("");
        setFieldErrors([]);
        setDraft(event.baseline);
        setSelectedDocs(Object.keys(event.baseline.documents));
        setDocumentKinds(event.baseline.document_kinds ?? {});
        setShowDocuments(false);
        break;
      case "progressReport":
        finishRead();
        // An in-flight inspection must not restore counts for an edited draft.
        if (!draftDirty.current) setReport(event.report);
        break;
      case "progressTests":
        finishRead();
        setTests(event as unknown as TestLinks);
        break;
      case "progressHistory":
        setHistory({
          snapshots: event.snapshots,
          since_save: event.since_save,
        } as ProgressHistory);
        break;
      case "progressLinks":
        finishRead();
        setLinks(event as unknown as LinkReport);
        break;
      case "progressExported":
        finishRead();
        setExported(`저장했습니다 · ${event.file}`);
        break;
      case "progressEvidence":
        if (event.id === selectedId) setCandidates(event.candidates);
        break;
      case "progressError":
        setBusy("");
        setFieldErrors(Array.isArray(event.errors) ? event.errors : []);
        setError(
          Array.isArray(event.errors) && event.errors.length
            ? ""
            : event.message,
        );
        break;
    }
  };

  const edit = (id: string, patch: Partial<ProgressItem>) => {
    if (busy === "save") return;
    draftDirty.current = true;
    setReport(null);
    setFieldErrors((old) =>
      old.filter(
        (entry) =>
          entry.id !== id ||
          !Object.keys(patch).some(
            (key) => entry.field === key || entry.field.startsWith(`${key}.`),
          ),
      ),
    );
    setDraft(
      (old) =>
        old && {
          ...old,
          requirements: old.requirements.map((item) =>
            item.id === id
              ? {
                  ...item,
                  ...patch,
                  ...(patch.criterion !== undefined &&
                  patch.criterion !== item.criterion
                    ? {
                        implementation_status: "unknown" as const,
                        evidence: null,
                      }
                    : {}),
                  ...(patch.evidence !== undefined ||
                  (patch.criterion !== undefined &&
                    patch.criterion !== item.criterion)
                    ? {
                        verification_status: "unverified" as const,
                        verification_note: "",
                      }
                    : {}),
                }
              : item,
          ),
        },
    );
  };
  const item = draft?.requirements.find((value) => value.id === selectedId);
  useEffect(() => {
    setCandidates([]);
  }, [selectedId]);
  const errorsOf = (id: string) =>
    fieldErrors.filter((entry) => entry.id === id);
  const invalidItems =
    draft?.requirements.filter((entry) => errorsOf(entry.id).length) ?? [];
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
    document
      .querySelector<HTMLElement>(`[data-field="${focusField}"]`)
      ?.focus();
    setFocusField("");
  }, [focusField, selectedId]);
  const visible = useMemo(
    () => filterProgressItems(draft, report, filter, query),
    [draft, report, filter, query],
  );
  useEffect(() => {
    if (!visible.some((entry) => entry.id === selectedId))
      setSelectedId(visible[0]?.id ?? "");
  }, [visible, selectedId]);
  const currentItems =
    draft?.requirements.filter((entry) => inCurrentScope(entry, draft)) ?? [];
  const selectFilter = (value: string) => {
    setFilter(value);
    setQuery("");
    setCandidates([]);
  };
  const changeKind = (relative: string, kind: DocumentKind) => {
    if (busy === "save") return;
    setDocumentKinds((old) => ({ ...old, [relative]: kind }));
    if (draft && relative in draft.documents) {
      draftDirty.current = true;
      setDraft({
        ...draft,
        document_kinds: { ...draft.document_kinds, [relative]: kind },
      });
      setReport(null);
      setExported("");
    }
  };
  const extract = () => {
    if (!selectedDocs.length) return;
    setBusy("extract");
    setError("");
    bridge?.previewProgress(
      path,
      JSON.stringify(
        selectedDocs.map((relative) => ({
          path: relative,
          kind: documentKinds[relative] ?? "current",
        })),
      ),
    );
  };
  const save = () => {
    if (!draft) return;
    setBusy("save");
    setError("");
    setFieldErrors([]);
    setLinks(null);
    setExported("");
    bridge?.saveProgress(path, JSON.stringify(draft));
  };
  const addManual = () => {
    if (!draft || busy === "save") return;
    draftDirty.current = true;
    const sourcePath = Object.keys(draft.documents).find(
      (relative) =>
        (draft.document_kinds?.[relative] ?? "current") === "current",
    );
    if (!sourcePath) return;
    const id = crypto.randomUUID();
    const newItem: ProgressItem = {
      id,
      title: "새 기능",
      criterion: "완료 조건을 입력하세요",
      area: "직접 추가",
      included: true,
      source: {
        path: sourcePath,
        line: 0,
        excerpt: "사용자가 직접 추가",
        sha256: draft.documents[sourcePath],
      },
      implementation_status: "unknown",
      evidence: null,
      verification_status: "unverified",
      verification_note: "",
    };
    setDraft({ ...draft, requirements: [...draft.requirements, newItem] });
    setReport(null);
    setSelectedId(id);
  };

  if (!connected)
    return (
      <section className="card progress-empty">
        <BookOpen size={28} />
        <h2>데스크톱 앱에서 프로젝트를 연결해 주세요.</h2>
        <p>브라우저 미리보기에서는 로컬 문서를 읽지 않습니다.</p>
      </section>
    );
  return (
    <div className="progress-page">
      <DocumentSetup
        path={path}
        documents={documents}
        selectedDocs={selectedDocs}
        documentKinds={documentKinds}
        draft={draft}
        currentCount={currentItems.length}
        omitted={omitted}
        busy={busy}
        expanded={showDocuments}
        onRefresh={() => bridge?.listProjectDocs(path)}
        onToggle={() => setShowDocuments(!showDocuments)}
        onSelect={(relative, selected) =>
          setSelectedDocs((old) =>
            selected
              ? [...old, relative]
              : old.filter((value) => value !== relative),
          )
        }
        onKind={changeKind}
        onExtract={extract}
      />

      {(error || invalidItems.length > 0) && (
        <div className="notice error" role="alert">
          <AlertCircle size={18} />{" "}
          {invalidItems.length
            ? `${invalidItems.length}개 항목을 확인하세요.`
            : error}
          {invalidItems.length > 0 && (
            <button className="text-button" onClick={goToFirstError}>
              첫 항목으로 이동
            </button>
          )}
        </div>
      )}
      {draft && (
        <>
          <ProgressOverview
            report={report}
            currentItems={currentItems}
            filter={filter}
            onFilter={selectFilter}
            onStartEvidence={() => {
              setSelectedId(currentItems[0]?.id ?? "");
              setFocusField("evidence.path");
            }}
          />
          {history && <History history={history} />}
          <section className="card progress-workspace">
            <div className="section-heading">
              <h2>
                기능별 현황 <span>{visible.length}</span>
              </h2>
              <div className="progress-actions">
                <button
                  className="secondary"
                  onClick={addManual}
                  disabled={
                    !!busy ||
                    !Object.keys(draft.documents).some(
                      (relative) =>
                        (draft.document_kinds?.[relative] ?? "current") ===
                        "current",
                    )
                  }
                >
                  <Plus size={15} /> 직접 추가
                </button>
                <button className="primary" onClick={save} disabled={!!busy}>
                  {busy === "save" ? "저장 중…" : "기준과 근거 저장"}
                </button>
              </div>
            </div>
            <div className="progress-actions">
              <button
                className="secondary"
                disabled={!report || !!busy}
                onClick={() => {
                  setBusy("links");
                  bridge?.checkProgressLinks(path);
                }}
              >
                {busy === "links" ? "점검 중…" : "문서 링크 점검"}
              </button>
              <button
                className="secondary"
                disabled={!report || !!busy}
                onClick={() => {
                  setBusy("tests");
                  bridge?.loadTestResults(path);
                }}
              >
                {busy === "tests" ? "읽는 중…" : "테스트 결과 불러오기"}
              </button>
              <button
                className="secondary"
                disabled={!report || !!busy}
                onClick={() => bridge?.exportProgress(path, "md")}
              >
                Markdown 저장
              </button>
              <button
                className="secondary"
                disabled={!report || !!busy}
                onClick={() => bridge?.exportProgress(path, "json")}
              >
                JSON 저장
              </button>
              {exported && (
                <span className="hint" role="status">
                  {exported}
                </span>
              )}
            </div>
            {tests && (
              <p className="hint" role="status">
                테스트 결과: {tests.file} ·{" "}
                {tests.format === "junit" ? "JUnit XML" : "Jest/Vitest JSON"} ·
                테스트 {tests.total}개 · 파일 시각{" "}
                {new Date(tests.modified).toLocaleString("ko-KR")}. 앱이
                테스트를 실행한 것이 아니며, 현황 수치에는 반영하지 않습니다.
                {tests.remembered
                  ? " 이전에 선택한 파일을 다시 읽었습니다."
                  : ""}{" "}
                <button
                  className="text-button"
                  onClick={() => {
                    bridge?.forgetTestResults(path);
                    setTests(null);
                  }}
                >
                  파일 기억 해제
                </button>
              </p>
            )}
            {links && (
              <div className="progress-links" aria-label="문서 링크 점검 결과">
                <h3>
                  문서 링크 점검 <span>{links.checked}개 확인</span>
                </h3>
                {(() => {
                  const sure = links.issues.filter(
                    (entry) => entry.confidence !== "low",
                  );
                  const hints = links.issues.filter(
                    (entry) => entry.confidence === "low",
                  );
                  return (
                    <>
                      {sure.length ? (
                        <ul>
                          {sure.map((entry) => (
                            <li
                              key={`${entry.path}:${entry.line}:${entry.target}`}
                            >
                              <code>
                                {entry.path}:{entry.line}
                              </code>{" "}
                              {entry.target} · {entry.message}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="hint">깨진 링크가 없습니다.</p>
                      )}
                      {hints.length > 0 && (
                        <details>
                          <summary>
                            확인이 필요한 파일 경로 {hints.length}개 (예시
                            경로일 수 있음)
                          </summary>
                          <ul>
                            {hints.map((entry) => (
                              <li
                                key={`${entry.path}:${entry.line}:${entry.target}`}
                              >
                                <code>
                                  {entry.path}:{entry.line}
                                </code>{" "}
                                {entry.target} · {entry.message}
                              </li>
                            ))}
                          </ul>
                        </details>
                      )}
                      <p className="hint">
                        {links.limitations}
                        {links.truncated
                          ? " 결과가 많아 일부만 표시합니다."
                          : ""}
                      </p>
                    </>
                  );
                })()}
              </div>
            )}
            <p className="hint">
              {report
                ? `요구사항 v${report.version} · 분석 ${new Date(report.at).toLocaleString("ko-KR")} · 코드 ${report.head.slice(0, 8)}`
                : "변경 사항이 저장되면 현황 수치를 다시 계산합니다."}
            </p>
            <div className="progress-toolbar">
              <label>
                목록 필터{" "}
                <select
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                >
                  <option value="all">전체</option>
                  <option value="complete">완료 확인</option>
                  <option value="implemented">구현 확인</option>
                  <option value="remaining">남은 작업</option>
                  <option value="unknown">근거 없음·재확인</option>
                  <option value="claims">문서와 불일치</option>
                  <option value="excluded">제외</option>
                </select>
              </label>
              <label>
                기능 검색{" "}
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="기능명·조건"
                />
              </label>
            </div>
            <div className="progress-grid">
              <div className="progress-list" aria-label="기능 목록">
                {visible.length ? (
                  visible.map((entry) => (
                    <button
                      key={entry.id}
                      className={`progress-row ${selectedId === entry.id ? "active" : ""}`}
                      onClick={() => {
                        setSelectedId(entry.id);
                        setCandidates([]);
                      }}
                      aria-current={
                        selectedId === entry.id ? "true" : undefined
                      }
                    >
                      <span>
                        <strong>
                          {errorsOf(entry.id).length > 0 && (
                            <AlertCircle
                              size={13}
                              aria-label="확인이 필요한 입력이 있습니다"
                            />
                          )}{" "}
                          {entry.title}
                        </strong>
                        <small>
                          {entry.area || entry.source.path} · 다음:{" "}
                          {inCurrentScope(entry, draft)
                            ? nextAction(entry, report)
                            : "현재 목표 집계에서 제외"}
                          {entry.duplicates?.length
                            ? ` · 다른 문서 ${entry.duplicates.length}곳에도 있음`
                            : ""}
                          {docClaimUnbacked(entry, report)
                            ? " · 문서는 완료 표시, 근거 없음"
                            : ""}
                          {tests?.items[entry.id]
                            ? ` · 자동 검증: ${testSummary(tests.items[entry.id])}${tests.items[entry.id].code_newer ? " (결과가 코드보다 오래됨)" : ""}`
                            : ""}
                        </small>
                      </span>
                      <span
                        className={`progress-status ${effectiveStatus(entry, report)}`}
                      >
                        {!inCurrentScope(entry, draft)
                          ? "제외"
                          : isStaleEvidence(entry, report) ||
                              report?.stale_documents.length
                            ? "재확인 필요"
                            : statusText[effectiveStatus(entry, report)]}
                      </span>
                      <ChevronRight size={15} />
                    </button>
                  ))
                ) : (
                  <div className="empty-inline">
                    조건에 맞는 기능이 없습니다.
                  </div>
                )}
              </div>
              <RequirementDetail
                item={item}
                draft={draft}
                report={report}
                tests={tests}
                candidates={candidates}
                errors={fieldErrors}
                bridge={bridge}
                path={path}
                disabled={busy === "save"}
                edit={edit}
              />
            </div>
          </section>
          <p className="hint">
            {report?.limitations ?? "분석 전에 기준을 저장해 주세요."}
          </p>
        </>
      )}
    </div>
  );
}
