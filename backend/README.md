# CodeTrace Backend — Coding Trace 파이프라인

학생의 편집/실행 이벤트를 영구 기록하고 → Code Snapshot + Diff로 변환하고
→ Process Feature로 압축하고 → 규칙 기반 Monitor가 Agent 호출 여부를 판정한다.

> Backend는 코드를 실행하는 서버가 아니라, 수정과 실행의 연속을
> 학습 가능한 Process State로 변환하는 시스템이다.

**JSON은 전부 snake_case다.**

## Setup

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Run

```bash
uvicorn app.main:app --reload --port 8000 --workers 1
open http://localhost:8000/docs
```

**`--workers 1`은 필수다.** SQLite + N워커 + 핫 카운터 행(`last_event_seq`)은
`database is locked` 생성기다.

## Test

```bash
pytest -q          # 146 tests
```

`tests/test_monitor.py`가 **데모 게이트**다. backend_plan §22의 필수 시나리오
(`2/5→3/5→4/5` 미발화 / `3/5×3` 발화 / syntax error 1회 미발화)가 여기서
초록이 아니면 하류의 어떤 것도 의미가 없다.

## Demo seed

```bash
python -m scripts.seed_demo
```

4개 데모 세션(PROGRESSING / STUCK / UNDERSTANDING_UNCERTAIN / RECOVERED)을 만들고
session_id를 출력한다. 그 다음:

```bash
curl localhost:8000/sessions/<id>/process-state | python -m json.tool
curl localhost:8000/sessions/<id>/timeline      | python -m json.tool
```

## API

```
GET  /health                                    judge/agent seam 상태
GET  /problems                                  목록 (테스트 데이터 없음)
GET  /problems/{problem_id}                     public 케이스 + hidden 개수/카테고리만

POST /sessions                                  세션 + SESSION_START + snapshot v1(템플릿)
GET  /sessions/{id}                             current_code 포함 (새로고침 복구용)
POST /sessions/{id}/finish                      멱등

POST /sessions/{id}/events                      배치 전용 {"events":[...]}
GET  /sessions/{id}/events?since_seq=&limit=
POST /sessions/{id}/results                     ★ 파이프라인의 척추
GET  /sessions/{id}/process-state               ★ 데모 패널용, 읽기 전용
GET  /sessions/{id}/timeline?collapse=true
GET  /sessions/{id}/snapshots
GET  /sessions/{id}/snapshots/{version}
GET  /sessions/{id}/snapshots/{version}/diff?from=

POST /sessions/{id}/run, /submit                → 503 JUDGE_UNAVAILABLE  (seam)
POST /agent/decide                              → action=WAIT            (seam)
```

에러 봉투: `{"detail": {"code": "...", "message": "...", "context": {...}}}`.
FastAPI의 422는 네이티브 배열 형태를 유지한다. 둘 다 `detail` 아래다.

### 프론트엔드가 지켜야 할 것

전체 연동 가이드는 **[plans/FRONTEND_INTEGRATION.md](../plans/FRONTEND_INTEGRATION.md)** 에 있다.

핵심만:

1. **`client_event_id`를 반드시 보낸다** (`crypto.randomUUID()`).
   이게 없으면 서버가 중복을 제거할 수 없고, 전송 실패 후 재시도가
   `RUN 3/5`를 다섯 번 기록해 monitor가 한 번 실행한 학생에게
   `REPEATED_FAILURE`를 외친다.
2. `code_version`은 **서버가 할당한다.** 클라이언트는 `CODE_SNAPSHOT`에
   `payload.code`만 담아 보내고 응답의 `current_code_version`을 받는다.
3. **Run/Submit 직전에 대기 중인 debounce 스냅샷을 flush한다.** 편집 창을
   `code_version`으로 자르기 때문에, 스냅샷이 결과보다 늦게 도착하면
   그 편집이 다음 결과의 창으로 밀려 판정이 어긋난다. 서버가 막을 수 없는 계약이다.
4. 오늘은 브라우저(Pyodide)가 채점하고 결과를 `POST /sessions/{id}/results`로 보낸다.
   서버 judge가 붙으면 `POST /run`으로 바꾸기만 하면 된다 — 백엔드는 그대로다.

## 아직 붙지 않은 것 (seam)

| 엔드포인트 | 오늘 | 켜는 법 |
|---|---|---|
| `POST /sessions/{id}/run`, `/submit` | 503 `JUDGE_UNAVAILABLE` | `JUDGE_BACKEND=docker` |
| `POST /agent/decide` | 항상 `action=WAIT` | `AGENT_BACKEND=llm` |

