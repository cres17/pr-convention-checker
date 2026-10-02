import type { LinkReport, TestLinks } from "../../bridge";
export default function ReferenceChecks({ tests, links, onForgetTests }: {
  tests: TestLinks | null; links: LinkReport | null; onForgetTests: () => void;
}) {
  const sure = links?.issues.filter((entry) => entry.confidence !== "low") ?? [];
  const hints = links?.issues.filter((entry) => entry.confidence === "low") ?? [];
  return (
    <>
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
            onClick={onForgetTests}
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

        </div>
      )}
    </>
  );
}
