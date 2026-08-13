# 프론트엔드 연동 가이드

백엔드가 프론트에 요구하는 계약. **필드 이름과 요청/응답 모양은 이 문서가 진실이다.**
화면 구성과 UX 설계는 [frontend_plan.md](frontend_plan.md)를 본다.

서버 띄우고 <http://localhost:8000/docs> 를 열면 아래 모든 스키마를 실제로 눌러볼 수 있다.

```bash
cd backend && uvicorn app.main:app --reload --port 8000 --workers 1
```

---

## 1. 30초 요약

- **JSON은 전부 `snake_case`다.** 계획서의 `camelCase` TS 인터페이스를 그대로 쓰면 안 된다.
- 이벤트는 **배치 전용** — 단건도 `{"events": [...]}`로 감싼다.
- 모든 이벤트에 **`client_event_id`를 반드시 넣는다** (`crypto.randomUUID()`).
- 채점은 오늘 브라우저(Pyodide)가 하고, 결과는 `POST /sessions/{id}/results`로 보낸다.
- **Run/Submit은 "스냅샷 먼저 보내고 → 채점 → 결과 전송"** 순서를 지켜야 한다 (§5).

---

## 2. 반드시 지켜야 할 5가지

깨지면 서버가 에러를 내는 게 아니라 **조용히 틀린 판단**을 한다. 그래서 여기 따로 모았다.

### ① `client_event_id`는 선택이 아니다

```ts
{ type: "RUN", client_event_id: crypto.randomUUID(), payload: {} }
```

전송 실패 시 재시도 큐를 두게 되는데, 가장 흔한 실패는 *"서버는 저장했는데 응답이 유실되어 클라이언트가 재시도"* 다. 이 키가 없으면 서버가 중복을 걸러낼 수 없고, `RUN 3/5`가 다섯 번 기록되어 **한 번 실행한 학생에게 "막힘" 판정이 뜬다.**

키가 있으면 서버가 알아서 걸러내고 `duplicate_client_event_ids`에 담아 알려준다. 재시도는 안전하다.

### ② Run/Submit 직전에 대기 중인 스냅샷을 flush 한다

서버는 "직전 실행 이후의 편집"을 코드 버전으로 잘라서 판단한다. debounce 타이머가 안 끝난 상태로 Run을 누르면 스냅샷이 결과보다 **늦게** 도착하고, 그 편집이 다음 결과의 창으로 밀려 판정이 한 칸씩 어긋난다.

서버는 이걸 막을 방법이 없다 — 도착 순서가 곧 진실이다. §5에 구현 코드가 있다.

### ③ `code_version`은 서버가 준다

프론트는 절대 지어내지 않는다. `POST /events` 응답의 `current_code_version`을 받아서 다음 `POST /results`에 실어 보낸다. 생략하면 서버가 최신 버전으로 추정하는데, 그 사이 편집이 하나 끼면 어긋난다.

### ④ 서버 전용 이벤트는 보내면 422

`SESSION_START`, `TEST_RESULT`, `AGENT_TRIGGER`, `AGENT_INTERVENTION`, `SYNTAX_ERROR`, `RUNTIME_ERROR` — 전부 서버가 만든다. 특히 계획서가 수집 목록에 넣어둔 **`SESSION_START`를 보내면 422**다. `POST /sessions` 응답 시점에 이미 만들어져 있다.

### ⑤ `GET`은 폴링해도 안전하다

`/process-state`를 몇 초마다 불러도 상태가 바뀌지 않는다. 의도된 설계다 — 마음껏 폴링해라.

---

## 3. 세션 생명주기

### 시작

```ts
const r = await fetch(`${API}/sessions`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ problem_id: "func_sum_list", user_id: "demo-user" }),
});
const s = await r.json();
localStorage.setItem("session_id", s.session_id);
editor.setValue(s.current_code);   // 문제 템플릿이 이미 들어 있다
```

응답 (`201`):

