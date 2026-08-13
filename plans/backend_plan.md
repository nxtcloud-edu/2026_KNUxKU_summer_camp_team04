# Backend 개발 계획서

## 1. 목적

Backend는 일반적인 문제·실행 API뿐 아니라, 학생의 Coding Trace를 영구 기록하고 이를 Agent가 판단할 수 있는 구조화된 Process State로 변환하는 역할을 담당한다.

핵심 데이터 흐름은 다음과 같다.

```text
Frontend Event
→ Trace Store
→ Code Snapshot / Diff
→ Judge Result
→ Process Feature Extraction
→ Lightweight Monitor
→ Agent Trigger
→ Agent Decision
→ Learning Activity
→ Student Response
→ State Update
```

Backend는 다음의 source of truth다.

- 문제 및 테스트케이스 (JSON 파일)
- 문제풀이 세션
- 코드 snapshot
- Coding Trace event
- Judge 결과
- Process State

---

## 1.1 현재 구현 상태

| 영역 | 상태 |
|---|---|
| Problem / Session API | 구현 완료 |
| Event 수집 · 중복 제거 | 구현 완료 |
| Code Snapshot / Diff / 영역 태깅 | 구현 완료 |
| Process Feature Extractor | 구현 완료 (feature 20종) |
| Lightweight Monitor | 구현 완료 (규칙 11단) |
| Timeline / Snapshot 조회 API | 구현 완료 |
| Agent Context Builder | 구현 완료 (LLM 없이 payload 생성) |
| **회원 인증** (JWT + bcrypt, 역할 3종) | 구현 완료 |
| **도토리 원장** (멱등성 키) | 구현 완료 |
| **사용자별 진행 상태 / Checkpoint** | 구현 완료 |
| **교육기관 서비스** (기관·강의·수강·대시보드) | 구현 완료 |
| Python Judge (Docker) | 어댑터 완료. **기본값이 `none`이라 `/run`은 503** — `JUDGE_BACKEND=docker`로 켠다 |
| Agent LLM 호출 | **seam** — `POST /agent/decide`가 항상 `WAIT` |
| Learning Activity | 미구현 |
| Learner State | 미구현 |
| Analytics endpoint | 미구현 (timeline `summary`가 일부 대체) |

**테스트 217개 통과.** 필수 시나리오 3개(§22)는 로컬 서버에서 검증됨.

채점 경로는 **`POST /sessions/{id}/run|submit`** 하나다. 이 호출이
스냅샷 생성 → Docker judge 실행 → `TEST_RESULT` 기록 → monitor 판정 →
진행 상태 갱신 → 도토리 지급 → 교육자 통계 재계산까지 전부 한다.

> 클라이언트가 채점 결과를 보고하던 `POST /sessions/{id}/results`는 **제거됐다.**
> 도토리가 정답 기준으로 지급되는 이상 그 입구가 열려 있으면
> `{"status":"ACCEPTED"}` 한 줄로 무한 획득이 가능하다.

프론트엔드 연동 규약은 [FRONTEND_INTEGRATION.md](FRONTEND_INTEGRATION.md)에 있다.
브랜치 통합 시 남은 조율 항목은 [TEAM_SYNC.md](TEAM_SYNC.md)에 있다.

### 실행에 필요한 것

```bash
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000 --workers 1

# 교육자 기능을 쓰려면 기관·교수자·강의를 먼저 만든다.
# Organization 생성 API가 아직 없어서 이 스크립트가 그 자리를 메운다.
python -m scripts.seed_org

# Docker judge를 켜려면
pip install "docker>=7.0"
cd ../judge && docker build -t judge-sandbox .
# .env: JUDGE_BACKEND=docker, JUDGE_PATH=../judge
```

---

## 2. 권장 기술 스택

- Python 3.12+
- FastAPI
- Pydantic
- SQLAlchemy 또는 SQLModel
- SQLite: 2일 MVP
- PostgreSQL: 이후 확장
- Docker 또는 별도 subprocess worker: Python code execution
- `difflib`: 코드 diff
- LLM SDK: 선택 provider
- pytest

2일 MVP에서는 message broker, Kubernetes, 복잡한 microservice는 사용하지 않는다.

---

## 3. Backend 역할 분담

## BE 1 — Judge / Core Backend Owner

담당:

- Problem Service
- Session Service
- Python Runner
- Public/Hidden tests
- Run/Submit API
- timeout/error handling
- 문제 데이터 3개

## BE 2 — Trace / Agent Backend Owner

담당:

- Event ingestion
- Code snapshot/diff
- Process Feature Extractor
- Lightweight Monitor
- Agent Context Builder
- Agent API 연동
- Activity 저장/평가
- analytics logging

두 Backend 개발자는 `JudgeResult`, `TraceEvent`, `AgentDecision` Schema를 첫 시간에 확정한다.

---

## 4. 모듈 구조

```text
backend/
├── app/
│   ├── main.py            # FastAPI 앱, CORS, 에러 핸들러, 라우터 8개 등록
│   ├── config.py          # Settings + MonitorConfig(임계값)
│   ├── db.py              # 엔진, 세션, create_all
│   ├── clock.py           # utcnow / seconds_between / to_naive_utc
│   ├── enums.py           # 모든 enum (순환 import 방지로 한 파일)
│   ├── models.py          # SQLModel 테이블 12개 (§17)
│   ├── errors.py          # AppError 계층 + 에러 코드
│   ├── schemas_common.py  # UtcDatetime (출력 시 Z 강제)
│   │
│   ├── auth/              # 회원가입·로그인·토큰·역할 게이트
│   │   ├── router.py  deps.py  schemas.py  security.py  service.py
│   ├── users/             # 프로필·도토리·진행 상태·풀이 목록
│   │   ├── router.py  schemas.py
│   ├── acorns/            # 도토리 원장 (잔액을 직접 증감하는 곳은 여기뿐)
│   │   └── service.py
│   ├── progress/          # 사용자별 문제 진행 + 정답 보상
│   │   └── service.py
│   ├── educator/          # 기관·강의·수강·대시보드·주의 학생
│   │   ├── router.py  schemas.py  service.py
│   │
│   ├── problems/
│   │   ├── router.py
│   │   ├── service.py     # JSON 파일 로더 (DB 아님)
│   │   ├── schemas.py     # hidden test를 담을 필드가 없음
│   │   └── data/          # 문제 3개
│   │
│   ├── sessions/
│   │   ├── router.py
│   │   ├── service.py
│   │   ├── store.py       # 세션 조회 + 카운터 원자 할당 (leaf 모듈)
│   │   └── schemas.py
│   │
│   ├── judge/
│   │   ├── router.py       # POST /run, /submit -- 채점+기록+판정+보상의 진입점
│   │   ├── interface.py    # JudgeProtocol
│   │   ├── stub.py         # JudgeUnavailable
│   │   └── docker_judge.py # BE1 judge 어댑터 (JUDGE_BACKEND=docker)
│   │
│   ├── trace/
│   │   ├── router.py
│   │   ├── service.py     # 이벤트 수집, 스냅샷 기록, 결과 기록
│   │   ├── diff.py        # 순수 모듈 (DB 모름)
│   │   ├── features.py
│   │   ├── monitor.py
│   │   ├── timeline.py
│   │   └── schemas.py
│   │
│   └── agent/
│       ├── router.py      # POST /agent/decide
│       ├── interface.py   # AgentProtocol
│       ├── context.py     # Context Builder (동작함)
│       └── stub.py        # 항상 WAIT
├── scripts/
│   ├── seed_demo.py       # 데모 세션 4개 생성
│   └── seed_org.py        # 기관·교수자·강의 (EDUCATOR 가입에 필요)
└── tests/                 # 217개
```

