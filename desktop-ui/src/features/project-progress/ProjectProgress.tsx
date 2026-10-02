import DraftRecovery from "./DraftRecovery";
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
  const { state, view, actions, pendingElsewhere } = useProjectProgress(props);
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
      {state.saveWarning && <div className="notice" role="status">{state.saveWarning}</div>}
      {state.conflict && view.merge && <div className="notice error" role="alert">
        <div>
          <strong>다른 편집기에서 저장한 최신 기준이 있습니다.</strong>
          <p>{view.merge.overflow ? "현재 편집과 최신 기준을 그대로 유지했습니다." : "서로 다른 부분의 변경은 모두 보존합니다. 합친 뒤 내용을 검토하고 다시 저장해 주세요."}</p>
          {view.merge.conflicts.length > 0 && <>
            <p>같은 부분을 다르게 편집한 변경 {view.merge.conflicts.length}개는 적용할 값을 선택해야 합니다.</p>
            <ul>{view.merge.conflicts.slice(0, 10).map((label) => <li key={label}>{label}</li>)}</ul>
            {view.merge.conflicts.length > 10 && <p>외 {view.merge.conflicts.length - 10}개</p>}
          </>}
          {view.merge.overflow ? <p>합친 결과가 문서 10개·기능 120개 상한을 넘습니다. 내 초안을 파일로 내보낸 뒤 최신 기준으로 전환할 수 있습니다.</p> :
            <div className="progress-actions">
              {view.merge.conflicts.length === 0
                ? <button className="primary" disabled={!!busy} onClick={() => actions.rebase('latest')}>최신 기준과 합치기</button>
                : <>
                  <button className="secondary" disabled={!!busy} onClick={() => actions.rebase('local')}>겹치는 변경은 내 편집으로 합치기</button>
                  <button className="secondary" disabled={!!busy} onClick={() => actions.rebase('latest')}>겹치는 변경은 최신 기준으로 합치기</button>
                </>}
            </div>}
          {view.merge.overflow && <div className="progress-actions">
            <button className="secondary" disabled={!!busy} onClick={actions.exportDraft}>내 초안 파일로 내보내기</button>
            <button className="secondary" disabled={!!busy || !state.draftExported} onClick={actions.useLatest}>내 편집을 폐기하고 최신 기준 사용</button>
          </div>}
          {state.draftExported && <p>초안 파일 저장을 확인했습니다 · {state.draftExported}. 최신 기준으로 전환해도 이 파일에 내 편집이 남습니다.</p>}
        </div>
      </div>}
      {!state.dirty && (state.recovery || state.recoveryWarning) && <DraftRecovery
        options={state.recoveryOptions} selected={state.recoveryKey} warning={state.recoveryWarning}
        recoverable={!!state.recovery} busy={!!busy} onSelect={actions.chooseRecovery}
        onKeepCopies={actions.keepCopies} onRecover={actions.recoverDraft} onDiscard={actions.discardDraft} onDiscardCopies={actions.discardCopies} />}
      {state.dirty && state.recoveryWarning && <div className="notice" role="status">{state.recoveryWarning}</div>}
      {state.dirty && state.draftStatus && <div className={`notice${state.draftStatus === "error" ? " error" : ""}`} role={state.draftStatus === "error" ? "alert" : "status"}>
        {state.draftStatus === "saving" ? "복구용 초안을 자동 보관하는 중입니다." : state.draftStatus === "cached"
          ? "복구용 초안을 이 기기에 보관했습니다. 다음 실행에서 복구할 수 있습니다. 현황 확정은 기준과 근거 저장을 눌러 주세요."
          : `초안 자동 보관에 실패했습니다. ${state.draftError} 앱을 닫기 전에 기준과 근거 저장을 사용하거나 다시 편집해 재시도해 주세요.`}
      </div>}
      {pendingElsewhere > 0 && <div className="notice" role="status">
        다른 프로젝트 {pendingElsewhere}개에 저장하지 않은 현황 편집이 있습니다. 해당 프로젝트를 다시 연결하면 이어서 편집할 수 있습니다.
      </div>}
      <fieldset className="progress-page" disabled={view.recoveryPending || busy === "draft-export" || busy === "latest"} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
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
                <button className="primary" onClick={actions.save} disabled={!!busy || !!state.conflict}>
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
      </fieldset>
    </div>
  );
}
