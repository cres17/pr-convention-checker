import { useEffect, useRef, useState, Component, type ReactNode } from "react";
import {
  FolderOpen,
  GitBranch,
  LayoutList,
  SlidersHorizontal,
  History,
  ShieldCheck,
  ArrowUpRight,
  Play,
  ChevronRight,
  FileCode2,
  Search,
  Check,
  AlertTriangle,
  X,
  Sparkles,
  Download,
  PanelLeftClose,
  PanelLeftOpen,
  ChartNoAxesCombined,
} from "lucide-react";
import ProjectProgress from "./features/project-progress/ProjectProgress";
import ViolationGuide from "./features/review/ViolationGuide";
import { findViolation, problemSummary, problemTitle } from "./features/review/violations";
import { StatsDisplay } from "./components/tool-ui/stats-display";
import { parseSerializableStatsDisplay } from "./components/tool-ui/stats-display/schema";
import { ProgressTracker } from "./components/tool-ui/progress-tracker";
import { OptionList } from "./components/tool-ui/option-list";
import { ApprovalCard } from "./components/tool-ui/approval-card";
import { CodeDiff } from "./components/tool-ui/code-diff";
import {
  connect,
  type Bridge,
  type Scan,
  type Review,
  type Decision,
} from "./bridge";

const labels: Record<string, string> = {
  pass: "통과",
  fail: "수정 필요",
  warn: "확인 필요",
  skipped: "제외",
  unmatched: "대상 아님",
  "rejected-ignore": "예외 거절",
  uncertain: "판단 유보",
};
const providers = [
  {
    id: "codex",
    label: "ChatGPT 구독",
    description: "공식 Codex CLI에 로그인한 계정으로 검토합니다.",
  },
  {
    id: "claude",
    label: "Claude 구독",
    description: "공식 Claude Code에 로그인한 계정으로 검토합니다.",
  },
];
export class Boundary extends Component<
  { children: ReactNode },
  { error: boolean }