`activities/`와 `analytics/`는 아직 없다. `judge/`와 `agent/`는 실제 구현 대신
**protocol + stub + 어댑터** 구조로, 환경변수 하나로 교체된다.

---

## 5. Problem Service

**문제는 DB가 아니라 JSON 파일이 진실이다.** `app/problems/data/*.json`을 읽고,
`PROBLEMS_DIR` 환경변수로 디렉터리를 바꿀 수 있다. `origin/judge`가 이미 파일 기반이라
DB에도 두면 병합 시 반드시 drift한다. 부수 효과로 hidden test가 ORM에 실리지 않아
어떤 `response_model` 실수도 유출을 만들 수 없다.

### 문제 데이터 (`func_sum_list.json`)

```json
{
  "problem_id": "func_sum_list",
  "title": "리스트의 합",
  "description": "정수 리스트의 모든 값을 더해 반환하세요.",
  "difficulty": "BEGINNER",
  "concept": ["loop", "accumulator"],
  "check_type": "function_call",
  "function_name": "sum_list",
  "code_template": "def sum_list(arr):\n    # 여기에 코드를 작성하세요\n    pass",
  "public_test_cases": [
    { "input": [[1, 2, 3]], "expected": 6, "category": "basic" }
  ],
  "hidden_test_cases": [
    { "input": "...", "expected": "...", "category": "negative_numbers" }
  ]
}
```

`hidden_test_cases`의 실제 값은 이 문서에 적지 않는다. 공개 저장소이고, 문서가
hidden test 유출 경로가 되면 API 쪽 구조적 방어(§5 끝)가 무의미해진다.
실제 값은 `backend/app/problems/data/*.json`에만 있다.

public/hidden은 `visibility` 필드가 아니라 **배열 자체가 분리**되어 있다.

문제 3개: `func_sum_list`, `func_find_max`, `func_count_positive`.

Hidden test category (Agent가 사용):

- `negative_numbers`
- `boundary_case`
- `empty_list`

### API

```http
GET /problems
GET /problems/{problem_id}
```

`ProblemDetail` 응답에는 **hidden test의 `input`/`expected`를 담을 필드 자체가 없다.**
`hidden_test_case_count`(개수)와 `hidden_test_categories`(카테고리)만 나간다.
유출 방지가 절차가 아니라 구조다.

---

## 6. Session Service

한 학생이 한 문제를 푸는 기간을 session으로 관리한다.

```json
{
  "session_id": "sess_699b671f0ece44199bfd220977ff12f8",
  "user_id": "user_faf17a7c42f44628a7202989839976f1",   // 토큰의 주인
  "problem_id": "func_sum_list",
  "status": "SOLVING",
  "started_at": "2026-08-13T12:00:00Z",
  "finished_at": null,
  "last_code_version": 1,
  "last_event_seq": 1,
  "current_code": "def sum_list(arr):\n    # 여기에 코드를 작성하세요\n    pass",
  "current_code_version": 1
}
```

`last_code_version`과 `last_event_seq`는 **원자 할당용 카운터**다.
`UPDATE ... SET x = x + 1 ... RETURNING x` 단일 statement로 증가시킨다 (SQLite 3.35+).
Python 레벨 read-modify-write가 없으므로 동시 요청이 서로 다른 값을 받는다.

`current_code`를 조회 응답에도 넣는다. 새로고침 복구가 왕복 한 번으로 끝난다.

### API

```http
POST /sessions
GET  /sessions/{session_id}
POST /sessions/{session_id}/finish
```

`POST /sessions`는 세션 행 + `SESSION_START` 이벤트 + **문제 템플릿 스냅샷 v1**을 함께 만든다.
`/finish`는 멱등이다. 종료된 세션의 이벤트도 409가 아니라 `session_finished: true`
플래그와 함께 수락한다 — 현실적 원인은 `/finish` 직후 큐 flush뿐인데 409는 데모 화면에
빨간 배너를 띄운다.

**세 엔드포인트 전부 로그인이 필요하다.** `POST /sessions`는 `user_id`를 body로
받지 않는다 -- 받으면 아무나 남의 이름으로 세션을 만들 수 있고 그 채점 결과가
그 사람의 도토리가 된다. 소유자는 토큰이 정한다.

남의 세션에 접근하면 **403이 아니라 404**다. 403은 "그 세션은 존재한다"를
알려주므로 id를 훑어 타인의 활동을 탐지할 수 있다.

---

## 7. Python Judge

**상태: 어댑터 완료, 기본값이 꺼져 있다.** `JUDGE_BACKEND` 기본값이 `none`이라
`POST /run`·`/submit`이 `503 JUDGE_UNAVAILABLE`을 반환한다. 아래 절차로 켠다.

BE1의 Docker judge를 붙이는 절차:

1. `pip install "docker>=7.0"`, `judge/`에서 `docker build -t judge-sandbox .`
2. `.env`: `JUDGE_BACKEND=docker`, `JUDGE_PATH=../judge`
3. **문제 디렉터리를 하나로 정한다.** `PROBLEMS_DIR`을 `../judge/problems`로 돌리거나,
   우리 것을 유지하되 양쪽 `problem_id` 집합이 같은지 확인한다. 디렉터리가 둘이면 drift 위험이다.
4. `run_judge()`가 `runtime_ms`를 반환하지 않는다 → 한 줄 추가하거나 `null`로 남는다.

어댑터(`app/judge/docker_judge.py`)는 작성되어 있다. 아래 §7.1~7.2는 그 judge의 설계 기준이다.

## 7.1 실행 방식

### 권장: Docker 기반 일회성 Runner

```text
student code
→ temporary directory
→ docker run --rm
→ strict timeout
→ JSON result
```

최소 제한:

- timeout: 2초
- 메모리 제한
- 네트워크 비활성화
- read-only filesystem 가능한 범위
- stdout 최대 길이 제한
- process 수 제한

### 시간 부족 시 폴백

분리된 subprocess worker에서 실행한다.

- 웹 서버 프로세스 내부의 직접 `exec()`는 피한다.
- `subprocess.run(..., timeout=2)` 사용
- 별도 working directory
- 환경변수 최소화

이 폴백은 대회 로컬 데모용이며 production-ready sandbox가 아님을 명시한다.

---

## 7.2 함수 호출형 채점

입출력 파싱이 아닌 함수 호출 방식으로 범위를 줄인다.