```jsonc
{
  "session_id": "sess_699b671f0ece44199bfd220977ff12f8",
  "user_id": "demo-user",
  "problem_id": "func_sum_list",
  "status": "SOLVING",
  "started_at": "2026-08-13T02:11:04Z",
  "finished_at": null,
  "last_code_version": 1,
  "last_event_seq": 1,
  "current_code": "def sum_list(arr):\n    # 여기에 코드를 작성하세요\n    pass",
  "current_code_version": 1
}
```

서버가 `SESSION_START` 이벤트와 **템플릿 스냅샷 v1을 이미 만들어놨다.** 시작하자마자 `CODE_SNAPSHOT`을 보낼 필요 없다.

### 새로고침 복구

```ts
const id = localStorage.getItem("session_id");
const s = await fetch(`${API}/sessions/${id}`).then(r => r.json());
editor.setValue(s.current_code);
```

`GET /sessions/{id}`가 `current_code`를 함께 준다. 왕복 한 번이면 끝난다. **백엔드가 진실이고 localStorage는 세션 id 보관용이다.**

### 종료

```ts
await fetch(`${API}/sessions/${id}/finish`, { method: "POST" });
```

멱등이라 여러 번 불러도 된다. 종료 후에도 이벤트는 거부되지 않고 `session_finished: true` 플래그와 함께 수락된다 (`/finish` 직후 큐가 비워지는 정상 상황을 에러로 만들지 않기 위해서다).

---

## 4. 이벤트 전송 정책 — 언제 무엇을 보내나

**주기적으로 보내는 게 아니라 행동 기반이다.** 세 채널로 나뉜다.

| 채널 | 시점 | 이벤트 |
|---|---|---|
| **debounce 800ms** | 타이핑이 멈추면 | `CODE_SNAPSHOT` |
| **즉시** (await) | Run · Submit · Reset 직전, 힌트 클릭, Activity 응답 | `CODE_SNAPSHOT` flush + `RUN` / `SUBMIT` / `HINT_REQUEST` / `ACTIVITY_RESPONSE` |
| **배치** (2초 또는 5개) | 그 외 | `UNDO`, `RESET`, `ACTIVITY_OPENED` |

강제 flush 시점: **Run / Submit / Reset 직전**, **페이지 이탈 직전**(`visibilitychange` → `hidden`에서 `navigator.sendBeacon`).

### 이벤트별 payload

| type | payload | 비고 |
|---|---|---|
| `CODE_SNAPSHOT` | `{ "code": "..." }` | **`code` 필수.** 없으면 422 `MISSING_SNAPSHOT_CODE` |
| `RUN` | `{}` | 실행 *요청*. 결과는 별도(§5) |
| `SUBMIT` | `{}` | 제출 *요청* |
| `UNDO` | `{}` | |
| `RESET` | `{}` | 템플릿으로 되돌릴 때. 직후 `CODE_SNAPSHOT`도 보낸다 |
| `HINT_REQUEST` | `{}` | **cooldown을 무시하고 즉시 개입을 발화시킨다.** 지연 없이 보낼 것 |
| `ACTIVITY_OPENED` | `{ "activity_id": "...", "activity_type": "..." }` | |
| `ACTIVITY_RESPONSE` | `{ "activity_id": "...", "result": "CORRECT" \| "INCORRECT" }` | **`result`가 정확히 `"CORRECT"`** 여야 서버가 진전으로 인정한다 |
| `SESSION_END` | `{}` | |

### 코드는 스냅샷으로만 보낸다

`CODE_SNAPSHOT`의 `payload.code`는 서버가 별도 테이블로 옮기고 이벤트 payload에서는 **지운다.** 다른 이벤트에 코드를 실어 보내지 마라 — 저장소가 둘이 되고 `GET /events`가 메가바이트를 뱉는다.

직전 스냅샷과 바이트가 완전히 같으면 새 버전을 만들지 않는다(`deduplicated: true`). undo/redo가 만드는 no-op 편집은 서버가 알아서 흡수하니 프론트가 비교할 필요 없다.

