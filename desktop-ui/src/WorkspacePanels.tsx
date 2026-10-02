import { ChevronRight, History, ShieldCheck, Sparkles } from "lucide-react";
import type { Scan } from "./bridge";
import { OptionList } from "./components/tool-ui/option-list";
import { Badge, projectName } from "./presentation";

export const providers = [
  { id: "codex", label: "ChatGPT 구독", description: "공식 Codex CLI에 로그인한 계정으로 검토합니다." },
  { id: "claude", label: "Claude 구독", description: "공식 Claude Code에 로그인한 계정으로 검토합니다." },
];

export function RulesPanel({ scan }: { scan: Scan | null }) {
  return <section className="card document">
    <div className="section-heading">
      <h2><ShieldCheck size={19} /> .drift-gate.yml</h2>
      <span className="badge">검사 시점 · 읽기 전용</span>
    </div>
    {scan ? <>
      <p>규칙을 수정하려면 저장소의 정책 파일을 편집한 후 다시 검사하세요.</p>
      <pre>{scan.policy}</pre>
    </> : <div className="empty-inline">검사를 실행하면 적용한 정책 원문을 볼 수 있습니다.</div>}
  </section>;
}

export function SessionHistory({ records, onOpen, onReview }: {
  records: Scan[]; onOpen: (index: number) => void; onReview: () => void;
}) {
  return <section className="card">
    <div className="section-heading">
      <h2>이번 세션의 검사 <span>{records.length}</span></h2>
      <span className="hint">앱을 닫으면 목록이 지워집니다.</span>
    </div>
    {records.length ? <div className="table-wrap">
      <table>
        <thead><tr><th>검사 시각</th><th>프로젝트</th><th>비교 기준</th><th>규칙 판정</th><th>상세</th></tr></thead>
        <tbody>{records.map((record, index) => <tr key={record.at}>
          <td>{new Date(record.at).toLocaleString("ko-KR")}</td>
          <td>{projectName(record.repository)}</td>
          <td className="mono">{record.base}</td>
          <td><Badge value={record.result.result} /></td>
          <td><button className="text-button" onClick={() => onOpen(index)}>결과 보기 <ChevronRight size={14} /></button></td>
        </tr>)}</tbody>
      </table>
    </div> : <div className="empty-inline">
      <History size={28} />
      <h3>아직 완료한 검사가 없습니다.</h3>
      <p>첫 검사를 실행하면 여기에 기록됩니다.</p>
      <button className="secondary" onClick={onReview}>리뷰로 이동</button>
    </div>}
  </section>;
}

export function SettingsPanel({ provider, cli, installed, onProvider, onCli }: {
  provider: string; cli: string; installed: Record<string, string>;
  onProvider: (value: "codex" | "claude") => void; onCli: (value: string) => void;
}) {
  return <div className="settings-grid">
    <section className="card">
      <div className="section-heading"><h2>구독 계정 연결</h2><Sparkles size={19} /></div>
      <p>공식 CLI를 설치하고 터미널에서 로그인하세요. 앱은 계정 토큰을 저장하지 않습니다.</p>
      <OptionList actions={[]} id="provider-settings" options={providers} selectionMode="single" value={provider}
        onChange={(value) => { if (value === "codex" || value === "claude") onProvider(value); }} className="provider-list" />
      <label className="field">
        CLI 실행 파일 경로 <span className="hint">선택 사항</span>
        <input value={cli} onChange={(event) => onCli(event.target.value)} placeholder="자동 검색 또는 직접 입력" />
      </label>
      <p className="hint">{installed[provider]
        ? "CLI 발견 · 실제 로그인은 요청 시 확인"
        : "CLI 자동 검색 결과 없음 · 설치 후 경로를 지정하세요."}</p>
      <div className="command"><code>{provider === "codex" ? "codex login" : "claude auth login"}</code></div>
      <p className="hint">구독별 CLI 이용 권한과 사용량 한도가 적용됩니다. API 결제로 자동 전환하지 않습니다.</p>
    </section>
    <section className="card">
      <h2>전송 범위</h2>
      <dl><dt>파일 수</dt><dd>최대 60개</dd><dt>파일별 diff</dt><dd>5,000자</dd>
        <dt>전체 diff</dt><dd>24,000자</dd><dt>정책</dt><dd>10,000자</dd></dl>
      <div className="notice"><ShieldCheck size={20} />
        <span>.env 및 대표 인증 파일 본문을 제외합니다. 모든 비밀값이 탐지되는 것은 아니므로 전송 전 미리보기를 확인하세요.</span>
      </div>
      <h3>로컬 규칙 검사</h3>
      <p>구독이나 API 키 없이 동작합니다. LLM 요청을 누르기 전에는 자료를 전송하지 않습니다.</p>
      <h3>저장 방식</h3>
      <p>마지막 저장소 경로와 비교 기준만 기억합니다. 검사 원문은 세션에 보관하며, 보고서는 직접 저장합니다.</p>
    </section>
  </div>;
}
