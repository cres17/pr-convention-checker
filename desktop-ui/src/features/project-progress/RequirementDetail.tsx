import type {
  Bridge,
  ProgressBaseline,
  ProgressFieldError,
  ProgressItem,
  ProgressReport,
  TestLinks,
} from "../../bridge";
import { documentKindText, nextAction, testSummary } from "./presentation";
import { docClaimUnbacked, inCurrentScope, isStaleEvidence } from "./status";

type Props = {
  item?: ProgressItem;
  draft: ProgressBaseline;
  report: ProgressReport | null;
  tests: TestLinks | null;
  candidates: { path: string; line: number; excerpt: string }[];
  errors: ProgressFieldError[];
  bridge: Bridge | null;
  path: string;
  disabled: boolean;
  edit: (id: string, patch: Partial<ProgressItem>) => void;
};
function FieldMessage({ text }: { text?: string }) {
  return text ? (
    <small className="field-error" role="alert">
      {text}
    </small>
  ) : null;
}

export default function RequirementDetail({
  item,
  draft,
  report,
  tests,
  candidates,
  errors,
  bridge,
  path,
  disabled,
  edit,
}: Props) {
  const fieldError = (field: string) =>
    errors.find((entry) => entry.id === item?.id && entry.field === field)
      ?.message;
  const mark = (field: string) => ({
    "data-field": field,
    "aria-invalid": fieldError(field) ? true : undefined,
  });
  return (
    <div className="progress-detail">
      <fieldset className="progress-detail-fields" disabled={disabled}>
        {item ? (
          <>
            <div className="section-heading">
              <h3>기능과 완료 조건</h3>
              <label className="progress-include">
                <input
                  type="checkbox"
                  checked={item.included}
                  onChange={(e) =>
                    edit(item.id, { included: e.target.checked })
                  }
                />{" "}
                이번 범위에 포함
              </label>
            </div>
            <label className="field">
              기능명
              <input
                {...mark("title")}
                value={item.title}
                onChange={(e) => edit(item.id, { title: e.target.value })}
                maxLength={500}
              />
              <FieldMessage text={fieldError("title")} />
            </label>
            <label className="field">
              완료 조건
              <textarea
                {...mark("criterion")}
                value={item.criterion}
                onChange={(e) => edit(item.id, { criterion: e.target.value })}
                rows={3}
                maxLength={500}
              />
              <FieldMessage text={fieldError("criterion")} />
            </label>
            <p className="progress-source">
              <strong>문서 출처</strong>{" "}
              {
                documentKindText[
                  draft.document_kinds?.[item.source.path] ?? "current"
                ]
              }{" "}
              · {item.source.path}
              {item.source.line ? `:${item.source.line}` : " · 직접 추가"}
              <br />
              <span>{item.source.excerpt}</span>
              {item.duplicates?.map((place) => (
                <span
                  key={`${place.path}:${place.line}`}
                  className="progress-duplicate"
                >
                  <br />
                  같은 항목: {place.path}:{place.line} · {place.excerpt}
                </span>
              ))}
              <FieldMessage text={fieldError("source")} />
            </p>
            {docClaimUnbacked(item, report) && (
              <p className="notice" role="status">
                이 항목은 문서에서 완료(<code>[x]</code>)로 표시됐지만 현재
                확인된 코드 근거가 없습니다.
              </p>
            )}
            <p className="progress-next">
              <strong>다음 할 일</strong>{" "}
              {!inCurrentScope(item, draft)
                ? "현재 목표 집계에서 제외 (기존 근거 유지)"
                : report?.stale_documents.length
                  ? "변경된 기준 문서 다시 확인"
                  : nextAction(item, report)}
            </p>
            <label className="field">
              구현 상태
              <select
                {...mark("implementation_status")}
                value={item.implementation_status}
                onChange={(e) =>
                  edit(item.id, {
                    implementation_status: e.target
                      .value as ProgressItem["implementation_status"],
                    verification_status: "unverified",
                  })
                }
              >
                <option value="unknown">근거 없음</option>
                <option value="partial">부분 구현</option>
                <option value="implemented">구현 확인</option>
                <option value="not_implemented">미구현 확인</option>
              </select>
              <FieldMessage text={fieldError("implementation_status")} />
            </label>
            {item.implementation_status !== "not_implemented" && (
              <div className="progress-evidence">
                <div className="section-heading">
                  <h3>코드 근거</h3>
                  <button
                    className="text-button"
                    onClick={() =>
                      bridge?.suggestProgressEvidence(
                        path,
                        JSON.stringify(item),
                      )
                    }
                  >
                    문서에 명시된 파일 찾기
                  </button>
                </div>
                <p className="hint">
                  후보는 파일 존재만 확인합니다. 완료 조건과의 연결은 직접
                  검토해 주세요. 근거를 저장하려면 구현 상태를 선택하세요.
                </p>
                {candidates.map((candidate) => (
                  <button
                    key={candidate.path}
                    className="progress-candidate"
                    onClick={() =>
                      edit(item.id, {
                        evidence: {
                          path: candidate.path,
                          line: candidate.line,
                          note: item.evidence?.note ?? "",
                        },
                      })
                    }
                  >
                    {candidate.path}:{candidate.line} · {candidate.excerpt}
                  </button>
                ))}
                <div className="progress-evidence-input">
                  <label className="field">
                    코드 파일 경로
                    <input
                      {...mark("evidence.path")}
                      value={item.evidence?.path ?? ""}
                      onChange={(e) =>
                        edit(item.id, {
                          evidence: {
                            path: e.target.value,
                            line: item.evidence?.line ?? 1,
                            note: item.evidence?.note ?? "",
                          },
                        })
                      }
                      placeholder="src/login.py"
                    />
                    <FieldMessage text={fieldError("evidence.path")} />
                  </label>
                  <label className="field">
                    줄 번호
                    <input
                      {...mark("evidence.line")}
                      type="number"
                      min={1}
                      value={item.evidence?.line ?? 1}
                      onChange={(e) =>
                        edit(item.id, {
                          evidence: {
                            path: item.evidence?.path ?? "",
                            line: Number(e.target.value),
                            note: item.evidence?.note ?? "",
                          },
                        })
                      }
                    />
                    <FieldMessage text={fieldError("evidence.line")} />
                  </label>
                </div>
                <label className="field">
                  이 코드가 조건을 충족하는 이유
                  <textarea
                    {...mark("evidence.note")}
                    rows={2}
                    value={item.evidence?.note ?? ""}
                    onChange={(e) =>
                      edit(item.id, {
                        evidence: {
                          path: item.evidence?.path ?? "",
                          line: item.evidence?.line ?? 1,
                          note: e.target.value,
                        },
                      })
                    }
                  />
                  <FieldMessage text={fieldError("evidence.note")} />
                </label>
                {item.evidence?.excerpt && (
                  <code className="progress-code">{item.evidence.excerpt}</code>
                )}
                {isStaleEvidence(item, report) && (
                  <p className="notice error">
                    코드가 바뀌었습니다. 근거를 다시 확인해 저장하세요.
                  </p>
                )}
              </div>
            )}
            {item.implementation_status === "not_implemented" && (
              <label className="field">
                미구현을 확인한 이유
                <textarea
                  {...mark("implementation_note")}
                  rows={2}
                  value={item.implementation_note ?? ""}
                  onChange={(e) =>
                    edit(item.id, { implementation_note: e.target.value })
                  }
                />
                <FieldMessage text={fieldError("implementation_note")} />
              </label>
            )}
            <label className="field">
              검증 상태
              <select
                {...mark("verification_status")}
                value={item.verification_status}
                disabled={item.implementation_status !== "implemented"}
                onChange={(e) =>
                  edit(item.id, {
                    verification_status: e.target
                      .value as ProgressItem["verification_status"],
                  })
                }
              >
                <option value="unverified">미검증</option>
                <option value="verified">수동 확인</option>
              </select>
              <FieldMessage text={fieldError("verification_status")} />
            </label>
            {item.verification_status === "verified" && (
              <label className="field">
                검증 기록
                <textarea
                  {...mark("verification_note")}
                  rows={2}
                  value={item.verification_note}
                  onChange={(e) =>
                    edit(item.id, { verification_note: e.target.value })
                  }
                  placeholder="검증 방법·대상·결과를 적어 주세요"
                />
                <FieldMessage text={fieldError("verification_note")} />
              </label>
            )}
            <label className="field">
              관련 테스트 이름 (쉼표로 구분, 이름의 일부)
              <input
                {...mark("test_patterns")}
                value={(item.test_patterns ?? []).join(",")}
                onChange={(e) =>
                  edit(item.id, { test_patterns: e.target.value.split(",") })
                }
                placeholder="test_login"
              />
              <FieldMessage text={fieldError("test_patterns")} />
            </label>
            {!!report?.test_pattern_hints?.[item.id]?.length && (
              <p className="notice" role="status">
                저장소의 테스트 파일에서 찾지 못한 이름:{" "}
                {report.test_pattern_hints[item.id].join(", ")}. 오타인지 확인해
                주세요.
              </p>
            )}
            <p className="hint">
              테스트 이름에 <code>req-{item.id.slice(0, 8)}</code>를 넣으면 이
              기능에 자동으로 연결됩니다.
            </p>
            {tests?.items[item.id] && (
              <div className="progress-tests" aria-label="자동 검증 기록">
                <h3>
                  자동 검증 기록 <small>{tests.file}</small>
                </h3>
                <p>
                  {tests.items[item.id].no_match
                    ? `입력한 이름과 일치하는 테스트가 결과 파일에 없습니다: ${tests.items[item.id].patterns.join(", ")}`
                    : `연결된 테스트 ${tests.items[item.id].matched}개 · ${testSummary(tests.items[item.id])}`}
                </p>
                {tests.items[item.id].code_newer && (
                  <p className="notice" role="status">
                    결과 파일보다 근거 코드가 나중에 바뀌었습니다. 테스트를 다시
                    실행해 결과 파일을 새로 만들어 주세요.
                  </p>
                )}
                {tests.items[item.id].failing.length > 0 && (
                  <ul>
                    {tests.items[item.id].failing.map((name) => (
                      <li key={name}>
                        <code>{name}</code>
                      </li>
                    ))}
                  </ul>
                )}
                {item.verification_status === "verified" &&
                  tests.items[item.id].failed > 0 && (
                    <p className="notice error" role="alert">
                      수동 확인으로 기록됐지만 연결된 테스트가 실패했습니다.
                      결과가 최신인지 확인해 주세요.
                    </p>
                  )}
              </div>
            )}
            <p className="hint">
              수동 확인은 검증 기록을 남긴 경우에만 완료로 집계합니다. 자동
              테스트 실행·CI 연결은 후속 단계입니다.
            </p>
          </>
        ) : (
          <div className="empty-inline">
            기능을 선택하면 출처와 근거를 확인할 수 있습니다.
          </div>
        )}
      </fieldset>
    </div>
  );
}
