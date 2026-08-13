# 프론트엔드 연동 가이드

백엔드가 프론트에 요구하는 계약. **필드 이름과 요청/응답 모양은 이 문서가 진실이다.**
화면 구성과 UX 설계는 [frontend_plan.md](frontend_plan.md)를 본다.

서버 띄우고 <http://localhost:8000/docs> 를 열면 아래 모든 스키마를 실제로 눌러볼 수 있다.

```bash
cd backend && uvicorn app.main:app --reload --port 8000 --workers 1
```

---

## 0. 인증

> **연동 완료.** 로그인/회원가입 화면은 `auth.ts`를 통해 실제 API를 부르고,
> `api.ts`의 `apiRequest`가 모든 요청에 `Authorization: Bearer`를 붙인다.
> 토큰 만료(401)는 `api.onUnauthorized`가 잡아 토큰을 폐기하고 로그인 화면으로 보낸다.
> 아래 본문은 계약 원문이라 그대로 둔다.

### 토큰 얻기

```http
POST /auth/signup   { "name": "홍길동", "email": "a@b.com", "password": "password123",
                      "role": "STUDENT", "invite_code": null }
POST /auth/login    { "email": "a@b.com", "password": "password123" }
```

두 응답이 같은 모양이다:

```jsonc
{
  "user": {
    "id": "user_...", "name": "홍길동", "nickname": "홍길동",
    "email": "a@b.com", "avatar_url": null,
    "role": "STUDENT",              // STUDENT | EDUCATOR | ADMIN
    "organization_id": null,
    "acorn_balance": 0, "total_acorns_earned": 0
  },
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 43200          // 초. 12시간
}
```

### 토큰 쓰기

```ts
headers: { Authorization: `Bearer ${token}` }
```

`localStorage`에 보관하고, 앱 부팅 시 `GET /auth/me`로 살아있는지 확인한다. 401이면 토큰을 지우고 로그인 화면으로 보낸다.

```
GET  /auth/me      → UserRead (새로고침 후 상태 복구)
POST /auth/logout  → 204. 서버는 상태를 안 지우므로 토큰 삭제는 클라이언트 몫
```

`/auth/refresh`는 **아직 없다.** access token 하나만 쓰고 만료되면 다시 로그인한다.

**비밀번호 재설정 API도 없다.** `POST /auth/password-reset/request` 는 존재하지
않는다(`models.PasswordResetToken` 테이블만 있다). 프런트가 한때 이 경로를 부르고
있었는데 항상 404 였고, 그런데도 화면은 "재설정 안내를 보냈습니다"를 띄웠다 —
학생은 오지 않는 메일을 기다리게 된다. 지금은 화면에서 기능을 약속하지 않는다.
켜려면 ① request 엔드포인트(계정 열거 방지를 위해 항상 204) ② 메일 발송 경로
③ `confirm {token, new_password}` + 입력 화면, **세 조각이 다 필요하다.**

### 역할 (`role`)

| 값 | 가입 방법 |
|---|---|
| `STUDENT` | 기본값. 그냥 가입 |
| `EDUCATOR` | **기관 초대 코드(`invite_code`)가 필수.** 없으면 422 |
| `ADMIN` | 가입으로 만들 수 없다 (DB에서 직접 승격) |

역할은 요청 body로 받되 **가입 게이트를 통과해야 한다.** 게이트가 없으면
누구나 `role="EDUCATOR"`로 가입해 교육자 API를 두드릴 수 있다.

로그인 후에는 **서버가 토큰의 주인에서 역할을 읽는다.** 프런트가 보낸 역할을
신뢰하지 않으므로, 화면에서 버튼을 숨기는 것만으로는 보안이 되지 않는다.

### 인증이 필요 없는 것

`GET /health`, `GET /problems`, `GET /problems/{id}`, `POST /auth/signup`, `POST /auth/login`.

**그 외 전부 로그인이 필요하다.**

### 비밀번호 정책

최소 8자. 서버가 422로 거부한다. 클라이언트에서도 같은 기준으로 미리 막아주면 왕복이 준다.

