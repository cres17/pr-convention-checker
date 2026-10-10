---
description: Figma 디자인으로부터 UI 컴포넌트의 요구사항을 정의하고 구현을 지원하는 스킬
allowed-tools: [Read, Write, Edit, Glob, Grep, Bash, EnterPlanMode, ExitPlanMode]
---

# UI 디자인 요구사항 정의 및 구현

Figma 디자인으로부터 UI 컴포넌트의 요구사항을 정의하고 구현을 지원하는 스킬입니다.

## 실행 플로우

### Phase 1: 정보 수집

다음 정보를 사용자에게 입력·선택하게 합니다.

1. Figma URL (node-id 포함) 확인
2. 참고해야 할 API Interface 파일(선택 사항) 확인

### Phase 2: 기존 컴포넌트 확인

1. `/components/ui/` 하위의 컴포넌트 파일을 읽기
2. 각 파일 상단 주석에서 Figma 정보(fileKey, node-id) 추출
3. 새로 추가할 Figma 노드 정보와 대조하여 동일 컴포넌트 식별
4. Figma 정보가 없는 경우, 이름 및 프로퍼티를 기준으로 재사용 가능성 판단

### Phase 3: Figma 디자인 정보 취득

**신규 컴포넌트에 대해서만 상세 취득**

1. URL에서 node-id 추출
   - URL 패턴:
     `https://figma.com/design/:fileKey/:fileName?node-id=X-Y`
   - node-id 변환 예:
     `node-id=11-3265` → `11:3265`

2. proto 파일 읽기 (제공된 경우에 한함)
   - `proto/` 하위 파일을 읽어 타입 정의 참조

3. 기존 컴포넌트로 대응 가능한지 판단
   - 기존 `/components/ui/`에서 대응 가능 → 이름과 경로만 기록
   - 신규 생성 필요 → 아래 MCP 툴 병렬 실행

4. Figma MCP 툴을 통한 디자인 정보 취득 (신규 컴포넌트만)

   #### Step 1: 스크린샷 및 메타데이터 취득

   ```typescript
   // 병렬로 호출
   mcp__figma-desktop__get_screenshot({
     nodeId: "추출한 node-id",
     clientLanguages: "typescript",
     clientFrameworks: "react"
   })

   mcp__figma-desktop__get_metadata({
     nodeId: "추출한 node-id",
     clientLanguages: "typescript",
     clientFrameworks: "react"
   })

   mcp__figma-desktop__get_variable_defs({
     nodeId: "추출한 node-id",
     clientLanguages: "typescript",
     clientFrameworks: "react"
   })
   ```

   #### Step 2: 디자인 컨텍스트를 단계적으로 취득

   `get_design_context`는 응답 토큰이 커질 수 있으므로 **분할 취득**합니다.

   1. **루트 노드 구조 먼저 취득**
      ```typescript
      mcp__figma-desktop__get_design_context({
        nodeId: "루트 node-id",
        clientLanguages: "typescript",
        clientFrameworks: "react"
      })
      ```

   2. **Token Limit 에러 발생 시 자식 노드 단위로 분할 취득**
      - Step 1에서 취득한 `get_metadata`의 결과로부터 자식 노드의 node-id를 특정
      - 각 자식 노드에 대해 개별적으로 `get_design_context`를 호출합니다.
      ```typescript
      // 자식 노드별로 병렬로 호출
      mcp__figma-desktop__get_design_context({
        nodeId: "자식1 node-id",
        clientLanguages: "typescript",
        clientFrameworks: "react"
      })
      mcp__figma-desktop__get_design_context({
        nodeId: "자식2 node-id",
        clientLanguages: "typescript",
        clientFrameworks: "react"
      })
      // ...
      ```

   3. **그래도 Token Limit 에러가 발생하는 경우, 더 깊은 계층으로 분할**
      - 에러가 발생한 노드의 자식 노드를 식별하고, 재귀적으로 분할 취득을 반복

   > **주의**: 취득한 각 파트의 디자인 정보를 통합하여 전체 컴포넌트 구조를 파악할 것.

### Phase 4: 구현 방침 제안

다음 정보를 포함한 구현 방침을 **ExitPlanMode 도구**로 제안하고, 사용자 승인을 기다립니다.

#### 제안 내용

1. **디자인 개요**
   - Figma URL
   - Node ID
   - 스크린샷 참조

