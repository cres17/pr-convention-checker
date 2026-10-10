import { BookOpen, FileSearch, RefreshCw } from "lucide-react";
import type { DocumentKind, ProgressBaseline, ProjectDocument } from "../../bridge";
import { documentKindText } from "./presentation";

export type { ProjectDocument } from "../../bridge";
type Props = {
  path: string;
  documents: ProjectDocument[];
  selectedDocs: string[];
  documentKinds: Record<string, DocumentKind>;
  draft: ProgressBaseline | null;
  currentCount: number;
  omitted: number;
  busy: string;
  expanded: boolean;
  onRefresh: () => void;
  onToggle: () => void;
  onSelect: (path: string, selected: boolean) => void;
  onKind: (path: string, kind: DocumentKind) => void;
  onArchive: (path: string) => void;
  onExtract: () => void;
};
export default function DocumentSetup({
  path,
  documents,
  selectedDocs,
  documentKinds,
  draft,
  currentCount,
  omitted,
  busy,
  expanded,
  onRefresh,
  onToggle,
  onSelect,
  onKind,
  onArchive,
  onExtract,
}: Props) {
  return (
    <section className="card progress-setup">
      <div className="section-heading">
        <h2>
          <BookOpen size={19} /> 기준 문서
        </h2>
        <div className="progress-actions">
          {expanded && (
            <button
              className="secondary"
              onClick={onRefresh}
              disabled={!path || !!busy}
            >
              <RefreshCw size={15} /> 문서 새로고침
            </button>
          )}
          {draft && (
            <button className="secondary" onClick={onToggle}>
              {expanded ? "문서 목록 접기" : "기준 문서 변경"}
            </button>
          )}
        </div>
      </div>
      {!expanded && (
        <p>
          {Object.keys(draft?.documents ?? {})
            .map(
              (relative) =>
                `${relative} (${documentKindText[draft?.document_kinds?.[relative] ?? "current"]})`,
            )
            .join(", ")}{" "}
          · 현재 목표 {currentCount}개
        </p>
      )}
      {expanded && (
        <>
          {draft && Object.keys(draft.documents).map((relative) => (
            <div key={`binding:${relative}`} className="progress-doc">
              <span>{relative} {draft.archived_documents?.includes(relative) ? "(출처 보관)" :
                !documents.some((doc) => doc.path === relative) ? "(현재 목록에 없음)" : "(연결됨)"}</span>
              {!draft.archived_documents?.includes(relative) && <button className="secondary"
                disabled={!!busy || (draft.archived_documents?.length ?? 0) >= 120}
                onClick={() => onArchive(relative)} aria-label={`${relative} 연결 해제하고 출처 보관`}>
                연결 해제하고 출처 보관
              </button>}
            </div>
          ))}
          {!!draft?.archived_documents?.length && <p className="hint">보관된 문서의 기능·근거는 유지되고 현재 목표 집계에서 제외됩니다. 다시 연결하려면 해당 문서를 선택하고 재추출하세요. 이름이 바뀐 문서는 새 문서로 선택하세요.</p>}
          <p>
            문서를 선택하고 종류를 지정하세요. 현재 목표에서만 기능 후보를
            추출합니다. 향후 계획·과거 결과·참고는 보관과 링크 점검에 사용하며
            현황에 집계하지 않습니다.
          </p>
          {!path ? (
            <div className="empty-inline">
              왼쪽에서 프로젝트 폴더를 선택해 주세요.
            </div>
          ) : documents.length ? (
            <>
              <div
                className="progress-doc-list"
                role="group"
                aria-label="기준 Markdown 선택"
              >
                {documents.map((doc) => (
                  <div key={doc.path} className="progress-doc">
                    <label>
                      <input
                        type="checkbox"
                        checked={selectedDocs.includes(doc.path)}
                        disabled={busy === "save" || busy === "extract"}
                        onChange={(e) => onSelect(doc.path, e.target.checked)}
                      />
                      <span title={doc.path}>{doc.path}</span>
                      {!doc.tracked && <small>미추적 파일</small>}
                    </label>
                    <select
                      aria-label={`${doc.path}의 문서 종류`}
                      disabled={
                        !selectedDocs.includes(doc.path) || busy === "save" || busy === "extract"
                      }
                      value={documentKinds[doc.path] ?? "current"}
                      onChange={(e) =>
                        onKind(doc.path, e.target.value as DocumentKind)
                      }
                    >
                      {Object.entries(documentKindText).map(([kind, text]) => (
                        <option key={kind} value={kind}>
                          {text}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
              {omitted > 0 && (
                <p className="hint">
                  크기 제한·제외 경로·목록 상한으로 {omitted}개 문서를
                  생략했습니다.
                </p>
              )}
              <div className="progress-actions">
                <button
                  className="primary"
                  disabled={
                    !selectedDocs.length || selectedDocs.length > 10 || !!busy
                  }
                  onClick={onExtract}
                >
                  <FileSearch size={16} />{" "}
                  {busy === "extract" ? "후보 추출 중…" : "기능 후보 추출"}
                </button>
                <span className="hint">
                  최대 10개 문서 · 재추출은 기존 편집과 근거를 보존하고 새
                  후보를 추가합니다. 선택 해제한 문서는 참고로 보관합니다.
                  새 현재 목표의 기능을 추가하려면 재추출하세요.
                </span>
              </div>
            </>
          ) : (
            <div className="empty-inline">
              {busy
                ? "Markdown 목록을 읽는 중…"
                : "읽을 수 있는 Markdown이 없습니다."}
            </div>
          )}
        </>
      )}
    </section>
  );
}
