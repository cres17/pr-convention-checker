# PR 파일럿 — 실행 전 산출물 목록

생성: 2026-10-21 · 엔진 출력은 아직 보지 않았다. 정답 label은 아직 없다.

## 표본 추출 결과

| 저장소 | 대상 브랜치 | 복제 시점 head | 기간 시작 | PR 형식 커밋 | 포함 조건 충족 | 제외 사유(중복 가능) | 선정 |
|---|---|---|---|---|---|---|---|
| open-webui/open-webui | `dev` | `9cbd27011b1d` | 2026-07-01 | 1020 | 952 | no-code-file 20, too-many-lines 45, too-many-files 3 | 10 |
| langflow-ai/langflow | `main` | `972d56c47d38` | 2026-07-01 | 32 | 25 | too-many-lines 3, no-code-file 3, too-many-files 3 | 10 |
| BerriAI/litellm | `main` | `2773ef0084b8` | 2026-07-01 | 2637 | 999 | too-many-files 278, bot 1191, too-many-lines 453, no-code-file 354, revert 8 | 10 |

- 기간 앞당김은 없었다(세 저장소 모두 15개 이상).
- 선정 PR 목록: [sample.json](sample.json). 생성 코드: [collect.py](collect.py). 순서는 `sha256("pr-pilot-2026-10-21:<저장소>:<PR 번호>")` 오름차순이다.
- 사례 파일(`candidates.json` 등)은 제3자 저장소의 소스·diff 18MB라 이 저장소에 넣지 않는다. 같은 저장소를 `--shallow-since=2026-01-01`로 복제해 `collect.py cases`를 다시 실행하면 아래 해시와 대조할 수 있다.

## 고정 산출물 SHA-256

| 파일 | SHA-256 |
|---|---|
| policies/open-webui.yml | `e6ff649e82ba5da0250cbb1ae5cad98c56f29e304c0de7a499e4666105de5236` |
| policies/langflow.yml | `f02d52b0d5c2d4952884d3384ed926e2dae3759370aa635187908bfe1f2f01c0` |
| policies/litellm.yml | `ef22445229f807cbb1b524e4e42103f959bfb59867d36fc615d193389dd35785` |
| sample.json | `a6b30fed6259649d0385bed46791ec2016ae6b701aedd01415e96e6fd62615b4` |
| candidates.json | `7c71920f05a040634020015b3e91fd103eb34ff2c8a3abf90955dc5199e73066` |
| holdout.json (split seed 20261021, fraction 0.999, 30 사례 전부 holdout) | `19a565e1d0c5f120492be920a3095f995b3a96520243b790941e8a9041933397` |
| frozen.json (protocol `pr-pilot-2026-10-21`) | `97b24f1e91ce00ecc492cdb816d087fc2bfb736e6aeb0853cec16442cd1e47b4` |
| packet.json (검토 항목 70개: 규칙 40, PR 단위 30) | `c23445e5033bc6ab51a797753968efe8df242b4d652694b508d6484f560273cf` |

`holdout split`은 `holdout_fraction`이 0과 1 사이여야 해서 0.999를 썼다. 저장소 단위 분할이므로 30개 사례가 모두 holdout이다.
사례의 `expected`는 스키마가 요구하는 자리표시자(`gate: pass`, 규칙 없음)이며 기대값이 아니다. 따라서 `frozen_expectation_agreement`는 쓰지 않는다.

## 다음 단계

1. 검토자가 packet의 70개 항목에 label을 단다(엔진 출력 비공개). 사람 검토자 여부는 아직 정해지지 않았다.
2. label이 모인 뒤에 `holdout run`을 실행한다(순서 위반 방지).
3. `adjudicate` → `score` → 불일치 사례별 원인 기록.