### 로그인 실패

이메일이 없든 비밀번호가 틀렸든 **같은 401**이 온다. 의도된 것이다 — 구분해서 알려주면 "이 이메일은 가입되어 있다"를 확인시켜 주는 셈이다. 화면에도 "이메일 또는 비밀번호가 올바르지 않습니다" 하나만 띄운다.

---

## 1. 30초 요약

- **JSON은 전부 `snake_case`다.** 계획서의 `camelCase` TS 인터페이스를 그대로 쓰면 안 된다.
- **거의 모든 API가 로그인을 요구한다.** `Authorization: Bearer <token>` (§0)
- 이벤트는 **배치 전용** — 단건도 `{"events": [...]}`로 감싼다.
- 모든 이벤트에 **`client_event_id`를 반드시 넣는다** (`crypto.randomUUID()`).
- 채점은 **서버가 한다.** `POST /sessions/{id}/run|submit` 한 번이 스냅샷·채점·기록·판정을 전부 처리한다.
- **Run/Submit 직전에 대기 중인 스냅샷을 flush** 해야 한다 (§5).

---

## 2. 반드시 지켜야 할 6가지

깨지면 서버가 에러를 내는 게 아니라 **조용히 틀린 판단**을 한다. 그래서 여기 따로 모았다.

### ① 토큰 없이 부르면 401

`POST /sessions`부터 막힌다. 로그인 연동이 Coding Trace보다 먼저다.

### ② `client_event_id`는 선택이 아니다

```ts
{ type: "RUN", client_event_id: crypto.randomUUID(), payload: {} }
```

전송 실패 시 재시도 큐를 두게 되는데, 가장 흔한 실패는 *"서버는 저장했는데 응답이 유실되어 클라이언트가 재시도"* 다. 이 키가 없으면 서버가 중복을 걸러낼 수 없고, `RUN 3/5`가 다섯 번 기록되어 **한 번 실행한 학생에게 "막힘" 판정이 뜬다.**

키가 있으면 서버가 알아서 걸러내고 `duplicate_client_event_ids`에 담아 알려준다. 재시도는 안전하다.

### ③ Run/Submit 직전에 대기 중인 스냅샷을 flush 한다

서버는 "직전 실행 이후의 편집"을 코드 버전으로 잘라서 판단한다. debounce 타이머가 안 끝난 상태로 Run을 누르면 스냅샷이 결과보다 **늦게** 도착하고, 그 편집이 다음 결과의 창으로 밀려 판정이 한 칸씩 어긋난다.

서버는 이걸 막을 방법이 없다 — 도착 순서가 곧 진실이다. §5에 구현 코드가 있다.

### ④ `code_version`은 서버가 준다

프론트는 절대 지어내지 않는다. `POST /events` 응답의 `current_code_version`을 받아 쓴다.

### ⑤ 서버 전용 이벤트는 보내면 422

`SESSION_START`, `TEST_RESULT`, `AGENT_TRIGGER`, `AGENT_INTERVENTION`, `SYNTAX_ERROR`, `RUNTIME_ERROR` — 전부 서버가 만든다. 특히 계획서가 수집 목록에 넣어둔 **`SESSION_START`를 보내면 422**다. `POST /sessions` 응답 시점에 이미 만들어져 있다.

### ⑥ `GET`은 폴링해도 안전하다

`/process-state`를 몇 초마다 불러도 상태가 바뀌지 않는다. 의도된 설계다 — 마음껏 폴링해라.

---

## 3. 세션 생명주기

### 시작

```ts
const r = await fetch(`${API}/sessions`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,     // 없으면 401
  },
  body: JSON.stringify({ problem_id: "func_sum_list" }),
});
const s = await r.json();
localStorage.setItem("session_id", s.session_id);
editor.setValue(s.current_code);   // 문제 템플릿이 이미 들어 있다
```

**`user_id`를 body로 보내지 않는다.** 보내도 무시된다 — 세션 소유자는 토큰이 정한다. 받아들이면 아무나 남의 이름으로 세션을 만들고 그 채점 결과가 그 사람의 도토리가 된다.