### 요청 / 응답

```http
POST /sessions/{session_id}/events
```

```jsonc
{
  "events": [
    {
      "type": "CODE_SNAPSHOT",
      "client_event_id": "8f14e45f-ceea-467a-9f6b-2c1e3d4a5b6c",
      "client_timestamp": "2026-08-13T02:11:09.412Z",   // 선택
      "payload": { "code": "def sum_list(arr):\n    total = 0\n..." }
    }
  ]
}
```

배치는 **최소 1개, 최대 50개.**

```jsonc
// 201
{
  "accepted": [ { "event_id": "evt_...", "seq": 2, "type": "CODE_SNAPSHOT",
                  "source": "CLIENT", "code_version": 2, "payload": { ... },
                  "server_timestamp": "2026-08-13T02:11:09Z" } ],
  "duplicate_client_event_ids": [],
  "current_code_version": 2,     // ← 다음 POST /results에 실어 보낼 값
  "last_event_seq": 2,
  "session_finished": false
}
```

`accepted[].payload`에는 코드 대신 diff 요약이 담겨 온다 — `change_ratio`, `changed_lines`, `primary_region`, `summary`. 에디터에서 변경 줄을 하이라이트할 때 그대로 쓰면 된다.

---

## 5. Run / Submit 흐름 ★

가장 중요한 부분이다. **flush → 채점 → 결과 전송** 순서를 지켜야 한다.

```ts
async function handleRun(mode: "run" | "submit") {
  // 1. 대기 중인 debounce 스냅샷을 강제로 비운다. 반드시 await.
  const { current_code_version } = await flushPendingSnapshot();

  // 2. 실행 "요청" 이벤트 (선택이지만 타임라인이 예뻐진다)
  await postEvents([{ type: mode.toUpperCase(), client_event_id: uuid(), payload: {} }]);

  // 3. 브라우저에서 채점
  const graded = await pyodideRunner.judge(editor.getValue(), mode);

  // 4. 결과 전송 → 여기서 백엔드 파이프라인 전체가 돈다
  const res = await fetch(`${API}/sessions/${sid}/results`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mode,                              // "run" | "submit"
      status: graded.status,             // ACCEPTED | WRONG_ANSWER | SYNTAX_ERROR | ...
      passed: graded.passed,
      total: graded.total,
      runtime_ms: graded.runtimeMs,
      message: graded.message ?? null,
      failed_categories: graded.failedCategories ?? [],
      code_version: current_code_version,   // ← 1번에서 받은 값
      client_event_id: uuid(),
    }),
  }).then(r => r.json());

  renderTestResult(res.event.payload);
  renderProcessState(res.process_state);
  if (res.agent_decision) renderAgent(res.agent_decision);
}
```

### `status`에 넣을 값

| 값 | 언제 | 점수로 세나 |
|---|---|---|
| `ACCEPTED` | 전부 통과 | ○ |
| `WRONG_ANSWER` | 일부/전부 오답 | ○ |
| `SYNTAX_ERROR` | 파싱 실패 | ✗ 관측 없음으로 처리 |
| `RUNTIME_ERROR` | 실행 중 예외 | ✗ |
| `TIME_LIMIT` | 시간 초과 | ✗ |
| `INTERNAL_ERROR` | 러너 자체 실패 | ✗ |

**에러 상태를 `passed: 0`인 `WRONG_ANSWER`로 보내지 마라.** 서버는 에러를 "0점"이 아니라 **"관측 없음"** 으로 취급한다. 오타 한 번을 0점으로 세면 `3/5 → 오타 → 3/5`가 "+3점 진전"으로 읽혀서 명백히 막힌 학생이 방치된다. 러너가 실제로 던진 상태를 그대로 보내면 된다.

제약: `0 ≤ passed ≤ total ≤ 100`. 어기면 422.

### 응답

