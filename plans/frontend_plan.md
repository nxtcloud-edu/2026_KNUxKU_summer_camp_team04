# CodeTrace Frontend 개발 계획서

## 1. 목적

CodeTrace Frontend는 백준형 문제풀이 화면을 제공하는 데 그치지 않고, **학생의 Coding Trace를 수집하고 Agent가 선택한 학습 활동을 즉시 수행할 수 있게 만드는 학습 인터페이스**다.

Frontend의 핵심 책임은 세 가지다.

1. 학생이 문제를 풀 수 있는 안정적인 Web IDE 제공
2. `CODE_SNAPSHOT`, `RUN`, `SUBMIT`, `UNDO`, 학습 활동 응답 등의 Event 수집
3. Agent의 `WAIT`, `HINT`, `TRACE`, `PREDICT`, `DEBUG`, `VERIFY`를 서로 다른 학습 UI로 렌더링

핵심 사용자 흐름은 다음과 같다.

```text
문제 확인
→ 코드 작성
→ Run / Submit
→ 테스트 결과 확인
→ Trace Event 전송
→ Agent 판단 수신
→ 학습 Activity 수행
→ 원래 문제 복귀
→ 코드 수정 및 재실행
```

---

## 1.1 현재 상태와 API 규약

| 영역 | 상태 |
|---|---|
| Vite + React + TS 프로젝트 | 세팅 완료 |
| Monaco Editor / 문제 화면 | 구현 완료 |
| Pyodide 실행 | TRACE 학습 화면(`runTrace`)에만 쓰인다. **채점은 서버가 한다** |
| Backend 연동 | 구현 완료 — `traceClient.ts`, `useCodingTrace.ts` |
| Agent Panel / Activity UI | 부분 (`AiTutorPanel.tsx` 있음, 백엔드 미연결) |
| Process State Panel / Timeline | 미구현 (백엔드 API는 준비됨) |
| 로그인·회원가입 API 연결 | **미구현** — 화면만 있고 API를 안 부른다 |
| 교육자 대시보드 | 미구현 (백엔드 9개 엔드포인트 준비됨) |

Backend는 전부 준비되어 있다. **요청/응답 필드 규약은
[FRONTEND_INTEGRATION.md](FRONTEND_INTEGRATION.md)가 진실이고**, 이 문서는 화면 구성과
UX 설계를 다룬다. 서버를 띄우고 <http://localhost:8000/docs>를 열면 모든 스키마를
실제로 눌러볼 수 있다.

기억할 세 가지:

- **JSON은 전부 `snake_case`다.**
- 채점은 **서버가 한다.** `POST /sessions/{id}/run|submit` 한 번이 전부 처리한다.
- **거의 모든 API가 로그인을 요구한다.** `Authorization: Bearer <token>`
- 모든 이벤트에 `client_event_id`(`crypto.randomUUID()`)를 넣는다.

---

## 2. 권장 기술 스택

2일 MVP를 기준으로 다음 구성을 권장한다.

- React + TypeScript
- Vite
- Monaco Editor
- TanStack Query: 서버 상태 및 API 호출
- Zustand 또는 React Context: 현재 세션/Agent UI 상태
- Tailwind CSS 또는 기존 팀 UI 라이브러리
- `diff` 또는 `diff-match-patch`: 프론트 임시 diff 표시가 필요할 경우

Next.js 경험이 팀에 더 많다면 Next.js를 사용할 수 있으나, SSR 기능은 MVP 핵심이 아니므로 Vite가 더 단순하다.

---

## 3. Frontend 역할 분담

## FE 1 — Coding Environment Owner

담당:

- 문제 목록 및 문제 상세
- Monaco Editor
- Run / Submit / Reset
- Test Result UI
- 코드 snapshot 생성
- Event 발행
- Backend Judge 연동

## FE 2 — Learning Experience Owner

담당:

- Agent panel
- HINT / TRACE / PREDICT / DEBUG / VERIFY UI
- Activity 응답 제출
- Coding Timeline
- Agent State visualization
- Process Replay 또는 snapshot navigation

두 개발자는 공통 타입과 API client를 첫 시간에 함께 확정한다.

---

## 4. 화면 구조

## 4.1 문제풀이 Workspace