2. **컴포넌트 구조 (트리 형식)** [**최우선**]
   - 전체 컴포넌트를 계층 구조로 표시
   - 각 컴포넌트에 (기존) 또는 (신규) 라벨 부여
   - 예시:
     ```
     페이지명
     ├── Header(기존 활용)
     │   ├── Logo(신규)
     │   └── Navigation(기존)
     └── Content
         ├── Card(기존)
         │   ├── CardTitle(기존)
         │   └── CustomIcon(신규)
         └── Footer(신규)
     ```

3. **기존 컴포넌트 활용 리스트**
   - 컴포넌트명, 파일 경로, 용도

4. **신규 생성 컴포넌트 리스트**
   - `/components/ui/` (공용·Storybook 필수)
   - `/app/components/` (페이지 전용)
   - 아이콘 및 유틸리티

5. **구현 절차**
   - Phase 단위의 단계적 계획

#### ⚠️ 중요:

**ExitPlanMode의 plan 파라미터에는 위 트리 구조를 생략 없이 모두 포함할 것.**
요약 금지. 전체 구조를 완전하게 제공할 것.

### Phase 5: 구현

승인 후 다음 순서로 구현:

1. **TodoWrite 도구로 작업 관리**
2. **컴포넌트 구현**
   - Figma 기반 구현
   - 기존 패턴 준수
3. **Storybook 파일 생성** (/components/ui/만)
4. **타입 정의 작성**
   - proto 파일이 있을 경우 참조
5. **기존 코드에 통합**
6. **완료 보고**

## 배치 규칙

| 디렉토리 | 대상 | 예 | Storybook |
|-----------|------|----|------------|
| `/components/ui/` | Figma 라이브러리 컴포넌트 | Button, Input, Messaging | 필수 |
| `/components/icons/` | 라이브러리 아이콘 | Check, ChevronDown | 선택 |
| `/app/components/pages/` | 페이지 전용 컴포넌트 | MemberCard, ProjectList | 불필요 |

**판단 기준**：
- 디자인 시스템 재사용 가능 → `/components/ui/`
- 단순 아이콘 → `/components/icons/`
- 특정 화면 전용 → `/app/components/pages/`

## Figma 연동 규칙

### Figma 메타데이터 주석 규칙

`/components/ui/` 및 `/components/icons/`에는 반드시 다음 주석을 포함한다.

```typescript
/**
 * Figma Information:
 * fileKey: YOUR_LIBRARY_FILE_KEY
 * node-id: 88-2636
 * URL: https://www.figma.com/design/YOUR_LIBRARY_FILE_KEY/Library?node-id=88-2636
 */
```

## 취득 방법

- MCP 도구를 통해 fileKey와 node-id를 취득
- URL에서 node-id를 추출할 때 `X-Y` 형식을 `X:Y`로 변환


## 적용 대상

- `/components/ui/` - 필수
- `/components/icons/` - 필수
- `/app/components/pages/` - 불필요 (페이지 전용이므로)

## 기존 컴포넌트 판정 방법

### 1. Figma 정보 기반 판정

- 컴포넌트 파일 상단 주석에서 fileKey와 node-id를 추출
- 새로 추가할 Figma 노드의 fileKey + node-id와 일치하면 “기존”으로 판정

### 2. Figma 정보가 없는 경우

- 컴포넌트 이름 및 props를 시각적으로 비교해 유사성 판단
- 재사용 가능하다고 판단되면 기존 컴포넌트에 Figma 정보를 추가

## 명명 규칙의 유연성

- **Figma 상의 이름과 Web 구현 이름은 달라도 무방**
- 예:
  - Figma: `Button/Primary` → Web: `PrimaryButton`
  - Figma: `Icon/Check` → Web: `CheckIcon`
- Web 구현에서는 React 및 TypeScript 명명 관습을 우선
- Figma 정보 주석이 있다면 이름이 달라도 동일 컴포넌트로 판정 가능

## 타이포그래피 토큰 사용

### 기본 원칙

**`text-[15px]`, `leading-[22.5px]` 같은 하드코딩 값 사용 금지.**
**`tailwind.config.ts`에 정의된 타이포그래피 토큰을 사용해야 함.**

- 토큰 존재 → 그대로 사용
- 토큰 미존재 → `tailwind.config.ts`에 추가 후 사용
- font-weight는 400 또는 600만 허용 (`font-medium` 사용 금지)

### 사용 예

