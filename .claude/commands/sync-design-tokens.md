---
description: Figma 디자인 토큰을 Tailwind CSS와 자동 동기화하는 스킬
allowed-tools: [Read, Write, Edit, Glob, Grep, Bash]
---

# Figma 디자인 토큰 → Tailwind CSS 동기화 가이드

이 스킬은 Figma에서 정의된 디자인 토큰(Variables)을 JSON으로 가져와 Tailwind CSS에서 바로 사용할 수 있는 구조로 변환하고, 프로젝트에 안전하게 반영합니다.
디자인-개발 간 토큰 싱크를 자동화하여 휴먼 에러를 제거하고 유지보수 비용을 최소화하는 것이 목적입니다.

## 전제 조건

- Figma 변수 정의가 `.figma/Library.json`에 export되어 있어야 합니다.
  - 대상: [Figma 파일(라이브러리)](https://www.figma.com/design/YOUR_FILE_KEY/Library)
- Typography 데이터는 Figma MCP 서버를 통해 자동으로 가져옵니다.
  - 대상: [Figma 타이포그래피(라이브러리)](https://www.figma.com/design/YOUR_FILE_KEY/Library?node-id=760-26&m=dev)

# 실행 프로세스

전체 작업은 4단계로 진행되며,
각 단계 완료 후 반드시 사용자 확인을 받은 뒤 다음 단계로 진행합니다.

### Phase 1: 준비 단계

#### 1-1. 업데이트 대상 선택 (기본값: 전체)

사용자가 다음 중 선택합니다:

- **① JSON 변수만**
  - Primitive Color
  - Semantic Color
  - Number 변수
  - Font Family

- **② Typography만**
  - fontSize
  - lineHeight
  - fontWeight

- **③ 전체 (권장)**
  - 위 항목 모두 처리

> 선택 범위에 따라 이후 분석 및 변환 범위를 제한하여 실행 속도를 최적화합니다.

#### 1-2. JSON 최신성 검증 (JSON 포함 선택 시)

- `.figma/Library.json` 존재 여부 확인
- 마지막 수정 시점 확인
- 최신이 아닐 경우:
  - `.figma/README.md` 지침에 따라 재 Export 진행
  - 이후 다시 실행

### Phase 2: 데이터 분석

선택된 범위만 분석합니다.

### ✅ JSON 변수 분석 시

1. `.figma/Library.json`의 `variables` 배열 로드
2. 다음 유형으로 분류:
   - Primitive
   - Semantic
   - Number
   - Font Family
3. 아래 파일과 diff 비교:
   - `app/globals.css`
   - `tailwind.config.ts`

분석 항목:
- 신규 추가 필요
- 값 변경 필요
- 제거 대상
- 오타 또는 네이밍 불일치

### ✅ Typography 분석 시

1. Figma MCP에서 Typography 토큰 수집
2. `tailwind.config.ts`의 `fontSize` 설정과 비교

검출 항목:
- size mismatch
- lineHeight mismatch
- weight mismatch
- 누락된 정의

### 🔎 분석 결과 출력

- 변경 요약 리스트 출력
- 신규 / 수정 / 삭제 / 네이밍 오류 구분
- 사용자 승인 요청

### Phase 3: 데이터 변환

선택 범위에 해당하는 데이터만 변환합니다.

### ✅ JSON 변수 변환 규칙

#### 1. 네이밍 정규화

- `Semantic/TextAndIcon/Plane/Heading` → `--semantic-text-icon-plane-heading`
- 슬래시(`/`) → 하이픈(`-`)
- 전체 소문자
- CSS Custom Property 형식 유지

#### 2. 컬러 변환

- RGB → HSL 포맷 변환
- 출력 형식: `0 0% 23%`
- shadcn/ui 호환 유지
- `<alpha-value>` 대응

#### 3. Alias 해석

- `alias` 필드 참조 체인 추적
- 최종 실값(resolve value)으로 치환

#### 4. Font Family 처리

- STRING 타입 → CSS 변수 기반 구조로 변환
- Tailwind `fontFamily` 확장 구조에 맞춤

### ✅ Typography 변환 규칙

Figma MCP 데이터 → Tailwind `fontSize` 형식:

```ts
fontSize: {
  'headline-lg': ['32px', { lineHeight: '40px', fontWeight: '700' }],
}
```

**카테고리:**
- Headline
- Title
- Body
- Label

### Phase 4: 변경 제안 및 승인

변경 대상만 정리해서 제안합니다.

**JSON 변수 선택 시 제안 항목:**
- CSS 변수 정의 샘플 (Primitive/Semantic/Number)
- Tailwind colors 정의 샘플 (semantic, primitive)
- fontFamily 설정 샘플
- borderRadius 설정 샘플
- 오타 수정 제안

**Typography 선택 시 제안 항목:**
- fontSize 설정 전체 diff
- size / lineHeight / weight 변경 제안

**전체 선택 시:**
- 위 모든 항목 통합 제안

### Phase 5: 파일 업데이트

선택한 업데이트 대상 섹션만 수정하고, 선택하지 않은 범위는 기존 값을 그대로 유지한다.

#### 순서 유지 원칙 (매우 중요)

실행할 때마다 변수나 키의 순서가 변경되면 불필요한 diff가 대량으로 발생한다.
아래 규칙을 반드시 준수한다.

**globals.css 업데이트 규칙:**
- 카테고리 내부 변수는 숫자 오름차순 정렬
  - 030, 050, 100, 200, 300... 순
- 신규 변수 추가
  - 동일 카테고리(`/* Primitive > Gray */`등) 내부에 숫자 순서에 맞게 삽입
- 카테고리 주석 유지
  - 기존 카테고리 주석(`/* Primitive > Gray */`) 및 위치 유지
- 삭제된 변수 처리
  - 완전 삭제 (주석 처리 금지, 줄 단위 삭제)
- 카테고리 순서 유지
  - Blue → Bluegray → Gray → Green → Parple → Red → WhiteAlpha → Black → Transparent
- 금지 사항
  - 카테고리 순서 변경

**주석 작성 규칙:**
- Alias 변수: `/* via Primitive/Gray/050 */`
  - 예: `--semantic-background-component-hover: 227 100% 98%; /* via Primitive/Blue/030 */`
- 직접 값 사용 시: RGB 16진수만 작성 (투명도는 값에 이미 포함) （`/* #FFFFFF */`）
  - 예: `--primitive-blue-030: 227 100% 98%; /* #F6F8FF */`
- 투명도 포함 시: RGB 16진수만 작성 (투명도는 값에 이미 포함)
  - 예: `--primitive-whitealpha-030: 0 0% 100% / 0.1; /* #FFFFFF */`
- Numbers 타입: 주석 작성 금지
  - 예: `--number-icon-hero: 80px;`
- 금지 사항
  - 기존 주석 형식 변경
  - alias 참조 정보 삭제

**tailwind.config.ts 업데이트 규칙:**
- 숫자 키는 오름차순 정렬
  - "030", "050", "100", "200"... 등
- 카테고리 키 순서 유지
  - blue → bluegray → gray → green → parple → red
- 신규 키 추가
  - 동일 depth 내부에 숫자 순서에 맞게 삽입
- 값만 수정
  - 키 순서 변경 금지
- 기존 포맷 유지
  - 인덴트 및 코드 스타일 유지
- 금지 사항:
  - 카테고리 키 재정렬
  - 객체 구조 변경

**구현 절차:**
1. 기존 파일을 읽어 현재 변수/키 순서를 기록
2. Figma 데이터와 기존 데이터를 병합 (기존 순서 우선)
3. 변경은 최소화하여 불필요한 diff 발생 방지

---

#### 선택 항목별 처리 규칙

**JSON 변수를 선택한 경우:**

`globals.css`:
- 기존 shadcn/ui 정의 유지
- Figma Design Tokens 섹션 추가 또는 업데이트
  - Primitive / Semantic / Number 카테고리 포함
- 삭제된 변수는 완전 삭제

`tailwind.config.ts`:
- 기존 색상 정의(background, foreground 등) 유지
- semantic / primitive 색상 정의 추가 또는 업데이트
  - `hsl(var(...) / <alpha-value>)` 형식 사용
- fontFamily 업데이트
- borderRadius 업데이트
- **fontSize는 수정하지 않음**(기존 값 유지)

**Typography를 선택한 경우:**

`tailwind.config.ts`:
- fontSize만 Figma MCP 데이터 기준으로 업데이트
  - 형식: `[size, { lineHeight, fontWeight }]`
- **colors, fontFamily, borderRadius는 수정하지 않음**

`globals.css`:
- **수정하지 않음**

**둘 다 선택한 경우:**

`globals.css`:
- 기존 shadcn/ui 정의 유지
- Figma Design Tokens 섹션 추가 또는 업데이트
- 삭제된 변수는 완전 삭제

`tailwind.config.ts`:
- 기존 색상 정의 유지
- semantic / primitive 색상 정의 추가 또는 업데이트
- fontFamily, borderRadius 업데이트
- fontSize를 MCP 데이터 기준으로 업데이트

**완료 확인:**
- 선택 범위 파일의 diff 출력
- 변경 요약 보고
  - 추가 수
  - 업데이트 수
  - 삭제 수

### Phase 6: 포맷 실행

파일 업데이트 완료 후 자동으로 코드 포맷 실행:

```bash
pnpm fmt
```

## 주의 사항

- 기존 shadcn/ui 정의(background, foreground, primary 등)는 반드시 유지
- 다크 모드는 `.dark` 셀렉터로 구현 가능
- **Typography는 Figma MCP를 통해 자동 동기화**
  - 폰트 패밀리 → Library.json
  - 사이즈/행간/웨이트 → MCP
- Figma 오타(Secound, Parple 등)는 원본을 따르되, 수정 제안은 별도로 제공
