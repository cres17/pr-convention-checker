import { useState } from "react";
import { FilePlus2 } from "lucide-react";
import type { PolicyPreview } from "../../bridge";

/** First run: the repository has no .drift-gate.yml, so show what would be created and let the user decide. */
export default function PolicySetup({ preview, busy, onPreset, onCreate }: {
  preview: PolicyPreview | null;
  busy: boolean;
  onPreset: (preset: string) => void;
  onCreate: (preset: string) => void;
}) {
  const [choice, setChoice] = useState("auto");
  const recommendations = preview?.recommendations;
  return (
    <section className="card policy-setup" aria-label="정책 파일 만들기">
      <div className="section-heading"><h2>정책 파일이 아직 없습니다</h2></div>
      <p>
        Drift Gate는 저장소 루트의 <code>.drift-gate.yml</code> 규칙으로 코드와 문서가 어긋났는지 검사합니다.
        저장소를 살펴 시작용 정책을 골랐습니다. 내용을 확인한 뒤 만들 수 있습니다.
      </p>
      {preview ? (
        <>
          <label className="field">
            시작용 정책
            <select
              value={choice}
              onChange={(e) => { setChoice(e.target.value); onPreset(e.target.value); }}
            >
              {preview.presets.map((name) => (
                <option key={name} value={name}>{name === "auto" ? `자동 추천 (${preview.preset})` : name}</option>
              ))}
            </select>
          </label>
          {recommendations && (
            <p className="hint">
              감지한 프레임워크: {recommendations.frameworks.join(", ")} · 문서 경로 후보: {recommendations.docs_paths.join(", ")}
            </p>
          )}
          <pre className="policy-preview" aria-label="만들 정책 파일 내용">{preview.policy}</pre>
          <div className="progress-actions">
            <button className="primary" disabled={busy || preview.exists} onClick={() => onCreate(choice)}>
              <FilePlus2 size={15} /> .drift-gate.yml 만들고 검사
            </button>
            <span className="hint">
              {preview.exists ? "이미 파일이 있어 만들 수 없습니다." : "기존 파일은 덮어쓰지 않습니다. 만든 파일은 Git에 추가해야 커밋됩니다."}
            </span>
          </div>
        </>
      ) : (
        <p className="hint">저장소를 살펴보는 중…</p>
      )}
    </section>
  );
}