```jsonc
// 201
{
  "event": { "event_id": "evt_...", "seq": 7, "type": "TEST_RESULT",
             "source": "CLIENT_JUDGE", "code_version": 4,
             "payload": { "mode": "run", "status": "WRONG_ANSWER",
                          "passed": 3, "total": 5, "runtime_ms": 21,
                          "judge": "pyodide" } },

  "process_state": { /* §6 */ },
  "agent_decision": null        // trigger가 있을 때만 채워진다
}
```

---

## 6. Process State 소비하기

`POST /results` 응답에 이미 들어 있다. 데모 패널을 따로 갱신하고 싶으면 `GET /sessions/{id}/process-state`를 **3~5초 주기로 폴링**하면 된다 (안전하다).

```jsonc
{
  "session_id": "sess_...",
  "status": "STUCK",
  "trigger": "REPEATED_FAILURE",
  "triggered": true,
  "reason": "같은 코드 영역을 반복 수정했지만 테스트 결과가 동일합니다.",
  "evidence": [
    "동일 결과 3/5 ×3",
    "반복문 영역 ×2 반복 수정",
    "최근 점수 3 → 3 → 3"
  ],
  "cooldown_active": false,
  "cooldown_remaining_seconds": 0,
  "features": { "run_count": 3, "same_result_count": 3, "progress_delta": 0, ... },
  "evaluated_at": "2026-08-13T02:12:40Z"
}
```

**`reason`과 `evidence`는 서버가 한국어로 만들어 보낸다.** 프론트에서 문자열을 조립하지 마라 — 그냥 `<ul>`로 뿌리면 된다. 문자열이 백엔드 테스트로 커버되고 있고, Agent도 같은 문장을 쓴다.

### `status` 6종

| 값 | 뜻 | UI 톤 |
|---|---|---|
| `PROGRESSING` | 잘 나아가는 중 | 중립 / 초록 |
| `PRODUCTIVE_STRUGGLE` | 고전 중이지만 스스로 될 여지 | 노랑 |
| `POSSIBLE_STUCK` | 막혔을 가능성 | 주황 |
| `STUCK` | 막힘 | 빨강 |
| `UNDERSTANDING_UNCERTAIN` | 통과했지만 이해 근거 부족 | 보라 |
| `HELP_REQUESTED` | 학생이 직접 요청 | 파랑 |

### `trigger` 4종 (`null`이면 개입 없음)

`HELP_REQUESTED` · `REPEATED_FAILURE` · `NO_PROGRESS` · `UNDERSTANDING_UNCERTAIN`

**`status`와 `trigger`는 별개다.** `status: "STUCK"` 인데 `trigger: null` 인 상태가 정상적으로 존재한다 — 직전에 이미 개입해서 대기 중(`cooldown_active: true`)인 경우다. *"막힌 걸 알지만 지금은 끼어들지 않는다"* 를 그대로 보여주면 데모에서 잘 먹힌다.

### `agent_decision`

`trigger`가 있을 때만 non-null. 오늘은 stub이라 항상 `action: "WAIT"`이다.

```jsonc
{ "state": "STUCK", "concept": "loop_range", "action": "WAIT",
  "reason": "...", "activity": null }
```

`action`: `WAIT` · `HINT` · `TRACE` · `PREDICT` · `DEBUG` · `VERIFY`.
**6종 전부에 대한 렌더링을 미리 준비해두면** LLM이 붙는 날 프론트는 손댈 게 없다.

---

## 7. 나머지 엔드포인트

### 문제

```http
GET /problems                 → 목록 (테스트 데이터 없음)
GET /problems/{problem_id}    → 상세
```

```jsonc
{
  "problem_id": "func_sum_list",
  "title": "...", "description": "...", "difficulty": "...",
  "concepts": ["loop", "accumulator"],
  "function_name": "sum_list",
  "check_type": "function_call",
  "code_template": "def sum_list(arr):\n    # 여기에 코드를 작성하세요\n    pass",
  "public_test_cases": [ { "input": [[1,2,3]], "expected": 6, "category": "basic" } ],
  "hidden_test_case_count": 3,
  "hidden_test_categories": ["negative_numbers", "boundary_case", "empty_list"]
}
```