```text
┌───────────────────────────────────────────────────────┐
│ 문제 제목 / 개념 / 난이도                            │
├──────────────────────────┬────────────────────────────┤
│ 문제 설명                │ Monaco Editor              │
│ 예제                     │                            │
│ 제약 조건                │                            │
│                          │          [Run] [Submit]    │
├──────────────────────────┴────────────────────────────┤
│ Test Result                                           │
│ 3 / 5 Passed                                          │
├──────────────────────────┬────────────────────────────┤
│ Agent / Learning Panel   │ Coding Timeline            │
└──────────────────────────┴────────────────────────────┘
```

MVP는 한 화면에서 문제풀이, Agent 활동, Timeline을 확인할 수 있게 구성한다.

---

## 4.2 최소 페이지

### `/problems`

- 문제 목록
- 문제 제목
- 개념 태그
- 완료 여부

### `/problems/:problemId`

- 문제 설명
- Editor
- 실행 결과
- Agent panel
- Timeline

로그인·회원가입·마이페이지 화면은 구현됐다 (`LoginPage.tsx`, `SignupPage.tsx`, `MyPage.tsx`).
다만 **셋 다 백엔드 API를 부르지 않고 로컬 상태만 바꾼다.**
교수자 dashboard는 백엔드 9개 엔드포인트가 준비됐고 화면이 없다.

---

## 5. 핵심 컴포넌트

```text
App
└── ProblemWorkspace
    ├── ProblemDescription
    ├── CodeEditor
    ├── ExecutionControls
    ├── TestResultPanel
    ├── AgentPanel
    │   ├── WaitCard
    │   ├── HintCard
    │   ├── TraceActivity
    │   ├── PredictActivity
    │   ├── DebugActivity
    │   └── VerifyActivity
    ├── ProcessStatePanel
    └── CodingTimeline
```

---

## 6. Monaco Editor 기능

### P0 — 필수

- Python syntax highlighting
- starter code 로드
- 코드 변경 감지
- Run
- Submit
- Reset
- 현재 코드 유지
- 실행 중 버튼 비활성화
- 오류 메시지 표시

### P1 — 시간 여유 시

- Undo / Redo event 식별
- 변경 line highlight
- Agent가 언급한 코드 영역 highlight
- 특정 Activity 완료 후 원래 코드 상태 복구

### Event 처리

모든 keystroke를 서버에 전송하지 않는다.

```text
사용자 입력
→ 800ms debounce
→ CODE_SNAPSHOT 후보 생성
→ 의미 있는 변경이면 Backend 전송
```

다음 시점에는 즉시 snapshot을 전송한다.

- Run 직전
- Submit 직전
- Reset 직전
- 페이지 이탈 직전 가능한 범위에서

---

## 7. Event Collector

Frontend는 Sensor 역할을 한다. 이벤트의 교육적 의미는 Backend가 판단한다.

### 수집 이벤트

- `CODE_SNAPSHOT`
- `RUN`
- `SUBMIT`
- `UNDO`
- `RESET`
- `HINT_REQUEST`
- `ACTIVITY_OPENED`
- `ACTIVITY_RESPONSE`
- `SESSION_END`

`SESSION_START`는 **서버가 만든다.** `POST /sessions` 시점에 이미 기록되므로
클라이언트가 보내면 422다. `TEST_RESULT`도 마찬가지로 서버 전용이고,
채점은 `POST /sessions/{id}/run|submit` 으로 보낸다.

### 이벤트 형태

```ts
interface TraceEvent {
  type:
    | 'CODE_SNAPSHOT'
    | 'RUN'
    | 'SUBMIT'
    | 'UNDO'
    | 'RESET'
    | 'HINT_REQUEST'
    | 'ACTIVITY_OPENED'
    | 'ACTIVITY_RESPONSE'
    | 'SESSION_END';
  client_event_id: string;        // crypto.randomUUID() -- 필수
  client_timestamp?: string;
  payload?: Record<string, unknown>;
}

// 요청은 배치 전용. 단건도 1개짜리 배치로 보낸다.
interface EventBatch { events: TraceEvent[] }   // 최대 50개
```

`session_id`는 URL path에 들어가므로 body에 넣지 않는다.
`code_version`은 **서버가 할당한다.** 응답의 `current_code_version`을 받아서 쓴다.

### payload 규약

| type | payload |
|---|---|
| `CODE_SNAPSHOT` | `{ code: string }` — 필수. 없으면 422 |
| `ACTIVITY_OPENED` | `{ activity_id, activity_type }` |
| `ACTIVITY_RESPONSE` | `{ activity_id, result: 'CORRECT' \| 'INCORRECT' }` |
| 그 외 | `{}` |