```python
# student code

def sum_list(arr):
    ...
```

Judge harness가 함수를 import/호출한다.

```python
result = sum_list([1, 2, 3])
assert result == 6
```

### JudgeResult

저장되는 `TEST_RESULT` 이벤트의 payload 형태:

```json
{
  "mode": "run",
  "status": "WRONG_ANSWER",
  "passed": 3,
  "total": 5,
  "runtime_ms": 21,
  "message": null,
  "failed_categories": ["boundary_case"],
  "judge": "pyodide"
}
```

`judge` 필드가 결과의 출처를 남긴다 (`pyodide` / docker judge 이름).
`failed_categories`는 Agent용이라 학생 화면에 그대로 노출하지 않는다.

### 상태

- `ACCEPTED`
- `WRONG_ANSWER`
- `RUNTIME_ERROR`
- `SYNTAX_ERROR`
- `TIME_LIMIT`
- `INTERNAL_ERROR`

---

## 8. 채점 API

**파이프라인의 척추다.** 경로는 하나뿐이다.

```http
POST /sessions/{session_id}/run       # public 테스트만
POST /sessions/{session_id}/submit    # public + hidden 전체
```

요청 (`RunRequest`) — 셋 중 하나를 준다:

```json
{ "code": "def sum_list(arr): ..." }        // 가장 흔한 형태. 스냅샷을 새로 만든다
{ "code_version": 4 }                        // 이미 올린 스냅샷을 채점
{}                                           // 최신 스냅샷을 채점
```

처리 순서 (`backend/app/judge/router.py` `_execute`):

```text
1. 세션 조회 + **소유권 검사**      require_session(user_id=...)
2. 스냅샷 생성 (code 를 준 경우)     create_snapshot()
3. 채점                              judge.judge()  <- Docker
4. TEST_RESULT 기록                  record_judge_result()
5. 진행 상태 갱신 + 도토리 지급       progress.record_judge_result()
6. 교육자 통계 재계산                 educator.recalculate_for_student()
7. Monitor 판정                      monitor.evaluate_and_record()
8. trigger 있으면 Agent 호출
```

응답 (`201 ResultIngestResponse`):

```json
{
  "event": {
    "event_id": "evt_...", "seq": 7, "type": "TEST_RESULT",
    "source": "SERVER", "code_version": 4,
    "payload": { "mode": "run", "status": "WRONG_ANSWER",
                 "passed": 3, "total": 5, "judge": "docker" }
  },
  "process_state": { "status": "STUCK", "trigger": "REPEATED_FAILURE",
                     "evidence": ["동일 결과 3/5 ×3", "반복문 영역 ×2 반복 수정"] },
  "agent_decision": null
}
```

**`JUDGE_BACKEND` 기본값이 `none`이라 설정 없이는 503 `JUDGE_UNAVAILABLE`이 난다.**
`JUDGE_BACKEND=docker` + `judge-sandbox` 이미지 빌드가 필요하다 (§1.1).

### 제거된 것: `POST /sessions/{id}/results`

클라이언트가 채점 결과를 보고하던 입구였다. 두 가지가 바뀌어 제거했다.

1. 프런트가 더 이상 브라우저에서 채점하지 않는다
2. 도토리가 정답 기준으로 지급된다 -- 클라이언트가 `status`를 정할 수 있으면
   `curl` 한 줄로 무한 획득이 가능하다

"서버의 ACCEPTED 결과를 기준으로 지급한다"는 요구는 **이 입구가 없어야** 성립한다.

Agent 호출이 실패해도 채점 결과는 반드시 반환된다 (`try/except`로 삼킨다).

## 9. Trace Event Service

### Event 종류

클라이언트가 보낼 수 있는 것:

- `CODE_SNAPSHOT`
- `RUN`
- `SUBMIT`
- `UNDO`
- `RESET`
- `HINT_REQUEST`
- `ACTIVITY_OPENED`
- `ACTIVITY_RESPONSE`
- `SESSION_END`

서버만 생성하는 것:

- `SESSION_START`
- `TEST_RESULT`
- `AGENT_TRIGGER`
- `AGENT_INTERVENTION`
- `SYNTAX_ERROR` / `RUNTIME_ERROR` (enum에 예약만, 지금은 emit하지 않음)

요청 스키마의 `type`이 축소 enum(`ClientEventType`)이라 `{"type": "TEST_RESULT"}`는
핸들러 진입 전에 **422**가 된다. 런타임 체크가 아니라 선언이고, OpenAPI에 제약이 드러나
프론트의 생성 타입은 그걸 표현조차 못 한다.

`SYNTAX_ERROR`/`RUNTIME_ERROR`를 별도 이벤트로 쓰지 않는 이유: 한 번의 실행이 두 행을
만들면 `recent_error_types`를 계산할 지점이 둘이 된다. 상태는 `TEST_RESULT.payload.status`가
운반하고, 타임라인 렌더러가 그걸 `kind: "ERROR"`로 표시하므로 화면은 동일하다.

### Event Schema

```json
{
  "event_id": "evt_...",
  "session_id": "sess_...",
  "seq": 7,
  "type": "RUN",
  "source": "CLIENT",
  "server_timestamp": "2026-08-13T12:04:11Z",
  "client_timestamp": "2026-08-13T12:04:10Z",
  "code_version": 4,
  "payload": {}
}
```

`source`는 `CLIENT` / `CLIENT_JUDGE` / `SERVER`. **`RUN` vs `RUN_REQUESTED` 같은 구분은
타입 이름이 아니라 이 컬럼이 담당한다** — provenance는 필드에 속한다. 둘 다 타입으로 두면
모든 feature/monitor 규칙이 영원히 두 이름을 매칭해야 한다.

### 순서의 권위는 `seq`다

`server_timestamp`가 아니다. 배치 이벤트는 timestamp가 동일하고(microsecond 절삭)
클라이언트 시계는 무의미하다. `ORDER BY server_timestamp`를 넣고 싶어지면 참으라.

### API

```http
POST /sessions/{session_id}/events        # 배치 전용
GET  /sessions/{session_id}/events?since_seq=&limit=
GET  /sessions/{session_id}/timeline?collapse=true
```

요청은 **배치 전용**이다. 단건은 1개짜리 배치로 보낸다 (`{"events": [...]}`, 최대 50개).
union 타입은 OpenAPI를 모호하게 만들고 코드 경로를 둘로 만든다.

### 멱등성

모든 이벤트에 `client_event_id`(`crypto.randomUUID()`)를 받아 중복을 제거한다.
전송 실패 후 재시도가 전형적 실패 모드인데, dedup이 없으면 `RUN 3/5`가 다섯 번 기록되고
monitor가 한 번 실행한 학생에게 `REPEATED_FAILURE`를 외친다.
응답의 `duplicate_client_event_ids`로 무엇이 걸러졌는지 알려준다.

---

## 10. Code Snapshot과 Diff

### Snapshot Schema

diff 결과를 **스냅샷 행에 함께 저장한다.** 조회 때마다 다시 계산하지 않는다.