응답 (`201`):

```jsonc
{
  "session_id": "sess_699b671f0ece44199bfd220977ff12f8",
  "user_id": "user_faf17a7c42f44628a7202989839976f1",   // 토큰의 주인
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

기기가 바뀌어도 이어서 풀려면 세션이 아니라 **진행 상태**를 쓴다 — `GET /users/me/progress/{problem_id}`의 `current_code` (§9).

### 남의 세션에 접근하면 404

403이 아니다. 403은 "그 세션은 존재하지만 네 것이 아니다"를 알려주므로 id를 훑어 다른 사용자의 활동을 탐지할 수 있다. 프론트 입장에서는 **"없는 세션"과 똑같이 처리**하면 된다 — localStorage를 비우고 새로 만든다.

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
  "current_code_version": 2,     // ← 서버가 할당한 최신 코드 버전
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
  // 1. 세션 확보 (지연 생성). 로그인이 안 돼 있으면 여기서 401.
  const sid = await ensureSession();

  // 2. 대기 중인 debounce 스냅샷을 강제로 비운다. 반드시 await.
  await flushPendingSnapshot();

  // 3. 실행 "요청" 이벤트 (선택이지만 타임라인이 예뻐진다)
  await postEvents([{ type: mode.toUpperCase(), client_event_id: uuid(), payload: {} }]);

  // 4. 채점. **이 한 번의 호출이 전부 한다** --
  //    스냅샷 생성 → Docker judge 실행 → TEST_RESULT 기록 → monitor 판정
  //    → 최초 정답이면 도토리 지급 + 진행 상태 갱신
  const res = await fetch(`${API}/sessions/${sid}/${mode}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ code: editor.getValue() }),
  }).then(r => r.json());

  renderTestResult(res.event.payload);      // { status, passed, total, ... }
  renderProcessState(res.process_state);
  if (res.agent_decision) renderAgent(res.agent_decision);
}
```

**프론트는 더 이상 채점하지 않는다.** `pythonRunner.runPython`은 죽은 코드다 (Pyodide는 TRACE 학습 화면의 `runTrace`에만 쓰인다).

⚠️ **`JUDGE_BACKEND` 기본값이 `none`이라 설정 없이는 503 `JUDGE_UNAVAILABLE`이 난다.**
백엔드에서 `JUDGE_BACKEND=docker` + `judge-sandbox` 이미지 빌드가 되어 있어야
실제 채점이 돈다. 503이 오면 백엔드 설정 문제이지 프런트 잘못이 아니다.

### `status`로 올 수 있는 값

| 값 | 언제 | 누구 잘못 | 점수로 세나 | 오류 횟수로 세나 |
|---|---|---|---|---|
| `ACCEPTED` | 전부 통과 | — | ○ | — |
| `WRONG_ANSWER` | 일부/전부 오답 | — | ○ | — |
| `SYNTAX_ERROR` | 파싱 실패 | 학생 | ✗ 관측 없음 | ○ |
| `RUNTIME_ERROR` | 학생 코드가 예외를 던졌다 | 학생 | ✗ | ○ |
| `TIME_LIMIT` | 시간 초과 | 학생 | ✗ | ○ |
| `INTERNAL_ERROR` | **채점 인프라가 고장났다** | 우리 | ✗ | **✗** |

서버가 에러를 "0점"이 아니라 **"관측 없음"** 으로 취급하기 때문에, 오타 한 번이 `3/5 → 오타 → 3/5`를 "+3점 진전"으로 만들지 않는다.

**`INTERNAL_ERROR`는 학생의 오류 횟수로 세지 않는다.** 도커가 죽어 있는데 학생이 Run을
세 번 누른 것을 "반복 실패"로 판정하면, 원인이 채점 서버인데 코드에 대한 힌트가 나간다.
그래서 monitor도 마지막 결과가 `INTERNAL_ERROR`면 trigger를 만들지 않는다
(`trigger: null` + `reason: "채점 서버에 문제가 생겨..."`).

**화면에서는 학생 코드 문제와 구분해서 보여줘야 한다.** "실행 중 오류가 발생했어요"가
아니라 "채점 서버에 문제가 생겼어요 (코드 문제가 아니에요)"에 가까운 문구가 맞다.

### `POST /sessions/{id}/results`는 **제거됐다**

클라이언트가 채점 결과를 보고하던 입구다. 도토리가 정답 기준으로 지급되는 이상 이 경로가 열려 있으면 `{"status":"ACCEPTED"}` 한 줄로 무한 획득이 가능해서 없앴다. 채점은 `run`/`submit`뿐이다.

### 응답

```jsonc
// 201
{
  "event": { "event_id": "evt_...", "seq": 7, "type": "TEST_RESULT",
             "source": "SERVER", "code_version": 4,
             "payload": { "mode": "run", "status": "WRONG_ANSWER",
                          "passed": 3, "total": 5, "runtime_ms": 21,
                          "judge": "docker" } },

  "process_state": { /* §6 */ },
  "agent_decision": null        // trigger가 있을 때만 채워진다
}
```

---

## 6. Process State 소비하기

`POST /run|submit` 응답에 이미 들어 있다. 데모 패널을 따로 갱신하고 싶으면 `GET /sessions/{id}/process-state`를 **3~5초 주기로 폴링**하면 된다 (안전하다).

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

**`concept`은 단수다.** 문제 JSON·judge API·프론트 파서가 전부 단수를 쓴다.

`check_type`에 따라 테스트케이스의 키가 다르다. **원본 키가 그대로 나간다.**

```jsonc
// check_type: "function_call"
{
  "problem_id": "func_sum_list",
  "title": "...", "description": "...", "difficulty": "BEGINNER",
  "concept": ["loop", "accumulator"],
  "check_type": "function_call",
  "function_name": "sum_list",
  "code_template": "def sum_list(arr):\n    # 여기에 코드를 작성하세요\n    pass",
  "public_test_cases": [
    { "input": [[1,2,3]], "expected": 6, "stdin": null, "expected_stdout": null, "category": "basic" }
  ],
  "hidden_test_case_count": 3,
  "hidden_test_categories": ["negative_numbers", "boundary_case", "empty_list"],
  "time_limit_sec": null, "memory_limit_mb": null
}