**hidden test의 input/expected는 응답에 담길 필드 자체가 없다.** 개수와 카테고리만 노출되니 "숨은 테스트 3개: 음수, 경계값, 빈 리스트" 같은 힌트 UI를 만들 수 있다. Pyodide는 `public_test_cases`만 채점하게 된다 (`mode: "run"`).

### 타임라인

```http
GET /sessions/{id}/timeline?collapse=true
```

```jsonc
{
  "entries": [
    { "seq": 1, "kind": "START",  "label": "START", "at": "..." },
    { "seq": 2, "kind": "EDIT",   "label": "반복문 영역 수정 (4줄)", "code_version": 2 },
    { "seq": 3, "kind": "RUN",    "label": "RUN 3/5" },
    { "seq": 8, "kind": "AGENT",  "label": "AGENT TRIGGER: REPEATED_FAILURE" }
  ],
  "summary": { "edit_count": 3, "run_count": 3, "trigger_count": 1,
               "best_passed": 3, "total_seconds": 142 }
}
```

`label`도 서버가 한국어로 만든다. `kind`는 11종(`START` `EDIT` `RUN` `SUBMIT` `ERROR` `HINT` `UNDO` `RESET` `AGENT` `ACTIVITY` `END`)이라 아이콘 매핑만 하면 된다.

### 스냅샷 / diff

```http
GET /sessions/{id}/snapshots                      → 요약 목록
GET /sessions/{id}/snapshots/{version}            → code 포함 전체
GET /sessions/{id}/snapshots/{version}/diff?from= → unified_diff 포함
```

"학생의 코드 변천사" 리플레이 UI에 쓸 수 있다.

### 아직 안 붙은 것

```http
POST /sessions/{id}/run     → 503 JUDGE_UNAVAILABLE
POST /sessions/{id}/submit  → 503 JUDGE_UNAVAILABLE
POST /agent/decide          → 200, 항상 action: "WAIT"
```

**둘 다 최종 스키마로 OpenAPI에 이미 올라가 있다.** 서버 judge가 붙는 날 프론트는 `POST /results` 호출을 `POST /run`으로 바꾸고 자체 채점을 지우기만 하면 된다. 응답 모양(`ResultIngestResponse`)이 동일하다.

---

## 8. 에러 처리

우리가 던지는 에러는 전부 이 봉투를 쓴다:

```jsonc
{ "detail": { "code": "SESSION_NOT_FOUND", "message": "...", "context": { ... } } }
```

FastAPI의 검증 실패(422)만 네이티브 배열 형태를 유지한다:

```jsonc
{ "detail": [ { "loc": ["body", "events", 0, "type"], "msg": "...", "type": "..." } ] }
```

둘 다 `detail` 아래라 분기는 `Array.isArray(body.detail)` 한 줄이면 된다.

| code | HTTP | 언제 |
|---|---|---|
| `SESSION_NOT_FOUND` | 404 | 세션 id가 없다 (DB를 지웠을 때 흔함 → localStorage 비우고 새 세션) |
| `PROBLEM_NOT_FOUND` | 404 | |
| `SNAPSHOT_NOT_FOUND` | 404 | |
| `SERVER_ONLY_EVENT` | 422 | 서버 전용 타입을 보냈다 (§2-④) |
| `MISSING_SNAPSHOT_CODE` | 422 | `CODE_SNAPSHOT`에 `payload.code`가 없다 |
| `INVALID_CODE_VERSION` | 422 | 서버가 아직 모르는 버전을 보냈다 |
| `JUDGE_UNAVAILABLE` | 503 | 서버 judge 미연결 (정상) |
| `AGENT_UNAVAILABLE` | 503 | LLM 미연결 (정상) |

