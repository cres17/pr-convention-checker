# 통합 보완 검증 자료

운영 소스는 `f43cada`, 외부 검토 문서는 `ae0028d` 기준이다. 해당 커밋 사이 변경은 docs 7개뿐이다.

- `verify.py`: 임시 Git 복사본에 fixture를 추가하고 실제 자체 검사 명령을 실행한다. 원본 저장소·인덱스는 수정하지 않는다.
- `verified-run/`: 최종 44조건. `result.json`은 실제 출력이며 `change.patch`, `status.txt`, stdout/stderr, 종료 코드가 함께 기록된다. 일부 실패 사례는 이전 PASS를 의도적으로 미리 넣고 잔존 여부를 검사했다. 그 경우 실행 결과는 `process_error`, 오래된 산출물은 `artifact_result=pass`로 구별한다.
- `run/`: 초기 40조건 탐색 결과. stale 사례의 초기 `actual=pass`는 오래된 파일의 값이므로 최종 판단에는 `verified-run/`을 사용한다.
- `replay_external.py`: 가져온 재현 프로그램을 깨끗한 ae0028d 복사본에서 실행한다.
- `mac-replay/`: Linux 검토에 대한 Mac 재현 및 C01~C12 판정 비교. 같은 verdict가 확인됐다.
- `inventory.py`, `coverage-final.json`: 범위를 명시한 194파일의 정책 일치 목록. 초기 `coverage-inventory.json`과 분류가 같다.
- `generalization-recheck.json`: 기존 동일 32사례 결과. 새 holdout이 아니다.
- `remote-*.json`: 읽기 전용 GitHub API에서 확인한 커밋·CI·branch protected 응답.

재실행할 때는 새 출력 경로를 쓴다. 기존 결과 파일을 덮어쓰지 않는다.

```sh
python docs/assessment/hardening-audit-2026-10-06/verify.py --out build/hardening-new-run
python docs/assessment/hardening-audit-2026-10-06/replay_external.py --out build/imported-review-new-run
python docs/assessment/hardening-audit-2026-10-06/inventory.py --out build/coverage-new.json
```

사전 기대는 각 사례의 검사 목적이다. 제품이 지원하지 않는 동작을 무작위 표본의 정답처럼 놓고 정확도·버그율을 계산하지 않는다. 언어/경로 fixture는 표적 실험이며 실제 악용·대규모 사용자 빈도 측정이 아니다.

통합 설명과 완료 기준: [보완 계획](../../review/drift-gate-hardening-plan-2026-10-06.md).