// check_type: "stdout_match"  -- function_name 이 null 이다
{
  "problem_id": "stdout_bigger_number",
  "concept": [], "check_type": "stdout_match", "function_name": null,
  "public_test_cases": [
    { "input": null, "expected": null, "stdin": "10 -3\n", "expected_stdout": "0\n", "category": "sample_1" }
  ],
  "time_limit_sec": 1.0, "memory_limit_mb": 128
}
```

렌더링은 `stdin !== null`로 분기하면 된다.

**hidden test의 값은 응답에 담길 필드 자체가 없다.** 개수와 카테고리만 노출되니 "숨은 테스트 3개: 음수, 경계값, 빈 리스트" 같은 힌트 UI를 만들 수 있다.

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

**Agent는 아직 stub이라 항상 `WAIT`을 돌려준다.** 응답 스키마는 확정이므로 6종 action UI를 지금 만들어두면 LLM이 붙는 날 프론트는 손댈 게 없다.

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
| `NOT_AUTHENTICATED` | 401 | 토큰이 없거나 만료. **토큰 지우고 로그인 화면으로** |
| `INVALID_CREDENTIALS` | 401 | 로그인 실패. 이메일/비밀번호를 구분하지 않는다 |
| `EMAIL_ALREADY_REGISTERED` | 409 | 이미 가입된 이메일 |
| `NICKNAME_TAKEN` | 409 | 닉네임 중복 |
| `INVALID_NICKNAME` | 422 | 길이·문자·금지어 위반 |
| `INSUFFICIENT_ACORNS` | 402 | 도토리 부족. `context.required` / `context.balance`가 함께 온다 |
| `FORBIDDEN` | 403 | 역할이 모자람 (학생이 교육자 API 호출 등) |
| `INVALID_INVITE_CODE` | 422 | 기관 초대 코드가 틀림. 교수자 가입 실패 |
| `COURSE_NOT_FOUND` | 404 | 없거나 **남의 강의** |
| `STUDENT_NOT_IN_COURSE` | 404 | 그 강의에 등록되지 않은 학생 |
| `ALREADY_ENROLLED` | 409 | 이미 등록됨 |
| `USER_NOT_FOUND` | 404 | 이메일로 학생을 찾지 못함 |

**Agent 호출이 실패해도 채점 결과는 반드시 돌아온다.** `POST /run|submit`이 내부에서 삼킨다 — "실행했는데 아무 반응이 없는" 상황은 만들지 않는다. `agent_decision: null`을 정상 케이스로 다뤄라.

---

## 9. 프로필 · 도토리 · 진행 상태

마이페이지와 홈 화면이 쓰는 API. 전부 로그인 필요.

### 프로필

```http
GET   /users/me/profile
PATCH /users/me/nickname   { "nickname": "새 닉네임" }
```

```jsonc
// GET /users/me/profile
{
  "id": "user_...", "name": "홍길동", "nickname": "도토리왕",
  "email": "a@b.com", "avatar_url": null,
  "acorn_balance": 135, "total_acorns_earned": 260,
  "current_badge": { "code": "SAPLING", "name": "묘목 뱃지", "required_acorns": 150 },
  "next_badge":    { "code": "OAK",     "name": "참나무 뱃지", "required_acorns": 300 },
  "created_at": "...", "last_login_at": "..."
}
```

**뱃지는 서버가 계산한다.** 프론트에서 누적 도토리로 다시 계산하지 마라 — 기준이 두 곳에 있으면 갈라진다.

닉네임 변경은 **도토리 5개**를 차감한다. 응답:

```jsonc
{ "nickname": "도토리왕", "acorn_balance": 5, "acorns_spent": 5 }
```

- 잔액이 부족하면 **402** `INSUFFICIENT_ACORNS`. **아무것도 바뀌지 않는다** (검증·차감·변경이 한 트랜잭션)
- 같은 닉네임으로 바꾸면 과금하지 않는다 (`acorns_spent: 0`)
- **차감액을 프론트가 보내지 않는다.** 서버가 정한다

### 도토리

```http
GET /users/me/acorns                          → { balance, total_earned }
GET /users/me/acorns/transactions?limit=&offset=
```

```jsonc
{
  "balance": 135, "total_earned": 260, "total": 12,
  "transactions": [
    { "id": "acorn_tx_...", "amount": 15, "balance_after": 135,
      "type": "PROBLEM_SOLVED", "description": "리스트 합 구하기 최초 해결",
      "problem_id": "func_sum_list", "created_at": "..." }
  ]
}
```

지급/차감은 **전부 서버가 한다.** 프론트가 "도토리 주세요"를 호출하는 API는 없다.

| 사건 | `type` | 변동 |
|---|---|---|
| 문제 **최초** 정답 | `PROBLEM_SOLVED` | +10 (난이도별 10/15/20, 현재 데이터엔 난이도가 없어 전부 10) |
| 같은 문제 재통과 | — | **0** |
| TRACE 최초 완료 | `TRACE_COMPLETED` | +3 — **아직 지급 경로가 연결되지 않았다** |
| 닉네임 변경 | `NICKNAME_CHANGED` | −5 |
| 프로필 사진 변경 | `AVATAR_CHANGED` | −10 — 업로드 API 미구현 |

`FIRST_ACCEPTED` / `DAILY_STREAK` / `ADMIN_ADJUSTMENT` 타입도 enum에 있으나 아직 안 쓴다.

### 진행 상태 · Checkpoint

```http
GET /users/me/progress                              → 전체 (홈 목록용, 코드 제외)
GET /users/me/progress/{problem_id}                 → 하나 (current_code 포함)
PUT /users/me/progress/{problem_id}/checkpoint      { "student_code": "..." }
```

```jsonc
{
  "problem_id": "func_sum_list",
  "status": "SOLVED",              // NOT_STARTED | IN_PROGRESS | SOLVED
  "best_passed": 5, "total_tests": 5,
  "attempt_count": 3,
  "last_judge_status": "ACCEPTED",
  "first_started_at": "...", "last_attempted_at": "...", "solved_at": "...",
  "current_code": "def sum_list(arr): ..."   // 목록에서는 null
}
```

**`localStorage`의 `codetrace:checkpoint:*`를 이걸로 대체한다.** 계정에 저장되므로 기기가 바뀌어도 이어서 풀 수 있다.

손대지 않은 문제도 **404가 아니라** `NOT_STARTED` 빈 상태를 준다 — "없음"과 "에러"를 구분하는 분기를 만들 필요가 없다. 존재하지 않는 `problem_id`만 404다.

### 푼 문제 목록

```http
GET /users/me/solved-problems
```

```jsonc
{
  "items": [
    { "problem_id": "func_sum_list", "title": "리스트 합 구하기",
      "solved_at": "...", "attempt_count": 3, "acorns_earned": 15 }
  ],
  "total": 1
}
```

마이페이지의 하드코딩된 샘플을 이걸로 바꾸면 된다.

---

## 10. 교육자 API

`EDUCATOR`(또는 `ADMIN`) 역할만 접근할 수 있다. 학생 토큰으로 부르면 **403 `FORBIDDEN`**.

**두 겹으로 막힌다** — 역할 검사 + 강의 소유권. 담당하지 않는 강의는 **404**다
(403이면 "그 강의는 존재한다"를 알려주는 셈이라 id를 훑어 타 기관 강의를 추정할 수 있다).

### 강의

```http
GET    /educator/courses
POST   /educator/courses          { title, term, code_visibility?, problem_ids? }
GET    /educator/courses/{id}
POST   /educator/courses/{id}/students          { email }
DELETE /educator/courses/{id}/students/{sid}    → 204
```

```jsonc
// CourseRead
{
  "id": "course_...", "organization_id": "org_...",
  "title": "Python 기초 01", "term": "2026 여름학기",
  "educator_id": "user_...", "educator_name": "김튜토리",
  "invite_code": "Sc4v0PfDXnoQ",
  "code_visibility": "SUBMITTED_ONLY",   // SUBMITTED_ONLY | LATEST_SNAPSHOT
  "student_count": 2, "assigned_problem_count": 3,
  "start_at": null, "end_at": null, "is_active": true
}
```

`code_visibility`는 **교수자가 강의별로 정한다.** 학생 코드를 어디까지 보여줄지:

| 값 | 보이는 것 |
|---|---|
| `SUBMITTED_ONLY` (기본) | submit으로 채점된 코드만 |
| `LATEST_SNAPSHOT` | 작성 중인 코드까지 |

### 대시보드

```http
GET /educator/courses/{id}/dashboard
```

```jsonc
{
  "course": { "id": "...", "title": "...", "term": "...", "educator_name": "김튜토리" },
  "metrics": {
    "student_count": 28,
    "student_count_delta": 0,      // 과거 스냅샷이 없어 항상 0. 뱃지를 감춰라
    "average_progress": 64,        // 학생별 진도율의 평균
    "weekly_progress_delta": 0,    // 항상 0
    "completion_rate": 71,         // (학생 × 배정문제) 중 해결한 칸의 비율
    "total_attempts": 728,         // run + submit 합
    "needs_attention_count": 2     // NEEDS_HELP 또는 INACTIVE
  }
}
```

### 학생 목록

```http
GET /educator/courses/{id}/students?q=민서&status=NEEDS_HELP&sort=risk_desc&page=1&size=30
```

`sort`: `risk_desc`(기본) · `progress_asc` · `progress_desc` · `name_asc`

```jsonc
{
  "items": [{
    "student_id": "user_...", "name": "김민서", "email": "...", "avatar_url": null,
    "progress": 82, "solved_count": 21, "attempt_count": 31,
    "last_active_at": "2026-08-13T14:48:00Z",
    "learning_status": "ON_TRACK",
    "weak_concepts": ["loop"]
  }],
  "total": 28, "page": 1, "size": 30
}
```

`learning_status` 4종 — 화면 문구 매핑:

| 서버 값 | 화면 |
|---|---|
| `ON_TRACK` | 순조로움 |
| `WATCH` | 관찰 필요 |
| `NEEDS_HELP` | 도움 필요 |
| `INACTIVE` | 장기 미접속 |

### 지금 확인할 학생

```http
GET /educator/courses/{id}/attention?limit=10
```

```jsonc
{
  "items": [{
    "student_id": "user_...", "name": "박지훈",
    "status": "NEEDS_HELP", "progress": 46, "risk_score": 75,
    "weak_concept": "conditional",
    "reasons": ["진도율 0%", "5회 시도 중 0문제 해결", "같은 문제를 5회 시도 중"]
  }]
}
```

**`reasons`는 서버가 한국어로 만들어 준다.** 그대로 렌더하면 된다.
`risk_score`는 0~100이고 40 미만 `ON_TRACK`, 70 미만 `WATCH`, 그 이상 `NEEDS_HELP`.

### 학생 상세

```http
GET /educator/courses/{id}/students/{student_id}
```

```jsonc
{
  "student": { "id": "...", "name": "박지훈", "email": "...", "avatar_url": null },
  "summary": { "progress": 46, "solved_count": 12, "attempt_count": 38,
               "last_active_at": "...", "risk_score": 75, "learning_status": "NEEDS_HELP" },
  "weak_concepts": [{ "concept": "conditional", "score": 42, "failed_attempts": 8 }],
  "recent_activity": [{
    "problem_id": "func_sum_list", "title": "리스트 합 구하기",
    "status": "IN_PROGRESS", "best_passed": 3, "total_tests": 5,
    "attempt_count": 5, "last_judge_status": "WRONG_ANSWER",
    "last_attempted_at": "...",
    "code": null,              // ← 정책에 따라 null 일 수 있다
    "code_kind": null          // "SUBMITTED" | "LATEST_SNAPSHOT"
  }],
  "recommendations": ["conditional 개념 기초 문제 재배정", "'리스트 합 구하기' 개별 힌트 전송"],
  "code_visibility": "SUBMITTED_ONLY"
}
```

`code`가 `null`이면 정책상 비공개다. `code_visibility`를 함께 내려주므로
"이 강의는 제출한 코드만 볼 수 있습니다" 같은 안내를 띄우면 된다.

### 기관 · 교수자 계정 만들기

기관 생성 API가 **아직 없다.** 백엔드에서 스크립트를 돌려야 한다:

```bash
cd backend && python -m scripts.seed_org
```

출력된 기관 초대 코드로 교수자가 가입하거나, 함께 만들어진 데모 계정
(`educator@example.com` / `password123`)으로 바로 로그인할 수 있다.

---


## 11. 구현 체크리스트

**먼저 해야 하는 것 (이게 없으면 나머지가 전부 401)**

- [x] `LoginPage` / `SignupPage`를 `POST /auth/login` · `/auth/signup`에 연결
- [x] `access_token`을 localStorage에 보관하고 모든 요청에 `Authorization: Bearer` 부착
- [x] 앱 부팅 시 `GET /auth/me`로 세션 복구, 401이면 토큰 삭제 후 로그인 화면
- [x] `traceClient.ts` / `useCodingTrace.ts`의 fetch에 토큰 추가
- [x] 401 공통 핸들러 (토큰 만료 시 자동 로그아웃) — `api.onUnauthorized`
- [x] 비밀번호 최소 길이를 서버와 같은 **8자**로 (프런트가 6자였다 → 6~7자 입력 시 원인 불명의 422)
- [x] 교수자 가입 `invite_code` 입력/전송 (없으면 EDUCATOR 가입 자체가 422라 교육자 화면에 들어갈 계정을 만들 수 없었다)

**그 다음**

- [x] 모든 요청/응답 필드를 `snake_case`로
- [x] 모든 이벤트에 `client_event_id = crypto.randomUUID()`
- [x] 전송 실패 → 메모리 큐 보관 → 재시도 (중복은 서버가 거른다)
- [x] `CODE_SNAPSHOT` 800ms debounce
- [x] **Run/Submit/Reset 직전 `await flushPendingSnapshot()`**
- [x] `SESSION_START` / `TEST_RESULT`를 `POST /events`로 보내지 않기
- [x] 남의 세션 404를 "없는 세션"과 동일하게 처리
- [ ] `process_state.reason` / `evidence`를 가공 없이 렌더
- [ ] `status` 6종 + `trigger` 4종 + `agent_decision.action` 6종 UI 매핑
- [x] `agent_decision: null`을 정상으로 처리
- [x] 페이지 이탈 시 마지막 flush (`sendBeacon` 이 아니라 `fetch(keepalive)` — beacon 은 `Authorization` 헤더를 실을 수 없다)
- [x] `.env`에 `VITE_API_BASE_URL=http://localhost:8000`