```json
{
  "session_id": "sess_...",
  "version": 4,
  "code": "...",
  "created_at": "...",
  "parent_version": 3,
  "added_line_count": 1,
  "deleted_line_count": 1,
  "change_size": 2,
  "change_ratio": 0.07,
  "seconds_since_parent": 12,
  "changed_lines": [4],
  "region_tags": ["loop"],
  "primary_region": "loop",
  "summary": "반복문 영역 수정 (1줄)"
}
```

코드가 최신 스냅샷과 **바이트 동일하면 새 버전을 만들지 않는다.**
debounce + undo/redo는 동일 스냅샷을 끊임없이 만들어내는데, 막지 않으면 no-op 편집으로
`same_region_edit_count`가 부풀려진다.

### 영역 태깅

`ast`가 아니라 **regex로 줄 단위 태깅**한다. 태깅 대상이 *편집 중인 학생 코드*이고
상당 비율이 문법적으로 무효인데, 그 무효성이 바로 우리가 관찰하려는 모집단이다.
`ast.parse`는 모듈 전체에 `SyntaxError`를 던져 파일 전체를 태그 0개로 만든다 —
가장 관찰이 필요한 순간에 눈이 먼다.

태그 7종과 우선순위 (위가 높음):

| 태그 | 매칭 | 라벨 |
|---|---|---|
| `loop` | `for` · `while` · `range(` · `enumerate(` | 반복문 |
| `condition` | `if` · `elif` · `else` · `match` · `case` | 조건문 |
| `accumulator` | `total += x` · `total = total + x` | 누적 변수 |
| `initialization` | 변수 초기 대입 | 초기화 |
| `return` | `return` · `yield` | 반환 |
| `function_def` | `def` · `class` · `@decorator` | 함수 정의 |
| `other` | 그 외 — 근거 계산에서 제외 | 기타 |

`accumulator`는 계획 원안의 3개(loop/condition/initialization)를 넘는 추가분이다.
대표 데모 문제가 accumulator 루프이고, "누적 변수 영역 ×3 수정"이 심사위원에게
"기타 ×3"보다 훨씬 나은 근거 문자열이기 때문이다.

### 조회 API

```http
GET /sessions/{id}/snapshots
GET /sessions/{id}/snapshots/{version}
GET /sessions/{id}/snapshots/{version}/diff?from=
```

`unified_diff`는 조회 시점에 `difflib`로 만들어 준다.

---

## 11. Process Feature Extractor

Raw event를 Agent 입력에 적합한 feature로 압축한다. 20종.

```json
{
  "elapsed_seconds": 142,
  "run_count": 6,
  "submit_count": 1,
  "attempt_count": 7,
  "recent_scores": [2, 3, 3, 3],
  "same_result_count": 3,
  "progress_delta": 0,
  "improved_recently": false,
  "seconds_without_progress": 96,
  "same_region_edit_count": 4,
  "repeated_edit_region": "loop",
  "edits_since_progress": 5,
  "edits_in_result_streak": 2,
  "undo_count": 1,
  "hint_count": 0,
  "large_change_detected": false,
  "recent_error_types": [],
  "consecutive_error_count": 0,
  "snapshot_count": 9,
  "last_result": { "mode": "run", "status": "WRONG_ANSWER", "passed": 3, "total": 5 }
}
```

### 정의상 결정 세 가지

이 층의 정의가 이후 모든 판정의 정확도를 좌우한다.

**① 에러 결과는 0점이 아니라 "관측 없음"이다.**
`SYNTAX_ERROR` / `RUNTIME_ERROR` / `TIME_LIMIT` / `INTERNAL_ERROR`는
`recent_scores`, `same_result_count`, `progress_delta` 계산에서 제외한다.

> **추가 (구현): `INTERNAL_ERROR`는 한 겹 더 빠진다.** 위 4개 중 앞의 3개는 학생
> 코드의 실패라 `consecutive_error_count`로 센다. `INTERNAL_ERROR`는 채점 인프라의
> 실패이므로 그것조차 세지 않는다(`app/enums.py`의 `SYSTEM_STATUSES`). 세면
> 도커가 죽어 있을 때 Run 세 번으로 `REPEATED_FAILURE`가 발화한다. 단 streak을
> **끊지도** 않는다 — 학생의 진짜 3연속 에러 중간에 채점기가 딸꾹질했다고 개입을
> 놓치면 그것도 틀리다. monitor에도 같은 취지의 게이트(R1s)가 있다.

- 0으로 세면 `3/5 → syntax → 3/5`가 `[3, 0, 3]`이 되어 `progress_delta = +3` →
  monitor가 `PROGRESSING`을 선언하고 명백히 막힌 학생을 방치한다.
- 반대로 `3/5 → 3/5 → syntax → 3/5 → 3/5`는 동일 결과 streak이 리셋되어
  영원히 `REPEATED_FAILURE`가 뜨지 않는다.
- 그리고 §22.3의 "syntax error 1회는 Agent를 호출하지 않는다"가 특례 규칙 없이
  **구조적으로** 도출된다.

**② 진전은 "개인 최고 기록 갱신"이다.** 아무 증가가 아니다.
`4/5 → 3/5 → 4/5`에서 두 번째 4/5는 회복이지 진전이 아니므로 90초 시계는 첫 4/5부터
계속 흘러야 한다.

**③ 결과 동일성은 `(status, passed, total)` 3요소로 판단한다.**
`passed`만 비교하면 run(public만, `total=1`)과 submit(public+hidden, `total=4`)이 섞인다.
`1/1 → 1/4 → 1/1`인 학생은 passed가 세 번 1이지만 같은 결과를 반복한 게 아니다.

### 편집 창은 `code_version`으로 자른다

"직전 결과 이후의 편집" 같은 창은 **시간이 아니라 버전으로** 자른다.
`server_timestamp`는 microsecond를 절삭하므로 빠르게 이어지는 편집/실행이 전부 같은 초에
몰리고, 시간으로 자르면 창이 의도보다 넓어져 그 이전 편집까지 쓸어담는다
(`large_change_detected`가 거짓 양성을 낸다). `version`은 `seq`와 마찬가지로 서버가
원자적으로 할당하는 단조 카운터라 안전하다.

### 계산 시점

`POST /run|submit` 처리 중, 그리고 `GET /process-state` 요청 시 **매번 전체 스캔**한다.
세션당 O(10²) 행이라 싸고, 증분 캐시의 무효화 버그가 계산 비용보다 훨씬 비싸다.
`now`는 주입 가능하다 — 이 파라미터 하나가 0.2초 테스트 스위트와 flaky 스위트를 가른다.

---

## 12. Lightweight Process Monitor

Monitor는 Agent가 아니다. LLM을 부르지 않고 결정론적 규칙만으로 판정한다.

### 규칙 체인 — first match wins. **순서가 설계다.**