`ACTIVITY_RESPONSE`의 `result`가 정확히 `"CORRECT"`여야 서버가 진전으로 인정한다.

### 전송 전략

- `RUN`, `SUBMIT`, `HINT_REQUEST`, Activity 응답은 즉시 전송
- `CODE_SNAPSHOT`은 800ms debounce
- 일반 이벤트는 최대 5개 또는 2초 단위로 batch
- 전송 실패 시 메모리 queue에 보관하고 재시도 — **중복은 서버가 거른다**
- 새로고침 대비 session id를 localStorage에 보관

Backend가 canonical source of truth이고, Frontend localStorage는 복구용이다.
코드 복구는 `GET /sessions/{id}`의 `current_code`로 한다.

### `client_event_id`가 없으면 안 되는 이유

재시도 큐가 있는 이상 중복 전송은 정상 동작이다. 이 키가 없으면 서버가 걸러낼 수 없고,
전송 실패 한 번이 `RUN 3/5`를 다섯 번 기록해 **한 번 실행한 학생에게 STUCK 판정**이 뜬다.

---

## 8. Run / Submit 흐름

```text
Run 클릭
→ 대기 중인 CODE_SNAPSHOT debounce를 강제 flush (await)
→ RUN 이벤트 전송
→ 브라우저(Pyodide)에서 채점
→ POST /sessions/{id}/results
→ Test Result 렌더링
→ Backend가 반환한 process_state / agent_decision 반영
```

**flush를 반드시 먼저 await 한다.** 서버는 "직전 실행 이후의 편집"을 코드 버전으로
잘라서 판단하는데, 스냅샷이 결과보다 늦게 도착하면 그 편집이 다음 결과의 창으로 밀려
판정이 한 칸씩 어긋난다. 도착 순서가 곧 진실이라 서버가 막을 방법이 없다.

```ts
async function handleRun(mode: 'run' | 'submit') {
  const { current_code_version } = await flushPendingSnapshot();
  await postEvents([{ type: mode.toUpperCase(), client_event_id: uuid(), payload: {} }]);

  const graded = await pyodideRunner.judge(editor.getValue(), mode);

  const res = await api.post(`/sessions/${sid}/results`, {
    mode,
    status: graded.status,          // ACCEPTED | WRONG_ANSWER | SYNTAX_ERROR | ...
    passed: graded.passed,
    total: graded.total,
    runtime_ms: graded.runtimeMs,
    failed_categories: graded.failedCategories ?? [],
    code_version: current_code_version,
    client_event_id: uuid(),
  });

  renderTestResult(res.event.payload);
  renderProcessState(res.process_state);
  if (res.agent_decision) renderAgent(res.agent_decision);
}
```

응답 예시:

```json
{
  "event": {
    "seq": 7,
    "type": "TEST_RESULT",
    "source": "CLIENT_JUDGE",
    "code_version": 4,
    "payload": { "mode": "run", "status": "WRONG_ANSWER", "passed": 3, "total": 5 }
  },
  "process_state": {
    "status": "STUCK",
    "trigger": "REPEATED_FAILURE",
    "triggered": true,
    "reason": "같은 코드 영역을 반복 수정했지만 테스트 결과가 동일합니다.",
    "evidence": ["동일 결과 3/5 ×3", "반복문 영역 ×2 반복 수정"],
    "cooldown_active": false
  },
  "agent_decision": null
}
```

`agent_decision`은 **trigger가 있을 때만 non-null**이다. `null`을 정상 케이스로 다룬다.

### 채점 에러를 0점으로 보내지 않는다

`SYNTAX_ERROR`를 `passed: 0`인 `WRONG_ANSWER`로 보내면 서버가 "+점수 진전"으로 읽어
막힌 학생을 방치한다. 러너가 던진 상태를 그대로 보낸다. 서버는 에러를 0점이 아니라
**"관측 없음"** 으로 취급한다.

Agent가 비동기로 늦어지면 `GET /sessions/{id}/process-state` 폴링으로 분리할 수 있다.
이 GET은 상태를 바꾸지 않으므로 3~5초 주기 폴링이 안전하다.

---

## 9. Test Result UI

학생에게 hidden test의 세부 입력은 공개하지 않는다.

### 표시 항목

- 상태: Accepted / Wrong Answer / Runtime Error / Syntax Error
- 통과 수: `3 / 5`
- public test 결과
- stdout/stderr
- 실행 시간

예:

```text
Wrong Answer
3 / 5 Tests Passed

✓ Basic case
✓ Empty list
✓ Single item
✕ Hidden test
✕ Hidden test
```

Agent 내부용 failed category는 학생 화면에 그대로 노출하지 않는다.

---

## 10. Agent Panel

일반 채팅창이 아니라 Agent Action별 UI를 제공한다.

## 10.1 WAIT

```text
현재 테스트 결과가 개선되고 있습니다.
지금은 개입하지 않고 조금 더 직접 시도하도록 기다리겠습니다.
```

WAIT은 화면을 방해하지 않도록 작은 상태 표시로 처리한다.

## 10.2 HINT

- 한 문장 또는 두 문장
- 접기/펼치기
- 정답 코드 직접 표시 금지

## 10.3 TRACE

```text
Iteration | i | total
----------|---|------
1         | □ | □
2         | □ | □
3         | □ | □
```

기능:

- 코드 snippet 표시
- 표 입력
- 제출
- 정오답 표시
- 다시 시도
- 원래 문제로 돌아가기

## 10.4 PREDICT

- 코드 표시
- 출력 예측 입력
- 제출 후 실제 결과와 비교

## 10.5 DEBUG

- 오류 코드 표시
- 반례 입력 또는 코드 수정 입력
- Run against activity API

## 10.6 VERIFY

- 자신의 현재 코드 일부 강조
- 설명형 질문
- 텍스트 답변
- 평가 결과: `UNDERSTANDING_CONFIRMED` 또는 `NEEDS_REVIEW`

---

## 11. Activity 렌더링 계약

Frontend는 Agent 자유 텍스트를 해석하지 않는다. `activity.type`을 기준으로 컴포넌트를 선택한다.

```ts
type Activity =
  | TraceActivityPayload
  | PredictActivityPayload
  | DebugActivityPayload
  | VerifyActivityPayload;
```

```ts
function LearningActivityRenderer({ activity }: { activity: Activity }) {
  switch (activity.type) {
    case 'TRACE':
      return <TraceActivity activity={activity} />;
    case 'PREDICT':
      return <PredictActivity activity={activity} />;
    case 'DEBUG':
      return <DebugActivity activity={activity} />;
    case 'VERIFY':
      return <VerifyActivity activity={activity} />;
  }
}
```

Agent 응답이 invalid할 경우:

```text
학습 활동을 불러오지 못했습니다.
현재 문제로 돌아가 계속 시도할 수 있습니다.
```

으로 안전하게 폴백한다.

---

## 12. Process State Panel

대회 데모에서는 Agent 판단을 눈에 보이게 해야 한다.

```text
Learning Process State

State
STUCK

Evidence
• Same score 3/5 ×3
• Loop boundary edited ×4
• No improvement for 92 sec

Agent Decision
TRACE
```

실제 학생 서비스에서는 evidence를 간략화할 수 있지만, 데모 모드에서는 전체를 표시한다.

**`reason`과 `evidence[]`는 서버가 한국어로 만들어 보낸다.** 프론트에서 문자열을
조립하지 않는다 — 그대로 `<ul>`로 뿌리면 된다. 문자열이 백엔드 테스트로 커버되고 있고,
Agent도 같은 문장을 재사용한다.

### 상태 색상 — 6종 전부 매핑한다

| `status` | 뜻 | 톤 |
|---|---|---|
| `PROGRESSING` | 잘 나아가는 중 | 긍정 |
| `PRODUCTIVE_STRUGGLE` | 고전 중이지만 스스로 될 여지 | 중립 |
| `POSSIBLE_STUCK` | 막혔을 가능성 | 주의 |
| `STUCK` | 막힘 | 경고 |
| `UNDERSTANDING_UNCERTAIN` | 통과했지만 이해 근거 부족 | 확인 필요 |
| `HELP_REQUESTED` | 학생이 직접 요청 | 정보 |

색상만으로 상태를 전달하지 않고 label과 설명을 함께 표시한다.

### `status`와 `trigger`는 별개다

`status: "STUCK"`인데 `trigger: null`인 상태가 **정상적으로 존재한다.** 직전에 이미
개입해서 대기 중(`cooldown_active: true`)인 경우다.

데모에서 이걸 그대로 보여주면 좋다 — 시스템이 막힘을 *알면서도* 다시 끼어들지 않기로
*선택*했다는 게 드러난다.

```text
State      STUCK
Decision   대기 중 (직전 개입 후 18초)
```

