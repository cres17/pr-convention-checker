# PR 파일럿 v3 — 실행 전 산출물 목록

생성: 2026-10-21 · 엔진 출력은 아직 보지 않았다. 정답 label은 아직 없다. 표본은 [sample.json](sample.json) 그대로다.

| 파일 | SHA-256 |
|---|---|
| sample.json | `a6b30fed6259649d0385bed46791ec2016ae6b701aedd01415e96e6fd62615b4` |
| policies/open-webui.yml | `e6ff649e82ba5da0250cbb1ae5cad98c56f29e304c0de7a499e4666105de5236` |
| policies/langflow.yml | `f02d52b0d5c2d4952884d3384ed926e2dae3759370aa635187908bfe1f2f01c0` |
| policies/litellm.yml | `ef22445229f807cbb1b524e4e42103f959bfb59867d36fc615d193389dd35785` |
| candidates.json (`collect.py cases`, 요구 문서 첨부) | `ea5b9a2e1b9e62f4e9acdfe1f2a042c284151cbb1ba8a669359a01e0142aeeea` |
| holdout.json (split seed 20261021, fraction 0.999) | `f80e227a29db22129eec38c1359cc56ca6542ede1c23f3c5db1101e88a0a27ac` |
| frozen.json (protocol `pr-pilot-2026-10-21-v3`) | `0cbc5311198da481736866b3e442d31e8c6876ab08d34a4b330f15d499f9143a` |
| packet.json (항목 70개: 규칙 40, PR 단위 30) | `a86ca41b993b522b4f3504017d43430d6462210ecc9a0c5ef8a3e8d20fc111f9` |
| review-sheet.md (`review_sheet.py`) | `bc7269fd48a780e1f67cfbd91e6d389323062e9b5a59f24a9b73d230435aaa99` |

사례 파일은 제3자 소스 18MB라 저장소에 넣지 않는다. `collect.py cases`를 같은 복제 상태(`--shallow-since=2026-01-01`)에서 다시 실행해 해시를 대조한다.
복제 시점 head는 [manifest.md](manifest.md)와 같다.