| # | 조건 | status | trigger |
|---|---|---|---|
| R0 | 마지막 개입 이후의 `HINT_REQUEST` (**cooldown 무시**) | `HELP_REQUESTED` | 발화 |
| R1 | cooldown 게이트 | (분류는 유지) | **죽임** |
| R2 | `ACCEPTED` + `large_change_detected` | `UNDERSTANDING_UNCERTAIN` | 발화 |
| R3 | `progress_delta > 0` 또는 `improved_recently` | `PROGRESSING` | 없음 |
| R4 | `ACCEPTED` | `PROGRESSING` | 없음 |
| R5 | 동일 결과 ≥3 **+** 같은 영역 편집 ≥2 | `STUCK` | 발화 |
| R5b | 동일 결과 ≥3 **+** streak 내 편집 0 | `STUCK` | 발화 |
| R6 | 연속 에러 ≥3 | `STUCK` | 발화 |
| R7 | 90초 무진전 **+** 실행 ≥2 | `POSSIBLE_STUCK` | 발화 |
| R8 | 실행 ≥2 | `PRODUCTIVE_STRUGGLE` | 없음 |
| R9 | 그 외 | `PROGRESSING` | 없음 |

**R2가 R3보다 위에 있어야 한다.** `3/5 → 5/5`는 `progress_delta = +2`라 진전 가드가
먼저 잡아버리는데, 이 시나리오의 요점이 바로 "겉보기 진전이 의심스러운 경우"다.
진전 가드가 보호할 대상은 `2/5 → 3/5 → 4/5`로 기어오르는 학생이지, 재작성을 붙여넣고
5/5로 점프한 학생이 아니다.

**새 규칙을 추가하면 반드시 R3 아래에 넣는다.** R3가 위에 있다는 사실 자체가,
눈에 띄게 개선 중인 학생을 미래의 공격적인 규칙으로부터 보호하는 보장이다.

R5b는 "아무것도 안 고치고 Run만 3번" 케이스다. `same_region_edit_count`가 0이라 R5가
안 걸리는데, 동일 코드 3연속 실행은 명백히 stuck이다.

R8에 `same_result_count` 가드를 걸지 않는다. 진짜로 막힌 경우는 R5/R5b/R6가 이미 다 잡았고,
여기까지 내려온 학생은 "같은 점수지만 서로 다른 영역을 시도 중"이다.

### status와 trigger는 별개다

cooldown 게이트(R1)는 **status는 그대로 분류하되 trigger만 죽인다.**
`status: "STUCK"` + `trigger: null`이 정상적으로 존재한다. 데모에서 중요한 성질이다 —
심사위원은 시스템이 stuck임을 *알면서도* 다시 끼어들지 않기로 *선택*했다는 걸 본다.

### cooldown

"개입 후 최소 30초 **또는** 다음 Run까지" — 둘 중 **먼저 오는 쪽**이 해제한다.
따라서 두 조건이 모두 살아 있을 때만 유지된다.

상태를 sessions 컬럼이 아니라 `AGENT_TRIGGER` **이벤트**에 둔다:

1. trigger는 원래 이벤트다. 컬럼으로 복제하면 동기화 의무가 생긴다.
2. `GET /timeline`에 그대로 보인다 — 데모가 어차피 필요로 하는 마커.
3. 세션 상태를 조작하는 대신 행 하나를 넣어 cooldown을 테스트할 수 있다.
4. Agent의 `previous_interventions`(§13)가 공짜로 나온다.

### pure / recording 분리

```text
GET  /sessions/{id}/process-state  ->  evaluate()             아무것도 쓰지 않는다
POST /sessions/{id}/run|submit     ->  evaluate_and_record()  AGENT_TRIGGER를 쓴다
```

cooldown 상태가 이벤트에 살기 때문이다. 데모 패널은 `/process-state`를 몇 초마다 폴링하는데,
GET이 cooldown을 소진하면 trigger 직후 첫 폴링이 그걸 먹고 **정작 Agent를 호출해야 할
실제 Run이 cooldown에 걸린다.** (GET이 상태를 바꾸는 건 그 자체로도 틀렸다.)

### 임계값 — 전부 `.env`로 조정 가능

```text
same_result_threshold      3
same_region_threshold      2
consecutive_error_threshold 3
no_progress_seconds       90
cooldown_seconds          30
large_change_ratio       0.5   (그리고 ≥5줄, 그리고 ≤60초 이내)
recent_score_window        5
```

### 근거 문자열은 서버가 만든다

`reason`과 `evidence[]`를 한국어로 생성해 내려보낸다. 프론트는 `<ul>`로 뿌리기만 하면 된다.
문자열이 백엔드 테스트로 커버되고, Agent Context Builder가 같은 함수를 재사용한다.

```text
동일 결과 3/5 ×3
반복문 영역 ×2 반복 수정
최근 점수 3 → 3 → 3
```

---

## 13. Agent Context Builder

**상태: 구현 완료.** `app/agent/context.py`의 `build_context()`가 실제로 동작한다.
LLM은 부르지 않지만 아래 payload를 실제 trace 데이터로 채운다 — trace가 충분한지에 대한 증명이고,
Agent 담당자는 day 1부터 이걸 입력으로 쓸 수 있다.

Agent에게 DB 전체를 전달하지 않는다.

```json
{
  "problem": {
    "title": "리스트의 합",
    "concepts": ["loop", "accumulator", "boundary"],
    "description_summary": "정수 리스트의 모든 값을 더해 반환"
  },
  "current_code": "...",
  "judge_result": {
    "status": "WRONG_ANSWER",
    "passed": 3,
    "total": 5,
    "failed_categories": ["boundary_case"]
  },
  "recent_trace": [
    "RUN 3/5",
    "line 4 loop boundary changed",
    "RUN 3/5",
    "line 4 loop boundary changed",
    "RUN 3/5"
  ],
  "features": {
    "same_result_count": 3,
    "same_region_edit_count": 3,
    "seconds_without_progress": 82
  },
  "previous_interventions": []
}
```

토큰 절감을 위해 최근 의미 있는 event 5~10개만 포함한다.

---

## 14. Agent Orchestrator

**상태: seam.** `POST /agent/decide`는 200을 반환하되 항상 `action: "WAIT"`이다.
`AgentProtocol`(`app/agent/interface.py`)을 구현해 `AGENT_BACKEND=llm`으로 바꾸면 켜진다.
응답 스키마는 최종 형태로 OpenAPI에 이미 올라가 있어, 프론트는 오늘 6종 action UI를
전부 만들어둘 수 있다.

### 함수

```python
async def analyze_and_plan(context: AgentContext) -> AgentDecision:
    ...

async def generate_activity(
    decision: AgentDecision,
    context: AgentContext,
) -> LearningActivity:
    ...

async def evaluate_activity(
    activity: LearningActivity,
    answer: ActivityAnswer,
) -> ActivityEvaluation:
    ...
```

### 오류 처리

- LLM timeout
- malformed JSON
- invalid action
- Activity 검증 실패

폴백:

```json
{
  "action": "WAIT",
  "reason": "현재 학습 활동을 안정적으로 생성하지 못해 학생의 추가 시도를 기다림"
}
```

Judge 결과는 Agent 실패와 무관하게 반드시 반환한다.

---