두 엔드포인트 모두 **최종 request/response 모양을 갖춘 채 OpenAPI에 이미 올라가 있다.**
프론트는 오늘 코드를 짤 수 있고, 켜질 때 양쪽 다 코드 수정이 없다.

`app/agent/context.py`(Agent Context Builder)는 **지금 동작한다.** LLM은 안 부르지만
`backend_plan §13`의 payload를 실제 trace 데이터로 채운다 — trace가 충분한지에 대한 증명이다.

### BE1의 Docker judge 병합 체크리스트

1. `pip install "docker>=7.0"`; `judge/`에서 `docker build -t judge-sandbox .`
2. `.env`: `JUDGE_BACKEND=docker`, `JUDGE_PATH=../judge`
3. **문제 디렉터리를 하나로 정한다.** `PROBLEMS_DIR`을 `../judge/problems`로 돌리거나
   (그 경우 우리 JSON의 `description`/`difficulty` 키를 그쪽에 복사),
   우리 것을 유지하되 양쪽 `problem_id` 집합이 같은지 확인. 디렉터리 둘이 drift 위험이다.
4. `run_judge()`는 `runtime_ms`를 반환하지 않는다 → BE1이 한 줄 추가하거나 `null`로 남는다.
5. 어댑터(`app/judge/docker_judge.py`)는 이미 작성되어 있다.

## 스키마를 바꾸면

Alembic을 쓰지 않는다. `create_all`은 절대 ALTER하지 않는다.

```bash
rm -f codetrace.db && uvicorn app.main:app --reload --workers 1
```

## 설계 노트

읽기 전에 알아두면 좋은 것들. 자세한 근거는 각 모듈 상단 docstring에 있다.

- **순서의 권위는 `seq`다. timestamp가 아니다.** 배치 이벤트는 `server_timestamp`가
  동일하고(microsecond 절삭) 클라이언트 시계는 무의미하다. 스냅샷과 결과의 순서 비교는
  `code_version`으로 한다. `ORDER BY server_timestamp`를 넣고 싶어지면 참으라.
- **에러 결과는 0점이 아니라 "관측 없음"이다.** `SYNTAX_ERROR`를 0점으로 세면
  `3/5 → syntax → 3/5`가 `[3,0,3]`이 되어 `progress_delta=+3` → 명백히 막힌 학생이
  `PROGRESSING`으로 방치된다. §22.3의 "syntax error 1회 미발화"도 여기서 구조적으로 나온다.
- **`evaluate()`는 아무것도 쓰지 않는다.** cooldown 상태가 `AGENT_TRIGGER` 이벤트에 살기 때문.
  데모 패널이 `/process-state`를 폴링하는데 GET이 cooldown을 소진하면
  정작 agent를 불러야 할 Run이 cooldown에 걸린다.
- **영역 태깅은 `ast`가 아니라 regex다.** 태깅 대상이 *편집 중인 학생 코드*이고
  상당 비율이 문법적으로 무효인데, 그 무효성이 바로 우리가 관찰하려는 모집단이다.
  `ast.parse`는 모듈 전체에 `SyntaxError`를 던져 파일 전체를 태그 0개로 만든다.
- **문제는 DB가 아니라 JSON 파일이 진실이다.** `origin/judge`가 이미 그렇게 하므로
  DB에도 두면 병합 시 반드시 drift한다. 부수 효과로 hidden test가 ORM에 실리지 않아
  어떤 `response_model` 실수도 유출을 만들 수 없다.
- **naive UTC 저장, 출력 시 강제 `Z`.** SQLite는 읽을 때 tzinfo를 버리고,
  `Z`가 없으면 JS가 로컬로 파싱해 KST에서 9시간이 밀린다.

## 알려진 제약

- **인증이 없다.** 악의적 클라이언트가 `/results`에 조작된 `5/5`를 보낼 수 있다.
  MVP 범위 밖이고, `POST /run`(서버 judge)이 유일한 결과 경로가 되면 닫힌다.
  값싼 방어(`0 <= passed <= total <= 100`, `status ∈ JudgeStatus`)는 이미 들어 있다.
- `FINISHED` 세션의 이벤트도 409가 아니라 플래그(`session_finished: true`)와 함께 수락한다.
  현실적 원인은 `/finish` 직후 큐 flush뿐인데 409는 무대에 빨간 배너를 띄운다.

## 이번 범위 밖

Docker judge 실행, LLM 호출, Activity/`answer_key`, learner state, analytics 엔드포인트.