---

## 13. Coding Timeline

### 표시 이벤트

- Start
- Code snapshot
- Run result
- Error
- Agent trigger
- Activity 시작/완료
- Accepted

```text
START
  │
  ├─ RUN 2/5
  ├─ EDIT
  ├─ RUN 3/5
  ├─ EDIT
  ├─ RUN 3/5
  ├─ AGENT: TRACE
  ├─ TRACE SUCCESS
  ├─ RUN 5/5
  └─ ACCEPTED
```

MVP에서는 세로 timeline으로 충분하다.

`GET /sessions/{id}/timeline`이 **한국어 label까지 만들어서** 준다. `kind`로 아이콘만
매핑하면 된다.

```jsonc
{
  "entries": [
    { "seq": 1, "kind": "START", "label": "START" },
    { "seq": 2, "kind": "EDIT",  "label": "반복문 영역 수정 (4줄)", "code_version": 2 },
    { "seq": 3, "kind": "RUN",   "label": "RUN 3/5" },
    { "seq": 8, "kind": "AGENT", "label": "AGENT TRIGGER: REPEATED_FAILURE" }
  ],
  "summary": { "edit_count": 3, "run_count": 3, "trigger_count": 1,
               "best_passed": 3, "total_seconds": 142 }
}
```

`kind` 11종: `START` `EDIT` `RUN` `SUBMIT` `ERROR` `HINT` `UNDO` `RESET` `AGENT`
`ACTIVITY` `END`.

`collapse=true`(기본)는 연속 EDIT을 하나로 합친다. debounce가 두 Run 사이에 만든
스냅샷 여러 개를 한 줄로 보여준다. Process Replay에는 `collapse=false`를 쓴다.

### Process Replay — P1

- Timeline 항목 클릭
- 해당 code snapshot 표시 — `GET /sessions/{id}/snapshots/{version}`
- 이전/다음 이동
- diff 하이라이트 — `.../diff?from=`이 `changed_lines`와 `unified_diff`를 준다
- 해당 시점의 test result와 Agent action 표시

실제 동영상 재생이 아니라 snapshot navigation으로 구현한다. **백엔드 API는 준비되어 있다.**

---

## 14. 상태 관리

### 서버 상태

TanStack Query:

- 문제 목록
- 문제 상세
- 세션
- Run 결과
- Timeline
- Activity

### 클라이언트 상태

Zustand 또는 Context:

```ts
interface WorkspaceState {
  sessionId: string | null;
  code: string;
  codeVersion: number;
  activeActivity: Activity | null;
  agentDecision: AgentDecision | null;
  pendingEvents: TraceEvent[];
}
```

코드와 Activity 상태를 지나치게 전역화하지 않는다.

---

## 15. API Client 목록

```text
GET  /problems
GET  /problems/{problem_id}
POST /sessions
GET  /sessions/{session_id}
POST /sessions/{session_id}/finish
POST /sessions/{session_id}/events           배치 전용
POST /sessions/{session_id}/results          ★ 채점 결과
GET  /sessions/{session_id}/process-state    폴링 안전
GET  /sessions/{session_id}/timeline
GET  /sessions/{session_id}/snapshots/{version}/diff   Process Replay용
```

아직 503을 반환하는 것 (서버 judge가 붙으면 켜진다):

```text
POST /sessions/{session_id}/run
POST /sessions/{session_id}/submit
```

아직 없는 것: `/activities/*`.

### 에러 처리

우리가 던지는 에러는 전부 이 봉투를 쓴다.

```json
{ "detail": { "code": "SESSION_NOT_FOUND", "message": "...", "context": {} } }
```

FastAPI 검증 실패(422)만 네이티브 배열 형태다. 분기는 `Array.isArray(body.detail)` 한 줄.

```ts
class ApiError extends Error {
  status: number;
  code?: string;        // SESSION_NOT_FOUND, SERVER_ONLY_EVENT, ...
  detail?: unknown;
}
```

`SESSION_NOT_FOUND`(404)는 백엔드가 DB를 지웠을 때 흔하다. localStorage를 비우고
새 세션을 만들면 된다.

### CORS

`http://localhost:5173`, `http://127.0.0.1:5173`이 열려 있다. 포트가 다르면 백엔드
`.env`의 `CORS_ORIGINS`에 추가를 요청한다.

---

## 16. UX 원칙