## 15. Learning Activity Service

**상태: 미구현.** 테이블도 엔드포인트도 아직 없다. Agent가 붙은 뒤의 범위다.
다만 `ACTIVITY_OPENED` / `ACTIVITY_RESPONSE` **이벤트는 이미 수집 가능**하고,
`ACTIVITY_RESPONSE`의 `payload.result == "CORRECT"`는 feature extractor가 진전 anchor로
인정한다. 즉 Activity UI가 붙으면 trace 쪽은 그대로 동작한다.

### Activity Schema

```json
{
  "id": "activity-001",
  "session_id": "sess_699b671f0ece44199bfd220977ff12f8",
  "type": "TRACE",
  "status": "PENDING",
  "payload": {},
  "answer_key": {},
  "created_by_decision_id": "decision-001"
}
```

### API

```http
GET  /activities/{activity_id}
POST /activities/{activity_id}/answers
```

### 평가 우선순위

1. deterministic evaluation
2. Code Judge execution
3. LLM rubric evaluation

TRACE/PREDICT를 LLM으로 채점하지 않는다.

---

## 16. Learner State

**상태: 미구현.** 후속 범위다.

MVP는 session-level evidence state만 저장한다.

```json
{
  "session_id": "sess_699b671f0ece44199bfd220977ff12f8",
  "concepts": {
    "loop_boundary": {
      "status": "NEEDS_REVIEW",
      "evidence": ["same_failure_x3", "trace_failed_x1"]
    },
    "accumulator": {
      "status": "OK",
      "evidence": ["trace_success_x1"]
    }
  }
}
```

상태 enum:

- `UNKNOWN`
- `NEEDS_REVIEW`
- `IMPROVING`
- `OK`
- `RECOVERED`

장기 사용자 모델과 BKT는 후속 범위다.

---

## 17. 데이터 모델

현재 테이블은 **12개**다.

### Trace 파이프라인 (3개)

#### `sessions`
- `id` (PK, `sess_` 접두), `user_id` (**FK → users.id**), `problem_id`, `status`
- `started_at`, `finished_at`
- `last_code_version`, `last_event_seq` — 원자 할당 카운터

#### `code_snapshots`
- `id` (`snap_`), `session_id`, `version`, `code`, `created_at`, `parent_version`
- diff 결과를 denormalize: `added/deleted_line_count`, `change_size`, `change_ratio`,
  `seconds_since_parent`, `changed_lines`, `region_tags`, `primary_region`, `summary`
- `UNIQUE(session_id, version)`

#### `events`
- `id` (`evt_`), `session_id`, `seq`, `type`, `source`, `code_version`, `payload`(JSON)
- `server_timestamp`, `client_timestamp`, `client_event_id`
- `UNIQUE(session_id, seq)`, `UNIQUE(session_id, client_event_id)`

### 회원 · 도토리 (4개)

#### `users`
- `id` (`user_`), `email`(UNIQUE, 소문자 정규화), `password_hash`(bcrypt)
- `name`, `nickname`(UNIQUE), `avatar_url`
- `role` — STUDENT / EDUCATOR / ADMIN. **권한의 유일한 근거**
- `organization_id` (FK, nullable)
- `acorn_balance`, `total_acorns_earned` — 원장의 캐시
- `created_at`, `updated_at`, `last_login_at`, `is_active`

#### `acorn_transactions`
- `id` (`acorn_tx_`), `user_id`, `amount`(±), `balance_after`, `transaction_type`
- `reference_type`, `reference_id`, `description`
- `idempotency_key` **UNIQUE** — 중복 지급을 DB 제약이 막는다

#### `user_problem_progress`
- `user_id`, `problem_id`, **`course_id`** (빈 문자열 = 개인 학습)
- `status`, `current_code`, `last_submitted_code`, `best_passed`, `total_tests`
- `attempt_count`, `last_judge_status`, `first_started_at`, `last_attempted_at`, `solved_at`
- `UNIQUE(user_id, course_id, problem_id)`

> `course_id`가 **NULL이 아니라 빈 문자열**인 이유: SQL은 UNIQUE에서 NULL을 서로
> 다른 값으로 취급한다. nullable로 두면 개인 학습 행이 같은 (user, problem)에
> 대해 몇 개든 생겨 제약이 무력해진다.

#### `password_reset_tokens`
- `user_id`, `token_hash`(원문 아님), `expires_at`, `used_at`
- 스키마만 있고 재설정 API는 미구현

### 교육기관 (5개)

#### `organizations`
- `name`, `domain`(허용 이메일 도메인), `invite_code`(UNIQUE) — **교수자 가입 게이트**
- 생성 API가 없다. `scripts/seed_org.py`가 만든다

#### `courses`
- `organization_id`, `title`, `term`, `educator_id`, `invite_code`(UNIQUE)
- `code_visibility` — SUBMITTED_ONLY(기본) / LATEST_SNAPSHOT. **교수자가 강의별로 정한다**
- `start_at`, `end_at`, `is_active`

#### `course_problems`
- `course_id`, `problem_id`, `order` — 진도율의 **분모**
- 비어 있으면 저장소 전체를 배정한 것으로 본다

#### `enrollments`
- `course_id`, `student_id`, `status`(ACTIVE/COMPLETED/DROPPED)
- `UNIQUE(course_id, student_id)`

#### `student_course_stats`
- 대시보드가 읽는 요약. 채점 때마다 해당 학생 행만 갱신
- `progress_rate`, `solved_count`, `assigned_count`, `attempt_count`, `last_active_at`
- `learning_status`, `primary_weak_concept`, `risk_score`, `reasons`(JSON)
- **파생 데이터다.** 진실은 언제나 `user_problem_progress`와 `events`

**`problems` / `test_cases` 테이블은 없다.** 문제는 JSON 파일이 진실이다 (§5).
`agent_decisions` / `activities`도 없다 — Agent 판정 근거는 `AGENT_TRIGGER`
이벤트 payload에 feature 스냅샷째로 들어간다.


### 마이그레이션

Alembic을 쓰지 않는다. `create_all`은 절대 ALTER하지 않으므로 컬럼을 추가해도 조용히 무시된다.
스키마를 바꾸면 DB 파일을 지운다.

```bash
rm -f codetrace.db && uvicorn app.main:app --reload --workers 1
```

### 시간 저장

naive UTC로 저장하고 출력 시 `Z`를 강제한다. SQLite는 읽을 때 tzinfo를 버리고,
`Z`가 없으면 JS가 로컬로 파싱해 KST에서 9시간이 밀린다.

### 동시성 전제

**`uvicorn --workers 1`.** SQLite + 다중 워커 + 뜨거운 카운터 행은
`database is locked` 생성기다.

---

## 18. Analytics와 Observability

**상태: 부분 구현.** 전용 endpoint는 없지만 `GET /sessions/{id}/timeline`의 `summary`가
편집·실행·trigger 수와 최고 점수, 총 소요 시간을 이미 준다. token/latency는 LLM이 붙어야 생긴다.

대회 발표를 위해 반드시 기록한다.

