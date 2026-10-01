import { AlertCircle, BookOpen, Plus } from "lucide-react";
import { progressFilterLabels } from "./status";
import History from "./History";
import DocumentSetup from "./DocumentSetup";
import ProgressOverview from "./ProgressOverview";
import RequirementDetail from "./RequirementDetail";
import ReferenceChecks from "./ReferenceChecks";
import RequirementList from "./RequirementList";
import useProjectProgress, { type ProjectProgressProps } from "./useProjectProgress";

export default function ProjectProgress(props: ProjectProgressProps) {
  const { path, connected } = props;
  const { state, view, actions } = useProjectProgress(props);
  const {
    documents, selectedDocs, documentKinds, draft, report, selectedId, filter, query,
    error, busy, candidates, omitted, showDocuments, fieldErrors, links, history,
    tests, exported,
  } = state;
  const { item, invalidItems, visible, currentItems, canAddManual } = view;
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
        onRefresh={actions.refreshDocuments}
        onToggle={actions.toggleDocuments}
        onSelect={actions.selectDocument}
        onKind={actions.changeKind}
        onExtract={actions.extract}
      />

      {(error || invalidItems.length > 0) && (
        <div className="notice error" role="alert">
          <AlertCircle size={18} />{" "}
          {invalidItems.length
            ? `${invalidItems.length}개 항목을 확인하세요.`
            : error}
          {invalidItems.length > 0 && (
            <button className="text-button" onClick={actions.goToFirstError}>
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
            onFilter={actions.selectFilter}
            onStartEvidence={actions.startEvidence}
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
                  onClick={actions.addManual}
                  disabled={!!busy || !canAddManual}
                >
                  <Plus size={15} /> 직접 추가
                </button>
                <button className="primary" onClick={actions.save} disabled={!!busy}>
                  {busy === "save" ? "저장 중…" : "기준과 근거 저장"}
                </button>
              </div>
            </div>
            <div className="progress-actions">
              <button
                className="secondary"
                disabled={!report || !!busy}
                onClick={actions.checkLinks}
              >
                {busy === "links" ? "점검 중…" : "문서 링크 점검"}
              </button>
              <button
                className="secondary"
                disabled={!report || !!busy}
                onClick={actions.loadTests}
              >
                {busy === "tests" ? "읽는 중…" : "테스트 결과 불러오기"}
              </button>
              <button
                className="secondary"
                disabled={!report || !!busy}
                onClick={() => actions.exportProgress("md")}
              >
                Markdown 저장
              </button>
              <button
                className="secondary"
                disabled={!report || !!busy}
                onClick={() => actions.exportProgress("json")}
              >
                JSON 저장
              </button>
              {exported && (
                <span className="hint" role="status">
                  {exported}
                </span>
              )}
            </div>
            <ReferenceChecks tests={tests} links={links} onForgetTests={actions.forgetTests} />
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
                  onChange={(e) => actions.selectFilter(e.target.value)}
                >
                  {Object.entries(progressFilterLabels).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
              </label>
              <label>
                기능 검색{" "}
                <input
                  value={query}
                  onChange={(e) => actions.search(e.target.value)}
                  placeholder="기능명·조건"
                />
              </label>
            </div>
            <div className="progress-grid">
              <RequirementList visible={visible} draft={draft} report={report} tests={tests}
                selectedId={selectedId} errors={fieldErrors} onSelect={actions.selectItem} />
              <RequirementDetail
                item={item}
                draft={draft}
                report={report}
                tests={tests}
                candidates={candidates}
                errors={fieldErrors}
                onFindEvidence={actions.findEvidence}
                onConfirmRequirement={actions.confirmRequirement}
                disabled={busy === "save"}
                edit={actions.edit}
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