- Agent가 매번 화면을 가로막지 않는다.
- `WAIT`은 방해하지 않는 상태 표시로 제공한다.
- Activity가 열려도 원래 코드는 보존한다.
- 학습 Activity 완료 후 원래 문제로 쉽게 돌아갈 수 있어야 한다.
- 로딩 중에는 Agent가 무엇을 하는지 짧게 표시한다.
- 학생을 부정행위자로 단정하는 문구를 사용하지 않는다.
- 큰 코드 변화는 `이해 확인이 필요함`으로 표현한다.
- 모바일 대응은 MVP 우선순위에서 제외하고 데스크톱에 집중한다.

---

## 17. 실패 및 복구 처리

### Backend 연결 실패

- 현재 코드는 localStorage에 보존
- Run 실패 안내
- 재시도 버튼

### Agent 실패

- Judge 결과는 정상 표시
- Agent panel만 비활성화
- 학생은 계속 문제를 풀 수 있음

### Activity 제출 실패

- 학생 입력 보존
- 재전송 가능

### 페이지 새로고침

- session id와 code 복구
- Backend에서 timeline 재조회

---

## 18. Frontend 테스트

### 필수 테스트

- 문제와 starter code 렌더링
- Run 성공/실패 표시
- debounce snapshot 전송
- Activity type별 렌더링
- TRACE 답변 제출
- Agent `WAIT` 렌더링
- API 실패 시 코드 보존

### E2E 데모 테스트

1. `2/5 → 3/5 → 4/5`: WAIT 표시
2. `3/5 → 3/5 → 3/5`: TRACE 표시
3. TRACE 성공 후 원래 Editor 복귀
4. 대규모 코드 변경 후 VERIFY 표시

---

## 19. 2일 개발 일정

## Day 1 시작 1시간

두 FE 개발자 공동:

- API types 확정
- Event schema 확정
- Agent action/activity schema 확정
- layout wireframe 확정

## Day 1 오전

### FE 1

- React/Vite 프로젝트 세팅
- 문제 화면
- Monaco Editor
- Run 버튼
- mock Judge 연동

### FE 2

- Agent panel shell
- fake JSON 기반 HINT/TRACE/PREDICT 렌더링
- Process State panel

## Day 1 오후

### FE 1

- 실제 Run API 연결
- Test Result UI
- Event Collector
- snapshot debounce

### FE 2

- TRACE/PREDICT 입력 및 제출
- Timeline
- Agent decision API 연결

### Day 1 종료 기준

```text
Editor → Run → Judge Result → Trigger → TRACE UI
```

가 한 번 끝까지 동작해야 한다.

## Day 2 오전

### FE 1

- Submit/Reset
- error handling
- session 복구
- UX 정리

### FE 2

- DEBUG/VERIFY
- Activity 결과 UI
- Timeline 개선
- snapshot replay P1

## Day 2 오후

- 데모 시나리오 3개 고정
- 로딩/오류 메시지 정리
- 발표용 demo mode
- Agent evidence panel
- 불필요 기능 제거 및 QA

발표 3~4시간 전부터 신규 기능 개발을 중단한다.

---

## 20. 완료 기준

Frontend MVP는 다음 조건을 만족해야 한다.

- [x] 문제 하나 이상이 정상 표시됨
- [x] Monaco에서 Python 코드 작성 가능
- [x] Run 결과가 표시됨 (브라우저 Pyodide)
- [x] Coding snapshot과 Run event가 Backend에 기록됨
- [ ] Agent의 `WAIT`, `HINT`, `TRACE`, `PREDICT`를 화면에 표시 가능
- [ ] TRACE 또는 PREDICT 답변 제출 가능
- [ ] Activity 이후 원래 문제로 복귀 가능
- [ ] Coding Timeline에서 Agent 개입 지점을 확인 가능
- [ ] Agent API가 실패해도 Judge 기능은 계속 사용 가능

가장 시급한 것은 **로그인 API 연결**이다. 지금 `LoginPage`가 입력값을 아무 데도
보내지 않아서, 백엔드에 붙이면 `POST /sessions`부터 401이 나고 Coding Trace와
채점이 전부 멈춘다. 계약은 [FRONTEND_INTEGRATION.md](FRONTEND_INTEGRATION.md) §0에 있다.

Frontend가 증명해야 할 핵심 메시지는 다음과 같다.

> **CodeTrace는 채팅창을 붙인 Online Judge가 아니라, 학생의 문제 해결 과정에 따라 학습 화면 자체가 바뀌는 프로그래밍 학습 환경이다.**