**Agent 호출이 실패해도 채점 결과는 반드시 돌아온다.** `POST /results`가 내부에서 삼킨다 — "실행했는데 아무 반응이 없는" 상황은 만들지 않는다. `agent_decision: null`을 정상 케이스로 다뤄라.

---

## 9. 구현 체크리스트

- [ ] 모든 요청/응답 필드를 `snake_case`로
- [ ] 모든 이벤트에 `client_event_id = crypto.randomUUID()`
- [ ] 전송 실패 → 메모리 큐 보관 → 재시도 (중복은 서버가 거른다)
- [ ] `CODE_SNAPSHOT` 800ms debounce
- [ ] **Run/Submit/Reset 직전 `await flushPendingSnapshot()`**
- [ ] `POST /events` 응답의 `current_code_version`을 보관 → `POST /results`에 전달
- [ ] 채점 에러를 `passed: 0`이 아니라 실제 `status`로 전송
- [ ] `SESSION_START` / `TEST_RESULT`를 `POST /events`로 보내지 않기
- [ ] `session_id`를 localStorage에, 코드 복구는 `GET /sessions/{id}`로
- [ ] `process_state.reason` / `evidence`를 가공 없이 렌더
- [ ] `status` 6종 + `trigger` 4종 + `agent_decision.action` 6종 UI 매핑
- [ ] `agent_decision: null`을 정상으로 처리
- [ ] 페이지 이탈 시 `sendBeacon`으로 마지막 flush
- [ ] `.env`에 `VITE_API_BASE=http://localhost:8000`

CORS는 `http://localhost:5173`, `http://127.0.0.1:5173`이 열려 있다. 포트가 다르면 백엔드 `.env`의 `CORS_ORIGINS`에 추가해달라고 요청할 것.

---

## 10. 이름이 정리된 항목

구현하면서 확정한 이름들. 아래 왼쪽 열은 초기 논의에서 쓰이던 표현이라 아직 코드나 메모에
남아 있을 수 있는데, 그대로 보내면 **422가 난다.**

| 예전 표현 | 실제 | 왜 |
|---|---|---|
| `sessionId`, `clientTimestamp`, `codeVersion` (camelCase) | **`session_id`, `client_timestamp`, `code_version`** | API 전체가 snake_case로 통일 |
| `RUN_REQUESTED` / `SUBMIT_REQUESTED` | **`RUN` / `SUBMIT`** | "누가 보냈나"는 타입 이름이 아니라 서버의 `source` 컬럼에 기록 |
| `LEARNING_ACTIVITY_RESPONSE` | **`ACTIVITY_RESPONSE`** | 3개 계획 문서 중 2개가 짧은 쪽으로 합의 |
| `CODE_CHANGE` | **`CODE_SNAPSHOT`** | 저장 산출물의 이름과 일치 |
| 수집 목록에 `SESSION_START` 포함 | **보내면 422** | `POST /sessions`가 이미 만든다 |
| 채점 결과는 `POST /run` | **`POST /results`** | 오늘은 브라우저가 채점한다. `/run`은 서버 judge용으로 예약 |
| 이벤트 단건 전송 | **배치 전용** (`{"events": [...]}`) | 단건은 1개짜리 배치 |

전송 시점 정책(800ms debounce, 즉시/배치 구분, 재시도 큐)은 [frontend_plan.md](frontend_plan.md) §6~7 그대로다.

---

## 11. 막히면

- <http://localhost:8000/docs> — 모든 스키마를 실제로 눌러볼 수 있다
- `python -m scripts.seed_demo` — 4개 데모 세션(PROGRESSING / STUCK / UNDERSTANDING_UNCERTAIN / RECOVERED)을 만들어준다. 프론트 붙이기 전에 응답 모양을 보려면 이게 제일 빠르다
- 설계 근거와 함정은 [../backend/README.md](../backend/README.md)
- 파이프라인 전체 그림은 [backend_plan.md](backend_plan.md)