```tsx
// ✅ 올바른 예
<h2 className="text-title-xlarge">프로젝트 선택</h2>
<p className="text-body-medium">설명 텍스트</p>
<label className="text-title-small">이름</label>
<button className="text-label-button-large">전송</button>

// ❌ 잘못된 예
<h2 className="text-[24px] leading-[36px] font-semibold">프로젝트 선택</h2>
<p className="text-sm">설명 텍스트</p>
```

### 자주 사용하는 패턴

| 사용 케이스            | 토큰                        |
| ----------------- | ------------------------- |
| 페이지 제목            | `text-title-xlarge`       |
| 섹션 제목             | `text-title-small`        |
| 본문                | `text-body-medium`        |
| 보조 텍스트            | `text-body-small`         |
| 폼 라벨              | `text-title-small`        |
| 에러 메시지            | `text-body-small`         |
| 태그/뱃지             | `text-label-tag`          |
| 버튼 (Large)        | `text-label-button-large` |
| 버튼 (Medium/Small) | `text-label-button-small` |

Figma 디자인의 font-size, line-height, font-weight를 확인하고
`tailwind.config.ts` 정의와 대조할 것.

---

## 폼 구현 가이드라인

> **Note:**
> 폼 라이브러리나 참조 파일은 프로젝트에 맞게 변경하십시오.
> 단, Schema(검증 정의)와 컴포넌트(UI)는 반드시 분리해야 합니다.
> 분리해두면 AI에 의한 컴포넌트 자동 수정 시 검증 로직에 대한 영향을 최소화할 수 있습니다.## 폼 구현 가이드라인

### 권장 구조

```
feature/
├── schema.ts      # Zod 등의 검증 정의
└── page.tsx       # UI 컴포넌트 (schema를 import하여 사용)
```

---

## 로직과 UI의 분리

### 기본 원칙

**JSX 내부에 복잡한 로직을 직접 작성하지 말고,**
**컴포넌트 상단에 핸들러 함수로 정의하여 로직과 UI를 분리합니다.**

### 복잡한 로직의 정의

다음 중 하나에 해당하면 핸들러 함수로 분리해야 합니다:

1. 3줄 이상의 인라인 콜백
2. 반복문이나 조건문 포함
   - `for`, `map`, `find`, `filter`, `if`
3. 데이터 변환·검색 포함
   - 배열 조작, 객체 탐색 등의 비즈니스 로직

### 推奨パターン: 名前付きハンドラー関数

### 권장 패턴: 이름 있는 핸들러 함수

```tsx
// ✅ 좋은 예: 핸들러 분리
export function UserSelector({ users }: Props) {
  const handleUserSelect = (userId: string) => {
    const selectedUser = users.find((user) => user.id === userId);

    if (selectedUser) {
      // 선택한 사용자의 세부정보 검색
      fetchUserDetails(selectedUser.id);
      // 폼에 값 설정
      setFormData(selectedUser);
    }
  };

  return (
    <Select onValueChange={handleUserSelect}>
      {users.map((user) => (
        <SelectItem key={user.id} value={user.id}>
          {user.name}
        </SelectItem>
      ))}
    </Select>
  );
}

// ❌ 나쁜 예: JSX 내부에 직접 로직 작성
export function UserSelector({ users }: Props) {
  return (
    <Select
      onValueChange={(userId) => {
        const selectedUser = users.find((user) => user.id === userId);

        if (selectedUser) {
          // 선택한 사용자의 세부정보 검색
          fetchUserDetails(selectedUser.id);
          // 폼에 값 설정
          setFormData(selectedUser);
        }
      }}
    >
      {users.map((user) => (
        <SelectItem key={user.id} value={user.id}>
          {user.name}
        </SelectItem>
      ))}
    </Select>
  );
}
```

### 예외

다음 경우 인라인 콜백 허용:

1. **1줄 수준의 단순 콜백**
   ```tsx
   <Button onClick={() => router.push(pagesPath.$url().pathname)}>
     홈으로
   </Button>
   ```

2. **props로 받은 콜백을 그대로 사용**
   ```tsx
   <Button onClick={onSubmit}>전송</Button>
   <Button onClick={onBack}>뒤로</Button>
   ```

---

## 전제 조건

### Figma 데이터 취득 전제

- **MCP 도구**: Figma Desktop 앱이 실행 중이어야 함
- **Figma 파일 키**:
  - 화면 디자인: `YOUR_DESIGN_FILE_KEY`
  - 공통 컴포넌트: `YOUR_LIBRARY_FILE_KEY`

**오류 발생 시**: 위의 파일 키를 사용하여 다시 시도하세요.