- 전체 editor event 수
- Run 수
- Agent trigger 수
- Agent invocation 수
- action 분포
- 평균 latency
- input/output token
- Agent 오류율
- Activity 성공률
- 개입 전후 test score 변화

예:

```json
{
  "editor_events": 487,
  "runs": 9,
  "agent_invocations": 3,
  "invocation_rate": 0.006,
  "average_latency_ms": 1320,
  "total_input_tokens": 5920,
  "total_output_tokens": 741
}
```

### API — 선택

```http
GET /sessions/{session_id}/analytics
```

발표용 dashboard가 없더라도 로그를 JSON 또는 CSV로 출력할 수 있어야 한다.

---

## 19. 보안 및 개인정보

### 코드 실행

- 네트워크 비활성화
- timeout
- stdout 제한
- 임시 파일 정리
- 서버 credential을 runner에 전달하지 않음

### Trace 데이터

- MVP에서는 실제 개인정보를 수집하지 않음
- 임시 user id 사용
- raw keystroke는 저장하지 않음
- 코드 snapshot과 의미 있는 event만 저장
- 로그에 API key 또는 system prompt를 남기지 않음

---

## 20. API 계약 요약

**JSON은 전부 `snake_case`다.** 라우트 34개.

### 인증 불필요

```text
GET  /health                                    seam 상태
GET  /problems                                  목록 (테스트 데이터 없음)
GET  /problems/{id}                             public 케이스 + hidden 개수/카테고리
POST /auth/signup                               role, invite_code 선택
POST /auth/login
```

**그 외 전부 로그인이 필요하다.**

### 인증 (로그인한 사용자)

```text
POST /auth/logout                               204. 토큰 삭제는 클라이언트 몫
GET  /auth/me                                   새로고침 후 상태 복구
```

### 학생 — 세션 · Trace

```text
POST /sessions                                  user_id 를 body 로 받지 않는다
GET  /sessions/{id}
POST /sessions/{id}/finish                      멱등
POST /sessions/{id}/events                      배치 전용 (1~50개)
GET  /sessions/{id}/events?since_seq=&limit=
POST /sessions/{id}/run                         ★ 채점 (§8)
POST /sessions/{id}/submit                      ★ 채점 (§8)
GET  /sessions/{id}/process-state               읽기 전용, 폴링 안전
GET  /sessions/{id}/timeline?collapse=true
GET  /sessions/{id}/snapshots
GET  /sessions/{id}/snapshots/{version}
GET  /sessions/{id}/snapshots/{version}/diff?from=
POST /agent/decide                              seam -> action=WAIT
```

세션 라우트는 전부 **소유권을 검사한다.** 남의 세션은 403이 아니라 404.

### 학생 — 프로필 · 도토리 · 진행 상태

```text
GET   /users/me/profile                         뱃지를 서버가 계산해 준다
PATCH /users/me/nickname                        도토리 -5. 검증·차감·변경이 한 트랜잭션
GET   /users/me/acorns                          { balance, total_earned }
GET   /users/me/acorns/transactions?limit=&offset=
GET   /users/me/progress                        홈 목록용 (코드 본문 제외)
GET   /users/me/progress/{problem_id}           current_code 포함
PUT   /users/me/progress/{problem_id}/checkpoint
GET   /users/me/solved-problems
```

### 교육자 (EDUCATOR 또는 ADMIN)

```text
GET    /educator/courses
POST   /educator/courses
GET    /educator/courses/{id}
POST   /educator/courses/{id}/students          이메일로 등록
DELETE /educator/courses/{id}/students/{sid}    DROPPED 로 표시 (행 삭제 아님)
GET    /educator/courses/{id}/dashboard         상단 지표 4종
GET    /educator/courses/{id}/students          q / status / sort / page / size
GET    /educator/courses/{id}/students/{sid}    code_visibility 정책에 따라 코드 노출
GET    /educator/courses/{id}/attention         risk_score 높은 순
```

두 겹으로 막힌다 — 역할(`require_educator`) + 강의 소유권(`require_course`).
소유하지 않은 강의는 **404**다.

아직 없는 것: `/activities/*`, `/auth/refresh`, `/auth/password-reset/*`,
`/sessions/{id}/analytics`, 기관 생성 API(→ `scripts/seed_org.py`).

### 에러 봉투

```json
{ "detail": { "code": "SESSION_NOT_FOUND", "message": "...", "context": {} } }
```

FastAPI의 검증 실패(422)만 네이티브 배열 형태를 유지한다. 둘 다 `detail` 아래다.

| 코드 | HTTP | 언제 |
|---|---|---|
| `NOT_AUTHENTICATED` | 401 | 토큰 없음/만료 |
| `INVALID_CREDENTIALS` | 401 | 로그인 실패. 이메일/비밀번호를 구분하지 않는다 |
| `FORBIDDEN` | 403 | 역할 부족 |
| `SESSION_NOT_FOUND` | 404 | 없거나 **남의 것** |
| `COURSE_NOT_FOUND` | 404 | 없거나 **남의 강의** |
| `STUDENT_NOT_IN_COURSE` | 404 | |
| `PROBLEM_NOT_FOUND` `SNAPSHOT_NOT_FOUND` `USER_NOT_FOUND` | 404 | |
| `INSUFFICIENT_ACORNS` | 402 | `context.required` / `context.balance` 동봉 |
| `EMAIL_ALREADY_REGISTERED` `NICKNAME_TAKEN` `ALREADY_ENROLLED` | 409 | |
| `INVALID_NICKNAME` `INVALID_INVITE_CODE` | 422 | |
| `SERVER_ONLY_EVENT` `MISSING_SNAPSHOT_CODE` `INVALID_CODE_VERSION` | 422 | |
| `JUDGE_UNAVAILABLE` `AGENT_UNAVAILABLE` | 503 | seam 미연결 |


## 21. 핵심 Schema

### TraceEvent (요청)

`code_version`을 클라이언트가 보내지 않는다. **서버가 할당한다.**

```json
{
  "events": [
    {
      "type": "CODE_SNAPSHOT",
      "client_event_id": "8f14e45f-ceea-467a-9f6b-2c1e3d4a5b6c",
      "client_timestamp": "2026-08-13T12:04:10Z",
      "payload": { "code": "..." }
    }
  ]
}
```

응답에 `current_code_version`이 담겨 온다. 프론트는 이 값을 보관해 쓴다.

### JudgeResult (요청)

```json
{
  "mode": "run",
  "status": "WRONG_ANSWER",
  "passed": 3,
  "total": 5,
  "runtime_ms": 21,
  "code_version": 4,
  "client_event_id": "..."
}
```

제약: `0 ≤ passed ≤ total ≤ 100`, `status ∈ JudgeStatus`.

### ProcessState

```json
{
  "session_id": "sess_...",
  "status": "STUCK",
  "trigger": "REPEATED_FAILURE",
  "triggered": true,
  "reason": "같은 코드 영역을 반복 수정했지만 테스트 결과가 동일합니다.",
  "evidence": ["동일 결과 3/5 ×3", "반복문 영역 ×2 반복 수정"],
  "cooldown_active": false,
  "cooldown_remaining_seconds": 0,
  "features": { "same_result_count": 3, "same_region_edit_count": 2 },
  "evaluated_at": "2026-08-13T12:04:11Z"
}
```