> {
  state = { error: false };
  static getDerivedStateFromError() {
    return { error: true };
  }
  render() {
    return this.state.error ? (
      <div className="notice error" role="alert">
        이 화면을 표시하지 못했습니다. 앱을 다시 열어 주세요. 규칙 판정은
        변경되지 않습니다.
      </div>
    ) : (
      this.props.children
    );
  }
}
function Badge({ value }: { value: string }) {
  return <span className={`badge ${value}`}>{labels[value] ?? value}</span>;
}
function name(path: string) {
  return path.split(/[\\/]/).filter(Boolean).at(-1) || "프로젝트 연결";
}
export default function App({
  initialScan = null,
  preview = false,
}: {
  initialScan?: Scan | null;
  preview?: boolean;
}) {
  const bridge = useRef<Bridge | null>(null);
  const [desktopBridge, setDesktopBridge] = useState<Bridge | null>(null);
  const [connected, setConnected] = useState(false);
  const [page, setPage] = useState("review");
  const [path, setPath] = useState(initialScan?.repository ?? "");
  const [base, setBase] = useState("HEAD");
  const [scan, setScan] = useState<Scan | null>(initialScan);
  const [review, setReview] = useState<Review | null>(null);
  const [records, setRecords] = useState<Scan[]>(
    initialScan ? [initialScan] : [],
  );
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState(0);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [provider, setProvider] = useState("codex");
  const [cli, setCli] = useState("");
  const [installed, setInstalled] = useState<Record<string, string>>({});
  const [prompt, setPrompt] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [historyScan, setHistoryScan] = useState<Scan | null>(null);
  const [fileIndex, setFileIndex] = useState(0);
  const [progressEvent, setProgressEvent] = useState<any>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (preview) return;
    let active = true;
    connect((event) => {
      if (!active) return;
      if (String(event.type).startsWith("progress")) {
        setProgressEvent(event);
        return;
      }
      switch (event.type) {
        case "ready":
          setConnected(true);
          setPath(event.repository);
          setBase(event.base);
          setInstalled(event.installed);
          break;
        case "repository":
          setPath(event.path);
          break;
        case "scanning":
          setBusy("scan");
          setError("");
          setReview(null);
          setScan(null);
          setHistoryScan(null);
          setPrompt(null);
          break;
        case "scanned":
          setBusy("");
          setScan(event.scan);
          setSelected(0);
          setFileIndex(0);
          setRecords((old) => [event.scan, ...old].slice(0, 20));
          break;
        case "preview":
          setPrompt(event.prompt);
          break;
        case "reviewing":
          setBusy("review");
          setReview(null);
          setPrompt(null);
          setError("");
          break;
        case "reviewed":
          setBusy("");
          setReview(event.review);
          break;
        case "error":
        case "reviewError":
          setBusy("");
          setError(event.message);
          break;
        case "saved":
          setNotice(`저장했습니다 · ${event.path}`);
          break;
      }
    })
      .then((value) => {
        bridge.current = value;
        setDesktopBridge(value);
      })
      .catch((e) => setError(String(e)));
    return () => {
      active = false;
    };
  }, [preview]);
  useEffect(() => {
    if (prompt !== null) dialog.current?.showModal();
    else dialog.current?.close();
  }, [prompt]);
  const current = historyScan ?? scan;
  const decisions = current?.result.rule_decisions ?? [];
  const issues = decisions.filter(
    (d) => d.status === "fail" || d.status === "rejected-ignore",
  );
  const visible = decisions.filter(
    (d) =>
      (filter === "all" ||
        (filter === "issues"
          ? d.status === "fail" || d.status === "rejected-ignore"
          : d.status === "pass")) &&
      `${d.rule_id} ${d.reason}`.toLowerCase().includes(search.toLowerCase()),
  );
  const decision = visible[selected] ?? visible[0];
  const files = current?.files ?? [];
  const file = files[fileIndex];
  const run = () => {
    setNotice("");
    setHistoryScan(null);
    setPage("review");
    bridge.current?.startScan(path, base);
  };
  const navigate = (target: string) => {
    setPage(target);
    setHistoryScan(null);
  };
  const stats = current
    ? parseSerializableStatsDisplay({
        id: "scan-stats",
        stats: [
          {
            key: "files",
            label: "변경 파일",
            value: current.changed_file_count,
          },
          { key: "rules", label: "평가 규칙", value: decisions.length },
          { key: "issues", label: "조치할 항목", value: issues.length },
          {
            key: "passed",
            label: "통과 규칙",
            value: decisions.filter((d) => d.status === "pass").length,
          },
        ],
      })
    : null;
  return (
    <div className={`app ${collapsed ? "collapsed" : ""}`}>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <GitBranch size={21} />
          </span>
          {!collapsed && (
            <div>
              Cross Agent<small>DRIFT GATE WORKSPACE</small>
            </div>
          )}
        </div>
        <button
          className="project"
          onClick={() => bridge.current?.chooseRepository()}
          disabled={!connected || !!busy}
          title="프로젝트 폴더 선택"
        >
          <FolderOpen size={18} />
          {!collapsed && (
            <span>
              <small>프로젝트</small>
              {name(path)}
            </span>
          )}
          <ChevronRight size={15} />
        </button>
        <div className="nav-caption">{!collapsed && "WORKSPACE"}</div>
        <nav aria-label="주 메뉴">
          {[
            ["review", "리뷰", LayoutList],
            ["progress", "프로젝트 현황", ChartNoAxesCombined],
            ["rules", "규칙", ShieldCheck],
            ["history", "히스토리", History],
            ["settings", "설정", SlidersHorizontal],
          ].map(([id, title, Icon]: any) => (
            <button
              key={id}
              aria-current={page === id ? "page" : undefined}
              onClick={() => navigate(id)}
              title={title}
            >
              <Icon size={19} />
              {!collapsed && title}
              {id === "review" && !!issues.length && !collapsed && (
                <b>{issues.length}</b>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          {!collapsed && (
            <div className="local-note">
              <span className="dot" />
              로컬 워크스페이스<small>규칙 검사는 외부 전송 없이 실행</small>
            </div>
          )}
          <button
            className="collapse-button"
            aria-label={collapsed ? "메뉴 펼치기" : "메뉴 접기"}
            onClick={() => setCollapsed(!collapsed)}
          >
            {collapsed ? (
              <PanelLeftOpen size={17} />
            ) : (
              <PanelLeftClose size={17} />
            )}
          </button>
        </div>
      </aside>
      <div className="workspace">
        <div className="topbar">
          <span>
            <FolderOpen size={14} />
            {name(path || current?.repository || "")}
            <ChevronRight size={12} />
            <strong>
              {
                {
                  review: "리뷰",
                  progress: "프로젝트 현황",
                  rules: "규칙",
                  history: "히스토리",
                  settings: "설정",
                }[page]
              }
            </strong>
          </span>
          <span className="mode">
            <span className="dot" />
            {preview
              ? "합성 사례 · 디자인 검증"
              : connected
                ? "데스크톱 연결됨"
                : "브라우저 미리보기 · 로컬 연결 없음"}
          </span>
        </div>
        <main>
          <header className="page-header">
            <div>
              <div className="eyebrow">CODE & DOCUMENT REVIEW</div>
              <h1>
                {
                  {
                    review: "변경을 살피고, 확신을 더하세요.",
                    progress: "계획에서 지금까지, 한눈에 확인하세요.",
                    rules: "검사의 기준을 확인하세요.",
                    history: "검토의 흐름을 이어가세요.",
                    settings: "나에게 맞는 리뷰 환경.",
                  }[page]
                }
              </h1>
              <p>
                {
                  {
                    review:
                      "규칙 판정부터 코드 근거, AI의 두 번째 의견까지 한곳에서.",
                    progress:
                      "문서의 기능과 완료 조건을 정리하고, 코드 근거와 남은 작업을 확인하세요.",
                    rules:
                      "현재 검사에 사용한 정책입니다. 실제 파일과 구분해 확인하세요.",
                    history: "이 앱 실행 중 완료한 최근 20개 검사입니다.",
                    settings: "구독 계정 연결과 데이터 전송 범위를 확인하세요.",
                  }[page]
                }
              </p>
            </div>
            {page === "review" && (
              <button
                className="primary"
                disabled={!connected || !!busy || !path.trim()}
                onClick={run}
              >
                <Play size={15} />
                {busy === "scan"
                  ? "검사 중…"
                  : scan
                    ? "다시 검사"
                    : "검사 시작"}
              </button>
            )}
          </header>
          {error && (
            <div className="notice error" role="alert">
              <AlertTriangle size={18} />
              {error}
              <button aria-label="오류 안내 닫기" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="notice" role="status">
              <Check size={18} />
              {notice}
            </div>
          )}
          {page === "review" && (
            <>
              <section className="repository-bar" aria-label="검사 설정">
                <label>
                  프로젝트
                  <input
                    value={path}
                    onChange={(e) => setPath(e.target.value)}
                    placeholder="Git 저장소 폴더 경로"
                    disabled={!!busy}
                  />
                </label>
                <button
                  className="secondary"
                  disabled={!connected || !!busy}
                  onClick={() => bridge.current?.chooseRepository()}
                >
                  <FolderOpen size={16} />
                  폴더 선택
                </button>
                <label className="base-field">
                  비교 기준
                  <input
                    value={base}
                    onChange={(e) => setBase(e.target.value)}
                    placeholder="HEAD"
                    disabled={!!busy}
                  />
                </label>
                <span className="hint">
                  HEAD는 커밋 전 변경
                  <br />새 파일은 Git 추가 후 검사
                </span>
              </section>
              {!current ? (
                <section className="empty-state">
                  <div className="empty-icon">
                    <ShieldCheck size={34} />
                  </div>
                  <span className="eyebrow">YOUR NEXT REVIEW STARTS HERE</span>
                  <h2>
                    {busy === "scan"
                      ? "변경과 문서를 확인하고 있습니다"
                      : "프로젝트의 첫 리뷰를 시작하세요"}
                  </h2>
                  <p>
                    Git 저장소와 비교 기준을 선택하면
                    <br />
                    코드 변경에 필요한 문서가 준비됐는지 확인합니다.
                  </p>
                  {busy === "scan" ? (
                    <ProgressTracker
                      id="scan-progress"
                      steps={[
                        {
                          id: "local",
                          label: "로컬 정책 검사",
                          description: "Git 변경과 정책을 읽고 판정 중",
                          status: "in-progress",
                        },
                        {
                          id: "llm",
                          label: "LLM 추가 검토",
                          description: "검사 후 직접 요청할 수 있습니다",
                          status: "pending",
                        },
                      ]}
                    />
                  ) : (
                    <button
                      className="primary"
                      onClick={() => bridge.current?.chooseRepository()}
                      disabled={!connected}
                    >
                      <FolderOpen size={17} />
                      프로젝트 폴더 선택
                    </button>
                  )}
                </section>
              ) : (
                <>
                  {historyScan && (
                    <div className="notice">
                      이전 검사 스냅샷입니다.{" "}
                      <button onClick={() => setHistoryScan(null)}>
                        최신 검사로 돌아가기
                      </button>
                    </div>
                  )}
                  <div className="summary-row">
                    <section
                      className={`verdict-card ${current.result.result}`}
                    >
                      <span className="eyebrow">규칙 판정</span>
                      <h2>
                        {labels[current.result.result] ?? current.result.result}
                      </h2>
                      <p>
                        {issues.length
                          ? `${issues.length}개 항목의 문서 조건을 확인하세요.`
                          : "설정된 정책 범위의 결과입니다."}
                      </p>
                      <span className="mono">
                        <GitBranch size={13} />
                        {current.base} → 작업 폴더
                      </span>
                    </section>
                    {stats && (
                      <StatsDisplay
                        {...stats}
                        className="stats"
                        locale="ko-KR"
                      />
                    )}
                  </div>
                  <div className="review-grid">
                    <section className="findings card">
                      <div className="section-heading">
                        <h2>
                          규칙별 판정 <span>{decisions.length}</span>
                        </h2>
                        <div className="filters" aria-label="판정 필터">
                          {[
                            ["all", "전체"],
                            ["issues", "조치 필요"],
                            ["pass", "통과"],
                          ].map(([id, label]) => (
                            <button
                              key={id}
                              aria-pressed={filter === id}
                              onClick={() => {
                                setFilter(id);
                                setSelected(0);
                              }}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      </div>
                      <label className="search">
                        <Search size={15} />
                        <input
                          aria-label="규칙 검색"
                          placeholder="규칙 이름 또는 근거 검색"
                          value={search}
                          onChange={(e) => {
                            setSearch(e.target.value);
                            setSelected(0);
                          }}
                        />
                      </label>
                      <div className="finding-list">
                        {visible.map((d, i) => (
                          <button
                            className={`finding ${decision === d ? "selected" : ""}`}
                            aria-pressed={decision === d}
                            key={d.rule_id}
                            onClick={() => setSelected(i)}
                          >
                            <div>
                              <Badge value={d.status} />
                              <span className="source">규칙 검사</span>
                            </div>
                            <strong>{problemTitle(d, findViolation(current, d))}</strong>
                            {problemTitle(d, findViolation(current, d)) !== d.rule_id && <small className="rule-id">{d.rule_id}</small>}
                            <p>{problemSummary(d)}</p>
                            <ChevronRight size={17} />
                          </button>
                        ))}
                        {!visible.length && (
                          <p className="list-empty">
                            조건에 맞는 규칙이 없습니다.
                          </p>
                        )}
                      </div>
                      <div className="list-footer">
                        <ShieldCheck size={14} />
                        규칙 판정은 LLM 의견과 별도로 유지됩니다.
                      </div>
                    </section>
                    <section className="detail card" aria-label="판정 근거">
                      {decision ? (
                        <>
                          <div className="section-heading">
                            <span className="eyebrow">EVIDENCE</span>
                            <Badge value={decision.status} />
                          </div>
                          <h2>{problemTitle(decision, findViolation(current, decision))}</h2>
                          {problemTitle(decision, findViolation(current, decision)) !== decision.rule_id && <small className="rule-id">{decision.rule_id}</small>}
                          <p>{problemSummary(decision)}</p>
                          <h3>변경된 코드</h3>
                          {decision.trigger_files.map((f) => (
                            <button
                              className="file-reference"
                              key={f}
                              onClick={() => {
                                const i = files.findIndex((x) => x.path === f);
                                if (i >= 0) {
                                  setFileIndex(i);
                                  document
                                    .getElementById("diff-view")
                                    ?.scrollIntoView({
                                      behavior: "instant",
                                      block: "start",
                                    });
                                }
                              }}
                            >
                              <FileCode2 size={15} />
                              <span>{f}</span>
                              <ArrowUpRight size={14} />
                            </button>
                          ))}
                          <GroupList decision={decision} />
                          <ViolationGuide
                            decision={decision}
                            violation={findViolation(current, decision)}
                            onOpen={!historyScan && desktopBridge ? (relative) => desktopBridge.openDocument(relative) : undefined}
                            onRescan={!historyScan && desktopBridge && path ? run : undefined}
                          />
                        </>
                      ) : (
                        <div className="list-empty">
                          규칙을 선택하면 근거가 표시됩니다.
                        </div>
                      )}
                    </section>
                  </div>
                  <section className="card diff-section" id="diff-view">
                    <div className="section-heading">
                      <h2>코드 변경 근거</h2>
                      <select
                        aria-label="변경 파일"
                        value={Math.min(
                          fileIndex,
                          Math.max(files.length - 1, 0),
                        )}
                        onChange={(e) => setFileIndex(Number(e.target.value))}
                      >
                        {files.map((f, i) => (
                          <option key={f.path} value={i}>
                            {f.path}
                          </option>
                        ))}
                      </select>
                    </div>
                    {file?.patch && file.patch.includes("@@") ? (
                      <Boundary key={file.path}>
                        <CodeDiff
                          id="file-diff"
                          patch={
                            file.patch.startsWith("diff --git ")
                              ? file.patch
                              : `diff --git a/${file.path} b/${file.path}\n--- a/${file.path}\n+++ b/${file.path}\n${file.patch}`
                          }
                          filename={file.path}
                          language="text"
                          lineNumbers="visible"
                          diffStyle="unified"
                          maxCollapsedLines={14}
                        />
                      </Boundary>
                    ) : (
                      <p className="hint">텍스트 diff가 없는 파일입니다.</p>
                    )}
                  </section>
                  <section className="ai-card">
                    <div className="ai-title">
                      <span className="ai-icon">
                        <Sparkles size={22} />
                      </span>
                      <div>
                        <span className="eyebrow">SECOND OPINION</span>
                        <h2>AI와 한 번 더 검토하세요</h2>
                      </div>
                      <Badge
                        value={
                          review && !historyScan ? review.verdict : "미요청"
                        }
                      />
                    </div>
                    <p>
                      규칙이 놓칠 수 있는 문맥을 검토합니다. 전송 자료를 먼저
                      확인하고 직접 요청하세요.
                    </p>
                    {review && !historyScan ? (
                      <div className="ai-response">
                        <strong>{review.summary}</strong>
                        {review.findings.map((f, i) => (
                          <article key={i}>
                            <h3>{f.rule_id}</h3>
                            <p>{f.reason}</p>
                            <p className="suggestion">
                              수정 제안 · {f.suggestion}
                            </p>
                          </article>
                        ))}
                        {review.limitations.map((l, i) => (
                          <p className="hint" key={i}>
                            {l}
                          </p>
                        ))}
                      </div>
                    ) : null}
                    {busy === "review" ? (
                      <>
                        <ProgressTracker
                          id="llm-progress"
                          steps={[
                            {
                              id: "scan",
                              label: "규칙 검사 완료",
                              status: "completed",
                            },
                            {
                              id: "llm",
                              label: "구독 계정으로 검토 중",
                              status: "in-progress",
                            },
                          ]}
                        />
                        <button
                          className="secondary"
                          onClick={() => bridge.current?.cancelReview()}
                        >
                          요청 중지
                        </button>
                      </>
                    ) : (
                      <button
                        className="primary"
                        disabled={
                          !connected ||
                          !!busy ||
                          !!historyScan ||
                          !current.changed_file_count
                        }
                        onClick={() => bridge.current?.previewReview()}
                      >
                        <Sparkles size={16} />
                        전송 내용 확인
                      </button>
                    )}
                    <button
                      className="text-button"
                      onClick={() => setPage("settings")}
                    >
                      연결 설정 <ArrowUpRight size={14} />
                    </button>
                  </section>
                  <div className="export-row">
                    <span>
                      검사 완료 · {new Date(current.at).toLocaleString("ko-KR")}
                    </span>
                    <button
                      className="secondary"
                      disabled={!connected || !!historyScan || !!busy}
                      onClick={() => bridge.current?.exportReport("json")}
                    >
                      <Download size={15} />
                      JSON 저장
                    </button>
                    <button
                      className="secondary"
                      disabled={!connected || !!historyScan || !!busy}
                      onClick={() => bridge.current?.exportReport("html")}
                    >
                      <Download size={15} />
                      HTML 보고서
                    </button>
                  </div>
                </>
              )}
            </>
          )}
          {page === "progress" && (
            <ProjectProgress path={path} connected={connected} bridge={desktopBridge} event={progressEvent} />
          )}
          {page === "rules" && (
            <section className="card document">
              <div className="section-heading">
                <h2>
                  <ShieldCheck size={19} /> .drift-gate.yml
                </h2>
                <span className="badge">검사 시점 · 읽기 전용</span>
              </div>
              {scan ? (
                <>
                  <p>
                    규칙을 수정하려면 저장소의 정책 파일을 편집한 후 다시
                    검사하세요.
                  </p>
                  <pre>{scan.policy}</pre>
                </>
              ) : (
                <div className="empty-inline">
                  검사를 실행하면 적용한 정책 원문을 볼 수 있습니다.
                </div>
              )}
            </section>
          )}
          {page === "history" && (
            <section className="card">
              <div className="section-heading">
                <h2>
                  이번 세션의 검사 <span>{records.length}</span>
                </h2>
                <span className="hint">앱을 닫으면 목록이 지워집니다.</span>
              </div>
              {records.length ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>검사 시각</th>
                        <th>프로젝트</th>
                        <th>비교 기준</th>
                        <th>규칙 판정</th>
                        <th>상세</th>
                      </tr>
                    </thead>
                    <tbody>
                      {records.map((r, i) => (
                        <tr key={r.at}>
                          <td>{new Date(r.at).toLocaleString("ko-KR")}</td>
                          <td>{name(r.repository)}</td>
                          <td className="mono">{r.base}</td>
                          <td>
                            <Badge value={r.result.result} />
                          </td>
                          <td>
                            <button
                              className="text-button"
                              onClick={() => {
                                setHistoryScan(i === 0 ? null : r);
                                setSelected(0);
                                setFileIndex(0);
                                setPage("review");
                              }}
                            >
                              결과 보기 <ChevronRight size={14} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="empty-inline">
                  <History size={28} />
                  <h3>아직 완료한 검사가 없습니다.</h3>
                  <p>첫 검사를 실행하면 여기에 기록됩니다.</p>
                  <button
                    className="secondary"
                    onClick={() => setPage("review")}
                  >
                    리뷰로 이동
                  </button>
                </div>
              )}
            </section>
          )}
          {page === "settings" && (
            <div className="settings-grid">
              <section className="card">
                <div className="section-heading">
                  <h2>구독 계정 연결</h2>
                  <Sparkles size={19} />
                </div>
                <p>
                  공식 CLI를 설치하고 터미널에서 로그인하세요. 앱은 계정 토큰을
                  저장하지 않습니다.
                </p>
                <OptionList
                actions={[]}
                  id="provider-settings"
                  options={providers}
                  selectionMode="single"
                  value={provider}
                  onChange={(v) => {
                    if (v === "codex" || v === "claude") {
                      setProvider(v);
                      setCli("");
                    }
                  }}
                  className="provider-list"
                />
                <label className="field">
                  CLI 실행 파일 경로 <span className="hint">선택 사항</span>
                  <input
                    value={cli}
                    onChange={(e) => setCli(e.target.value)}
                    placeholder="자동 검색 또는 직접 입력"
                  />
                </label>
                <p className="hint">
                  {installed[provider]
                    ? "CLI 발견 · 실제 로그인은 요청 시 확인"
                    : "CLI 자동 검색 결과 없음 · 설치 후 경로를 지정하세요."}
                </p>
                <div className="command">
                  <code>
                    {provider === "codex" ? "codex login" : "claude auth login"}
                  </code>
                </div>
                <p className="hint">
                  구독별 CLI 이용 권한과 사용량 한도가 적용됩니다. API 결제로
                  자동 전환하지 않습니다.
                </p>
              </section>
              <section className="card">
                <h2>전송 범위</h2>
                <dl>
                  <dt>파일 수</dt>
                  <dd>최대 60개</dd>
                  <dt>파일별 diff</dt>
                  <dd>5,000자</dd>
                  <dt>전체 diff</dt>
                  <dd>24,000자</dd>
                  <dt>정책</dt>
                  <dd>10,000자</dd>
                </dl>
                <div className="notice">
                  <ShieldCheck size={20} />
                  <span>
                    .env 및 대표 인증 파일 본문을 제외합니다. 모든 비밀값이
                    탐지되는 것은 아니므로 전송 전 미리보기를 확인하세요.
                  </span>
                </div>
                <h3>로컬 규칙 검사</h3>
                <p>
                  구독이나 API 키 없이 동작합니다. LLM 요청을 누르기 전에는
                  자료를 전송하지 않습니다.
                </p>
                <h3>저장 방식</h3>
                <p>
                  마지막 저장소 경로와 비교 기준만 기억합니다. 검사 원문은
                  세션에 보관하며, 보고서는 직접 저장합니다.
                </p>
              </section>
            </div>
          )}
          <footer>
            Cross Agent <span>·</span> Powered by Drift Gate <span>·</span> 로컬
            규칙 검사 + 선택형 LLM 검토
          </footer>
        </main>
      </div>
      <dialog
        ref={dialog}
        className="review-dialog"
        onCancel={() => setPrompt(null)}
      >
        <div className="section-heading">
          <h2>LLM에 보낼 내용</h2>
          <button
            className="icon-button"
            aria-label="전송 창 닫기"
            onClick={() => setPrompt(null)}
          >
            <X size={20} />
          </button>
        </div>
        <p>마지막 검사 스냅샷입니다. 아래 자료가 선택한 서비스로 전송됩니다.</p>
        <OptionList
                actions={[]}
          id="provider-send"
          options={providers}
          selectionMode="single"
          value={provider}
          onChange={(v) => {
            if (v === "codex" || v === "claude") {
              setProvider(v);
              setCli("");
            }
          }}
          className="provider-list"
        />
        <details>
          <summary>
            전송 원문 펼치기 · {prompt?.length.toLocaleString()}자
          </summary>
          <pre>{prompt}</pre>
        </details>
        <ApprovalCard
          id="send-confirm"
          title={`${provider === "codex" ? "ChatGPT" : "Claude"} 구독으로 추가 검토`}
          description="요청 시 구독 사용량을 소비합니다. LLM 의견은 규칙 판정을 바꾸지 않습니다."
          confirmLabel="전송하고 검토"
          cancelLabel="취소"
          onConfirm={() => bridge.current?.startReview(provider, cli)}
          onCancel={() => setPrompt(null)}
          className="approval"
        />
      </dialog>
    </div>
  );
}
function GroupList({ decision }: { decision: Decision }) {
  return (
    <>
      {decision.unsatisfied_groups.length > 0 && (
        <>
          <h3>필요한 문서 조건</h3>
          {decision.unsatisfied_groups.map((g, i) => (
            <div className="requirement" key={i}>
              <strong>{g.name}</strong>
              <p>{g.evidence}</p>
              {g.required?.map((r) => (
                <code key={r}>{r}</code>
              ))}
            </div>
          ))}
        </>
      )}
      {decision.satisfied_groups.length > 0 && (
        <>
          <h3>충족한 조건</h3>
          {decision.satisfied_groups.map((g, i) => (
            <p key={i}>
              <Check size={14} />
              {g.name} · {g.evidence}
            </p>
          ))}
        </>
      )}
    </>
  );
}