**마이페이지 / 홈 (§9)**

- [ ] `localStorage`의 `codetrace:checkpoint:*` → `PUT .../checkpoint`
- [ ] `tutory:profile` → `GET /users/me/profile`
- [ ] 하드코딩된 도토리·풀이 기록 → `GET /users/me/acorns`, `/solved-problems`
- [ ] 뱃지를 프론트에서 계산하지 말고 `current_badge` 사용
- [ ] 닉네임 변경 시 402 `INSUFFICIENT_ACORNS` 처리

CORS는 `http://localhost:5173`, `http://127.0.0.1:5173`이 열려 있다. 포트가 다르면 백엔드 `.env`의 `CORS_ORIGINS`에 추가해달라고 요청할 것.

---

## 12. 이름이 정리된 항목

구현하면서 확정한 이름들. 아래 왼쪽 열은 초기 논의에서 쓰이던 표현이라 아직 코드나 메모에
남아 있을 수 있는데, 그대로 보내면 **422가 난다.**

| 예전 표현 | 실제 | 왜 |
|---|---|---|
| `sessionId`, `clientTimestamp`, `codeVersion` (camelCase) | **`session_id`, `client_timestamp`, `code_version`** | API 전체가 snake_case로 통일 |
| `RUN_REQUESTED` / `SUBMIT_REQUESTED` | **`RUN` / `SUBMIT`** | "누가 보냈나"는 타입 이름이 아니라 서버의 `source` 컬럼에 기록 |
| `LEARNING_ACTIVITY_RESPONSE` | **`ACTIVITY_RESPONSE`** | 3개 계획 문서 중 2개가 짧은 쪽으로 합의 |
| `CODE_CHANGE` | **`CODE_SNAPSHOT`** | 저장 산출물의 이름과 일치 |
| 수집 목록에 `SESSION_START` 포함 | **보내면 422** | `POST /sessions`가 이미 만든다 |
| 채점 결과를 `POST /results`로 보고 | **`POST /run\|submit`** | 서버가 채점한다. 클라이언트 보고 경로는 제거됐다 |
| 이벤트 단건 전송 | **배치 전용** (`{"events": [...]}`) | 단건은 1개짜리 배치 |

전송 시점 정책(800ms debounce, 즉시/배치 구분, 재시도 큐)은 [frontend_plan.md](frontend_plan.md) §6~7 그대로다.

---

## 13. 막히면

- <http://localhost:8000/docs> — 모든 스키마를 실제로 눌러볼 수 있다
- `python -m scripts.seed_demo` — 4개 데모 세션(PROGRESSING / STUCK / UNDERSTANDING_UNCERTAIN / RECOVERED)을 만들어준다. 프론트 붙이기 전에 응답 모양을 보려면 이게 제일 빠르다
- 설계 근거와 함정은 [../backend/README.md](../backend/README.md)
- 파이프라인 전체 그림은 [backend_plan.md](backend_plan.md)