`status` 6종 · `trigger` 4종(`null` 가능) · `reason`/`evidence`는 서버가 만든 한국어 문자열.

### AgentDecision

```json
{
  "state": "STUCK",
  "concept": "loop_boundary",
  "action": "TRACE",
  "reason": "...",
  "activity": {}
}
```

`action` 6종: `WAIT` · `HINT` · `TRACE` · `PREDICT` · `DEBUG` · `VERIFY`.
`trigger`가 있을 때만 non-null이다.

Frontend와 Backend는 이 타입을 OpenAPI(`/docs`)에서 생성한다.

---

## 22. 테스트 계획

**현재 217개 통과.** `pytest -q`로 실행한다.

### Unit Test

- 문제 조회 / hidden test 비노출
- snapshot version 증가 · 바이트 동일 시 dedup
- diff 계산 · 영역 태깅
- feature 계산 (에러=관측 없음, 진전 anchor, 창 자르기)
- monitor 규칙 체인 각 분기
- timeline 렌더링 · collapse

### Integration Test

```text
session 생성
→ snapshot 저장
→ 결과 전송
→ repeated failure feature 계산
→ agent trigger 기록
→ agent decision 반환
```

### 필수 시나리오 — `tests/test_monitor.py`가 데모 게이트다

여기가 초록이 아니면 하류의 어떤 것도 의미가 없다.

| # | 시나리오 | 기대 | 상태 |
|---|---|---|---|
| 1 | `2/5 → 3/5 → 4/5` | 개입 없음 | 통과 (라이브 검증) |
| 2 | `3/5 → 3/5 → 3/5` + 같은 영역 수정 | `REPEATED_FAILURE` | 통과 (라이브 검증) |
| 3 | Syntax Error 1회 | 개입 없음 | 통과 (라이브 검증) |
| 4 | TRACE 정답 → 원 문제 복귀 | — | Activity 미구현 |
| 5 | TRACE 오답 → PREDICT replanning | — | Activity 미구현 |
| 6 | Agent 실패 시 Judge 결과 정상 반환 | 결과 반환 | 통과 |

추가로 검증된 것:

- `/process-state` 5회 폴링 후 `AGENT_TRIGGER`가 1개 — GET이 상태를 바꾸지 않는다
- 동일 `client_event_id` 재전송 시 새 행 0개
- `POST /events`로 `TEST_RESULT` 위조 시 422
- `/problems/{id}` 응답에 hidden input/expected 미포함

### 데모 시드

```bash
python -m scripts.seed_demo
```

4개 세션(PROGRESSING / STUCK / UNDERSTANDING_UNCERTAIN / RECOVERED)을 만들고
session_id를 출력한다.

---

## 23. 2일 개발 일정

## Day 1 시작 1시간

두 BE 개발자 공동:

- API path 확정
- TraceEvent/JudgeResult/AgentDecision schema 확정
- 문제 3개 및 함수 signature 확정
- DB schema 확정

## Day 1 오전

### BE 1

- FastAPI skeleton
- Problem/Session API
- Python Runner
- 첫 문제 test harness

### BE 2

- Event API
- SQLite models
- snapshot 저장
- feature extractor 기본 구조

## Day 1 오후

### BE 1

- 문제 3개
- Public/Hidden tests
- Run/Submit
- error/timeout

### BE 2

- diff
- repeated failure/progress feature
- Process Monitor
- Agent Context Builder
- Agent 호출 연결

### Day 1 종료 기준

```text
Run → Judge → Event 저장 → 반복 실패 Trigger → Agent → TRACE
```

가 API 수준에서 끝까지 동작한다.

## Day 2 오전

### BE 1

- Runner 안정화
- hidden category
- Submit/Accepted
- integration test

### BE 2

- Activity 저장/답변 API
- Evaluator/replanning
- token/latency logging
- timeline API

## Day 2 오후

- E2E QA
- synthetic trajectory evaluation
- API response 정리
- 발표용 analytics 추출
- 실패 폴백 검증
- 기능 동결

---

## 24. 우선순위

### P0 — 반드시 구현

- [x] 문제 3개
- [x] 세션
- [ ] Python Judge — seam 준비 완료, BE1 병합 대기
- [x] snapshot/event 저장
- [x] Run/Test history
- [x] repeated failure/progress feature
- [x] Agent trigger
- [x] Agent 판정 근거 저장 (`AGENT_TRIGGER` payload)
- [ ] TRACE/PREDICT Activity API
- [x] Timeline API

### P1 — 가능하면 구현

- [ ] DEBUG/VERIFY
- [x] Process Replay 지원 — snapshot/diff 조회 API로 충족
- [ ] learner state
- [ ] analytics endpoint — timeline summary가 일부 대체

### P2 — 후속

- 로그인
- 교수 dashboard
- PostgreSQL
- 여러 언어
- 장기 learner model
- adaptive curriculum
- production-grade sandbox cluster

---

## 25. 완료 기준

Backend MVP는 다음 조건을 만족해야 한다.

- [x] Python 함수형 문제를 안전한 별도 실행 환경에서 채점 가능 — Docker judge 어댑터 완료 (`JUDGE_BACKEND=docker`로 켠다)
- [x] 문제/세션/코드 snapshot/Event를 저장 가능
- [x] Run 결과가 Trace에 자동 연결됨
- [x] 최근 실행의 진전 여부와 반복 실패를 계산 가능
- [x] 의미 있는 trigger에서만 Agent를 호출함
- [x] Agent 결과를 구조화된 JSON으로 Frontend에 반환함
- [ ] TRACE/PREDICT 답변을 평가하고 원 문제 복귀 또는 replanning을 반환함
- [x] Agent 실패 시에도 Judge 결과는 정상 반환됨
- [ ] 호출 횟수, latency, token usage를 확인 가능 — trigger 횟수는 timeline summary에 있음

### 알려진 제약

**인증이 구현됐고**(JWT + bcrypt, 역할 3종) 클라이언트가 결과를 보고하던
`POST /results`도 제거됐다. 채점은 서버가 실행한 judge 결과만 인정한다.

남은 제약:

- **`/auth/refresh`가 없다.** access token 하나만 쓰고 만료되면 다시 로그인한다.
- **비밀번호 재설정 API가 없다.** 테이블(`password_reset_tokens`)만 있다.
- **기관 생성 API가 없다.** `scripts/seed_org.py`가 그 자리를 메운다.
- **감사 로그가 없다.** 교육자가 학생 코드를 열람한 기록이 남지 않는다.

Backend가 증명해야 할 핵심 메시지는 다음과 같다.

> **Backend는 코드를 실행하는 서버가 아니라, 실행과 수정의 연속을 학습 가능한 Process State로 변환하고 Agent의 자율적 개입을 가능하게 하는 기반 시스템이다.**
