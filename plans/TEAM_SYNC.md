# 팀 조율 문서 — 통합 전 결정해야 할 것들

> **갱신: 2026-08-13 · 모든 브랜치가 `main`에 머지된 뒤 기준.**
> 아래 본문은 최초 감사(브랜치 4개가 갈라져 있던 시점) 그대로 두었다.
> 각 항목의 근거와 실패 모드가 여전히 읽을 값이 있어서다.
> **무엇이 해결됐고 무엇이 남았는지는 이 표를 본다.**

## 해결됨 (재논의 불필요)

| # | 항목 | 어떻게 |
|---|---|---|
| [0] | 브랜치 머지 | 6개 브랜치 전부 `main`에 머지 |
| [2] | 파서를 stdout_match까지 확장 | judge 26문제가 전부 파싱된다 (실측 OK 26 / FAIL 0) |
| [3] | `concept` vs `concepts` | **단수 `concept`으로 확정.** 응답 스키마 수정 완료 |
| [5] | 프론트 진입점 계약 | `POST /sessions/{id}/run\|submit` 으로 이전. `POST /results` 제거 |
| [6] | `get_agent()`가 500을 내던 문제 | `WaitAgent` 폴백 + 경고 |
| [7] | 개입 판단 소유권 | `entry_agent.py` 삭제, `state_agent`의 규칙 게이트로 통합 |
| [13] | 에러 봉투 모양 통일 | `traceClient.errorMessage()`가 3형태를 전부 처리 |
| — | `description_summary`가 `"## 문제"`를 뽑던 문제 | `_first_prose_line()` |
| — | 인증 부재 | JWT + bcrypt + 역할 3종 구현 |
| — | 도토리 조작 경로 | `POST /results` 제거. 서버 judge 결과만 인정 |
| — | `/agent/decide` 소유권 검사 없음 | `require_session(user_id=...)` 추가 |

## 남은 것

| # | 항목 | 상태 |
|---|---|---|
| **[신규]** | **프론트가 `Authorization` 헤더를 안 보낸다** | **가장 시급.** 로그인 화면이 API를 안 부른다 → 붙이면 전부 401 |
| [1] | 문제 정본 = `judge/problems` 26개 | **미실행.** 파서는 준비됐다(`PROBLEMS_DIR` 한 줄). 다만 23개에 `concept`/`difficulty`가 비어 있다 |
| [4] | 8000 포트 = backend 단독 | **미실행.** `judge/main.py`가 아직 8000에 `/problems`·`/judge`를 노출한다 |
| [8] | AgentContext ↔ agent 어댑터 | **미실행.** 어댑터가 없어 `AGENT_BACKEND=llm`이 `WaitAgent`로 폴백 |
| [9] | LLM 호출 예산 / 타임아웃 | 5회 → 4회로 줄었으나 `agent.decide()`에 여전히 타임아웃 없음 |
| [10] | Activity 생성 주체 | **미실행.** `TRACE_CODE` 하드코딩, 생성기 없음 |
| ~~[12]~~ | ~~`INTERNAL_ERROR`~~ | **해결됨.** judge가 인프라 장애 4곳을 `INTERNAL_ERROR`로 반환하고, backend가 `SYSTEM_STATUSES`로 분리해 오류 횟수에서 제외한다(+ monitor R1s 게이트). 프론트 유니온·라벨은 PR #13에서 이미 들어갔다 |
| [15] | hidden 테스트 공개 노출 | 미결정 (공개 레포에 185개) |
| — | 교육기관 UI | 백엔드 9개 엔드포인트 완성, 화면 0줄 |
| [16] | 문제 JSON 스키마 문서 | **미실행.** `judge/README.md`가 `CLAUDE.md`를 가리키는데 그 파일은 `.gitignore` 대상이라 팀원이 볼 수 없다 |
| — | 마이그레이션 감지 | 스키마가 바뀌어도 조용히 옛 DB로 돈다 |

---


## 한눈에 보기 — 의존 관계

```
[0] 브랜치 머지 (backend FF → frontend 수작업)
     ↓ 코드가 한 트리에 모여야 아래 작업이 서로 안 밟힘
[1] 문제 데이터 정본 = judge/problems 로 확정   ←── 가장 먼저 정해야 할 결정
     ↓
[2] backend 파서/스키마 확장 (stdout_match, concept 이름, time_limit)
     ↓
[3] 8000 포트 소유권 = backend 단독
     ↓
[4] 프론트 진입점 계약 (POST /judge 어댑터 vs 세션 계약 이전)
     ↓
[5] agent 연결 방식 (in-process vs HTTP) + get_agent 폴백 버그
     ↓
[6] 개입 판단 소유권 = monitor 단일화
     ↓
[7] AgentContext ↔ agent 어댑터 계약 (+ 호출 예산/타임아웃)
     ↓
[8] Activity 생성 소유권
```

**오늘 안에 답이 나와야 하는 결정은 [1], [3], [4], [5], [6] 다섯 개다.** 나머지는 이 다섯 개가 정해지면 구현 작업으로 내려간다.

---

## 1단계 — 지금 당장 (오늘 결정 / 오늘 실행)

### [0] 브랜치 머지: backend는 FF, frontend는 6개 파일 충돌

**누가 결정하는가**: 전원 합의(순서) + **App.tsx 담당자를 FE 두 명 중 한 명으로 지정**

- `origin/backend`는 `origin/main`의 직계 자손이라 **fast-forward로 충돌 0건** (`git merge --ff-only origin/backend`).
- `origin/frontend`는 머지 베이스가 초기 커밋(`20adeee`)이라 공통 조상이 없다. 충돌 파일은 **6개**다: `frontend/README.md`, `src/App.tsx`, `src/LoginPage.tsx`, `src/SignupPage.tsx`, `src/pythonRunner.ts`, `src/styles.css`.
- backend를 먼저 머지해도 frontend 충돌 파일 집합은 동일하다(순서 무관, 새 충돌 추가 없음).

**해결 방법 (파일별로 난이도가 극단적으로 갈린다)**

| 파일 | numstat (+/-) | 처리 |
|---|---|---|
| `pythonRunner.ts` | 45 / 0 | `--theirs` (frontend가 완전 상위집합) |
| `README.md` | 46 / 0 | `--theirs` |
| `LoginPage.tsx` | 84 / 2 | `--theirs` (삭제 2줄은 import 확장·비밀번호 토글로 대체된 줄) |
| `SignupPage.tsx` | 18 / 2 | `--theirs` (동일) |
| `styles.css` | 253 / 12 | `--theirs` 기반 + main의 `.section-kicker` / `.lesson-title` 규칙만 복원 |
| `App.tsx` | 203 / 110 | **사람이 수작업** — 19개 hunk 중 17개가 양방향 |

```
git checkout --theirs frontend/src/pythonRunner.ts frontend/README.md \
                      frontend/src/LoginPage.tsx frontend/src/SignupPage.tsx && git add
```
로 4개를 먼저 털어내면 사람이 볼 파일은 `App.tsx` 하나로 줄어든다.

**주의 (실수하기 쉬운 지점)**

- `styles.css`를 **main 기준으로 잡으면 안 된다.** frontend가 253줄을 새로 썼고 삭제는 12줄뿐이다. main 기준으로 잡으면 다크테마 토큰, `.judge-message`, `.failed-categories`, `.trace-button`, 반응형 블록이 통째로 날아간다.
- 단, frontend의 `styles.css`에는 `.section-kicker`가 없는데 `LoginPage.tsx:34,85`와 `SignupPage.tsx:26`이 그 클래스를 쓴다. main에서 그 1줄만 살려와야 로그인/회원가입 화면 kicker 텍스트가 무스타일이 되지 않는다.
- `frontend/src/problem.ts`는 지우지 마라. `pythonRunner.ts:2`가 `import type { TestCase } from './problem'`로 아직 참조한다.
- **AuthView 게이트는 충돌 밖이다.** `useState<AuthView>('login')`, `<LoginPage/>`, `<SignupPage/>`는 마커 바깥 공통 영역에 있어 자동 머지된다. App.tsx 수작업의 실제 부담은 auth가 아니라 `problemService`/`traceActivity`/테마토글 배선이다.
- `git checkout origin/frontend -- .` 류의 명령을 쓰지 마라. 2-dot diff 기준 `origin/frontend`에는 judge 코드 12개, agent 16개, 루트 `.gitignore`가 없어서 그대로 삭제된다. 판단은 3-dot(`origin/main...origin/frontend`)으로 하고, 머지 전에 `git diff --cached --diff-filter=D --name-only`로 삭제 목록을 확인할 것.

**머지 직후 반드시 할 것 (1줄)**: `frontend/vite.config.ts`에 `server: { fs: { allow: ['..'] } }` 추가.
`problemService.ts:1-2`가 `'../../judge/problems-index.json'`을 import하는데 이건 Vite 프로젝트 루트(`frontend/`) 바깥이다. 레포 루트에 `package.json`/lock/workspace 표지가 없어 workspace root가 `frontend/`로 확정되고, `server.fs.allow` 기본값도 `frontend/` 하나가 된다. **`vite build`는 통과하고 `npm run dev`만 403이 날 가능성이 높다** — CI가 build만 돌리면 영구히 은폐된다. 그러니 **머지 검증은 `npm run build`가 아니라 `npm run dev`로 하라.** (node_modules가 없어 실행 검증은 못 했다. 관측된 실패가 아니라 구성상 위험이다.)

---

### [1] 문제 데이터 정본을 하나로 확정한다 — 나머지 절반이 여기 걸려 있다

**누가 결정하는가**: **judge 담당(BE1) + backend 담당(사용자) 합의.** 프론트는 결과 통보만 받으면 된다.

지금 같은 데이터가 네 곳에 있다.

| 위치 | 개수 | 성격 |
|---|---|---|
| `judge/problems/*.json` | 26 (func 3 + stdout 23) | 채점기가 런타임에 실제로 읽는 파일 |
| `judge/problems-index.json` / `problems-detail.json` | 26 | 프론트 공유용 수작업 export (생성 스크립트 없음) |
| `backend/app/problems/data/*.json` | 3 | backend가 읽는 파일 |
| `frontend/src/problem.ts` | 1 (`sum_even`) | 어느 카탈로그에도 없는 데모 잔재 |

**확인된 사실**
- `func_*` 3개는 두 곳에 중복 존재하며 **이미 내용이 다르다.** `hidden_test_cases`/`public_test_cases`/`code_template`은 바이트 동일하지만, `description`(backend 평문 vs judge `## 문제` 마크다운), `difficulty`(backend에만 있음, judge 26개 전부 없음), `concept`(`func_sum_list`: `[loop,accumulator,function]` vs `[loop,function]`; `func_count_positive`: `condition` vs `conditional`)이 갈린다.
- `docker_judge.py:46`은 `ProblemRecord`를 받고도 `problem.problem_id`만 넘기고, `judge_service.py:85`가 `PROBLEMS_DIR`(`:18` 하드코딩)에서 파일을 **다시 읽는다.** `interface.py` 주석의 "시스템에 문제 로더가 정확히 하나만 존재한다"가 자기 어댑터에서 이미 깨져 있다. 결과적으로 병합 후에는 학생에게 보이는 지문은 backend 파일에서, 채점 total은 judge 파일에서 나오게 된다.
- `problems-index.json` / `problems-detail.json`은 현재 원본과 drift가 0이지만 **생성 스크립트가 레포에 없다**(커밋 `efb7c85`, `8662dc3`로 수동 추가). 문제 JSON을 고치면 조용히 낡는다.
- 프론트는 API 실패 시 로컬 26개로 **조용히 폴백**한다(`problemService.ts:69-83`). backend에 붙으면 목록이 3개가 되고, 캐시/이전 화면에서 `stdout_*` id로 진입하면 404를 받은 뒤 로컬 상세로 폴백해 **"화면엔 보이지만 서버엔 없는" 유령 문제**가 된다.

**권장 결정**: 정본 = `judge/problems/*.json` 26개. backend가 `PROBLEMS_DIR=../judge/problems`로 그것만 읽는다.
근거는 단순하다 — judge에 26개가 이미 있고 채점기가 실제로 그 파일을 읽으며, 프론트 UI에 '입출력형' 필터가 이미 있다. 반대로 judge에서 23개를 버릴 수는 없다.

**단, 지금 바로 `PROBLEMS_DIR`을 돌리면 backend가 기동 중 죽는다. [2]를 먼저 끝내야 한다.**

**결정 즉시 할 일**
- backend/README.md의 "BE1의 Docker judge 병합 체크리스트" 3번과 `docker_judge.py` 상단 주석에 **"[2] 완료 전까지 실행 금지"** 경고를 단다. (README 원문은 "돌리거나 … 우리 것을 유지하되"라는 택일 지시이지 "그냥 돌리면 된다"가 아니다. 그래도 한쪽 선택지를 고르면 크래시한다는 사실은 어디에도 적혀 있지 않다.)
- `parse_problem` 독스트링(`service.py:69-72`)의 "PROBLEMS_DIR을 judge 쪽으로 돌려도 그대로 파싱되게 하기 위함"은 26개 중 23개에서 거짓이므로 함께 수정.

---

### [2] backend 파서/스키마를 stdout_match까지 지원하도록 확장한다

**누가 결정하는가**: 결정 불필요 — **[1]이 확정되면 backend 담당(사용자)의 구현 작업.** 단 `concept` 이름(아래)만 judge·frontend와 합의 필요.

**실측 재현됨**: `judge/problems/*.json` 26개를 backend의 `parse_problem` 로직으로 파싱하면 **OK 3 / FAIL 23**, 전부 `KeyError('function_name')`. 그것을 고쳐도 두 번째 벽에서 `KeyError('input')`이 난다.

원인은 두 겹이고 한 줄 수정으로 끝나지 않는다.

1. `service.py:81` — `function_name=data["function_name"]` (`.get()`이 아님). stdout 문제엔 이 키가 없다(stdin/stdout으로 채점하므로 필요가 없다).
2. `service.py:57-58` — `input=tc["input"]`, `expected=tc["expected"]`. stdout 테스트케이스의 키는 `{stdin, expected_stdout, category}`다.
3. 응답 스키마도 그릇이 없다. `TestCasePreview.input: list[Any]` / `expected: Any` 필수, `ProblemSummary.function_name: str` 필수.
4. `reload()`가 `__init__`에서 `sorted(glob)` 전체를 파싱하므로 **파일 하나 실패 = 저장소 전체 사망**. 정렬상 `func_*` 3개를 통과한 뒤 `stdout_bigger_number.json`에서 죽고, `get_problem_repository()` 의존성 주입 자체가 실패해 `/problems`, `/sessions`, `/sessions/{id}/run` 전부 500이 된다.

**할 일 목록 (backend)**
- `function_name`을 `str | None`으로, `data.get("function_name")`으로. `ProblemSummary`/`ProblemDetail`도 Optional. → **프론트는 이미 `function_name?: string`이라 수정 0줄.**
- `TestCase`/`TestCasePreview`를 `input`/`expected` + `stdin`/`expected_stdout` 양쪽 담을 수 있게(전부 Optional) 하고 `check_type`으로 유효한 쪽을 결정. `_parse_test_cases`는 `.get()`으로.
- `time_limit_sec` / `memory_limit_mb`를 `ProblemRecord`/`ProblemDetail`에 추가. judge JSON에 이미 있고 프론트 타입에도 이미 optional로 있다. 지금은 항상 undefined라 문제 화면의 시간/메모리 제한 표기가 사라진다.
- `reload()`에서 개별 파일 파싱 실패가 저장소 전체를 죽이지 않게 로그 후 skip.
- `context.py:63`의 `description_summary = description.split("\n")[0]`을 고친다. judge 데이터를 쓰면 첫 줄이 리터럴 `"## 문제"`가 되어 그 무의미한 문자열이 모든 에이전트 프롬프트에 들어간다. → `next((l for l in description.splitlines() if l.strip() and not l.startswith('#')), '')`
- `backend/tests/test_problems_api.py:15`의 하드코딩 `3`과 `:47`의 `ALLOWED_DETAIL_KEYS`도 함께 갱신.

**judge 담당(BE1)에게 필요한 것**
- `difficulty`: judge 26개 파일에 전부 없다. backend 기본값 `"BEGINNER"` 유지로도 동작하지만(프론트 타입에 difficulty가 없어 화면에는 안 뜬다), 목록에 난이도 배지를 띄우려면 스크립트로 한 번에 채워야 한다.
- `stdout_*` 23개의 `concept`이 전부 `[]`다. 최소한 `loop`/`conditional`/`arithmetic`/`string` 정도는 붙여야 agent 개입 로직이 개념 신호를 받을 수 있다.
- `problems-index.json`에 `check_type`을 추가. 지금 `problemList.tsx:27`이 `problem_id.startsWith('func_')`로 유형을 추론하는데(index에 `check_type`이 없어서 생긴 우회다), 이러면 `problem_id` 명명규칙이 암묵적 API 계약이 된다. 세 곳(index 생성, `list_all_problems`, `ProblemSummary`) 한 줄씩이면 없앨 수 있다.

---

### [3] `concept` vs `concepts` — 응답 키 이름을 오늘 하나로 못박는다

**누가 결정하는가**: **backend 담당 + frontend 담당 + 문서 소유자 합의.** backend 단독 결정이 아니다.

- 문제 JSON 파일 **전부**(backend 3 + judge 26): `"concept"` (단수)
- `judge_service.py:66` 응답: `"concept"`
- 프론트 `problemService.ts:7,120,135`: `item.concept`만 읽음
- backend `ProblemSummary`/`ProblemDetail` 응답: `"concepts"` (복수)
- **`plans/FRONTEND_INTEGRATION.md` §7의 `GET /problems` 응답 예시: `"concepts": [...]`** ← 팀의 문서화된 계약은 복수형이다

`parse_problem`은 입력 단계에서 `concepts`/`concept` 둘 다 받아주지만(`service.py:73`) **출력 키는 `concepts` 하나뿐**이다. 입구는 관대하고 출구만 이름이 바뀐 상태. 그래서 프론트를 backend로 붙이면 `Array.isArray(item.concept)`가 항상 false → `concept: []`로 정규화된다. **에러도 경고도 없이 조용히 사라진다.** 증상은 문제 카드 개념 배지 공백, 그리고 `problemList.tsx`의 검색(`${title} ${problem_id} ${concept.join(' ')}`)에서 개념 키워드 검색 무력화.

**선택지**
- (A) backend 응답을 `concept`으로 맞춘다 — 파일·judge·프론트 3:1이라 rename 비용 최소(`schemas.py` 2줄). **단 `FRONTEND_INTEGRATION.md` §7을 함께 고쳐야 한다.**
- (B) `concepts`를 유지하고 프론트가 마이그레이션 — Pydantic `Field(serialization_alias="concept")` + `populate_by_name`으로 과도기에 두 이름을 동시 노출할 수도 있다.

어느 쪽이든 **`problems-index.json` 생성 로직까지 같은 이름으로 통일**할 것.

곁다리로 정리할 것: `AgentDecision.concept`(단수, `str|None`)은 "개입 대상 개념"이라 의미가 완전히 다르다. `target_concept` 등으로 개명해 이름 충돌을 없애는 게 좋다.

---

### [4] 8000 포트 소유권 — 서버를 하나로 줄인다

**누가 결정하는가**: **judge 담당(BE1) + backend 담당(사용자).**

`judge/main.py`는 `GET /problems`, `GET /problems/{id}`, `POST /judge`를 8000에 띄우고, backend도 `GET /problems`, `GET /problems/{id}`를 8000에 띄운다. **경로 2개가 완전히 겹치고 포트도 같아 두 서버를 동시에 실행할 수 없다.** 지금은 팀원마다 어느 서버를 8000에 띄웠느냐에 따라 다른 화면을 보고 다른 버그를 보고하게 된다.

`judge/main.py` 상단 독스트링이 이미 예고해뒀다 — "지금은 backend가 아직 없어서 임시로 노출한다, 나중에 backend가 생기면 이 레이어는 옮기거나 backend가 이 서비스를 호출하는 구조로 바뀔 수 있다". **그 시점이 도래했는데 `origin/main`에 `judge/main.py`가 그대로 머지되어 소유권이 미확정이다.**

**권장 결정**: `judge/main.py`를 HTTP 서버에서 은퇴시키고 judge는 `judge_service.py`(라이브러리) + Dockerfile만 남긴다. `backend/app/judge/docker_judge.py`가 이미 그 어댑터다(`JUDGE_BACKEND=docker`, `JUDGE_PATH=../judge`). 8000은 backend 단독 소유.

당장 지우기 부담스러우면 **최소한 `judge/main.py`의 실행 포트를 8001로 바꾸고 README 두 곳(`judge/README.md:32`, `backend/README.md:23`)에 "개발용, 프론트는 붙지 않음"을 명시**할 것.

부수 효과로 프론트의 단일 `VITE_API_BASE_URL` 문제가 소멸한다. 프론트는 잘못한 게 없다 — 단일 base URL은 "서버는 하나"라는 정상적 전제이고, 이 결정이 그 전제를 성립시킨다. CORS도 backend `cors_origins`에 `5173`이 이미 들어 있어 그대로 동작한다.

---

### [5] 프론트 진입점 계약 — `POST /judge`가 backend에 없다

**누가 결정하는가**: **frontend 담당 + backend 담당.** [4]에 의존한다.

프론트 `App.tsx:108`은 '실행'/'제출하기' 버튼 양쪽 모두 `judgeCode()` 하나만 호출하고, `judgeCode()`는 `POST {VITE_API_BASE_URL}/judge`로 `{student_code, problem_id, mode}`를 보내 평면 `{passed,total,status,message?,failed_categories?}`를 기대한다. **이 계약을 만족하는 건 `judge/main.py:61`의 임시 API뿐이다.**

backend에는 `/judge` 경로가 없다(problems/sessions/trace/judge/agent 5개 라우터 전수 확인). 대응되는 것은 `POST /sessions/{id}/run`과 `/submit`이고 **세 가지가 전부 다르다**:

| | 프론트가 보내는 것 | backend가 받는 것 |
|---|---|---|
| 경로 | `/judge` | `/sessions/{session_id}/run` \| `/submit` |
| 바디 | `{student_code, problem_id, mode}` | `RunRequest{code, code_version}` (mode는 경로 분기, problem_id는 세션에서 유도) |
| 응답 | 평면 `{passed,total,status}` | `ResultIngestResponse{event, process_state, agent_decision}` — passed/total은 `event.payload` 안 |

**그리고 프론트에는 세션 개념 자체가 없다.** `origin/frontend`의 `src` 전체를 grep해도 `/sessions`, `/events`, `/results`, `client_event_id`, `code_version`, `process-state` 문자열이 **단 하나도 없다.** 즉 backend가 구현한 Coding Trace 파이프라인 전체(events/results/process-state/timeline/snapshots/agent)가 데모에서 **한 번도 실행되지 않는다.** `plans/FRONTEND_INTEGRATION.md` §3·§5가 "세션 생성 → 스냅샷 flush → 채점 → `POST /sessions/{id}/results`" 흐름을 프론트 계약으로 상세히 규정해뒀지만 어느 항목도 구현되지 않았다.

`VITE_API_BASE_URL`을 backend로 돌리면 `/problems`는 200이 오는데 `/judge`만 404가 나서 `JudgeErrorView('채점 서버에 연결할 수 없어요')`만 뜬다. **부분적으로 동작해서 원인 찾기가 더 어렵다.**

**선택지 (둘 중 하나를 오늘 고른다)**

- **(A) 호환 어댑터 — 데모 전이면 권장.** backend에 얇은 `POST /judge {student_code, problem_id, mode} -> 평면 JudgeResult`를 추가한다. 내부적으로 세션이 없으면 만들고 `judge_service.run_judge`를 호출한 뒤 `judge/main.py`와 바이트 동일한 응답을 돌려준다. **프론트 수정 0줄이고 `judge/main.py`를 그대로 은퇴시킬 수 있다.** 다만 이 경로로 trace가 쌓이게 할지(세션 생성 + 이벤트 기록까지 서버가 대신할지)는 구현 시 명시적으로 정해야 한다.
- **(B) 정식 경로 이전.** 프론트가 ① 문제 진입 시 `POST /sessions {problem_id, user_id}` → session_id 보관, ② `execute()`를 `POST /sessions/{id}/run|submit {code}`로 교체, ③ 응답 파싱을 `ResultIngestResponse` 기준으로(`res.event.payload`의 passed/total, `res.agent_decision`), ④ 편집 debounce 스냅샷을 `POST /sessions/{id}/events`로 배치 전송.

**현실적 권고**: A로 데모를 뚫고 B를 후속 과제로. 단 **A를 고르더라도 세션 생성(①)만은 붙이는 것을 권한다** — 그래야 monitor와 agent_decision이 살아나고, 이 프로젝트의 핵심 주장인 Coding Trace 파이프라인이 데모에서 실제로 돌아간다.

> 참고: backend의 run/submit은 오늘 `UnavailableJudge` 때문에 503 `JUDGE_UNAVAILABLE`이다. 경로를 고쳐도 `JUDGE_BACKEND=docker`를 켜지 않으면 채점은 안 된다.

---

### [6] agent 연결 방식 — 지금은 잇는 코드가 하나도 없고, 켜는 순간 500이 난다

**누가 결정하는가**: **agent 담당 + backend 담당(사용자).**

레포 전체에서 backend 코드가 `tutor_agent`/`strands`를 참조하는 지점이 **0건**이고, `backend/requirements.txt`에 `strands-agents` 의존성이 없다. 두 프로젝트는 런타임도 분리돼 있다(backend: requirements.txt + `.venv` / agent: pyproject.toml + uv.lock + 자체 `.env`). `agent/README.md`의 TODO가 이 공백을 그대로 적어뒀다 — "SessionContext 생성 지점을 backend 쪽에 연결".

**먼저, 결정과 무관하게 오늘 고칠 수 있는 폴백 버그가 하나 있다.**

`backend/app/agent/__init__.py:10-14`의 `get_agent()`는 `agent_backend=='llm'`이면 `raise NotImplementedError`다. 그런데 `get_agent`는 라우터에서 `agent: AgentProtocol = Depends(get_agent)` 형태의 FastAPI 의존성으로 쓰인다(`trace/router.py:142`, `judge/router.py:126`). **의존성 해석은 핸들러 본문 진입 전에 일어나므로 `router.py:186`의 `except`가 이 예외를 잡을 기회가 없다.** 즉 `.env`에 `AGENT_BACKEND=llm`을 넣는 순간 `agent_decision=null`로 우아하게 빠지는 게 아니라 **`POST /sessions/{id}/results`와 `/run`이 통째로 500**이 나고, `backend_plan §14`의 "Judge 결과는 Agent 실패와 무관하게 반드시 반환한다"가 무력화된다.
→ **`get_agent()`에서 예외 대신 `WaitAgent` 폴백 + 로그로 바꾼다. 통합 여부와 무관하게 지금 고칠 수 있다. 담당: backend.**

**연결 방식 선택지**

- **(A) in-process 어댑터 — 권장.** 2일 MVP에서 서비스를 하나 덜 띄운다.
  1. backend venv에 `pip install -e ../agent`, `backend/requirements.txt`에 의존성 명시
  2. `get_agent()`의 `llm` 분기에서 [7]의 어댑터를 import해 반환
  3. `agent/src/tutor_agent/agents/`와 `tools/`에 `__init__.py`가 없다. `pyproject.toml`의 `[tool.setuptools.packages.find] where=["src"]`는 `find_packages` 의미론이라 **비-editable 설치(`pip install ./agent`)에서는 두 서브패키지가 휠에 포함되지 않아 `orchestrator.py:15`의 `from .agents import ...`가 ImportError를 낼 수 있다.** README가 안내하는 `pip install -e` 경로에서는 src 경로 훅 덕에 대체로 동작한다. `__init__.py` 두 개를 추가하거나 `find_namespace_packages`로 전환할 것.
  4. `ANTHROPIC_API_KEY` 등 모델 설정을 `backend/.env.example`에도 문서화. **`agent/models.py`가 `load_dotenv()`로 CWD 기준 `.env`를 읽으므로 backend 프로세스에서는 `backend/.env`를 본다.**
- **(B) HTTP 분리.** `agent/`에 서버 진입점이 아예 없으므로 `judge/main.py` 같은 얇은 API를 새로 만들어야 하고, 그 경우에도 backend 쪽 `HttpAgent` 어댑터는 여전히 필요하다.

---

### [7] 개입 판단(should_enter / should_intervene)의 소유권 = monitor

**누가 결정하는가**: **agent 담당.** 단 계획서에 이미 답이 명문화돼 있어 사실상 확인 절차에 가깝다.

같은 결정을 두 곳이 한다.

- `entry_agent.decide()`가 `SessionContext`를 통째로 LLM에 넣고 `EntryDecision.should_enter`를 받는다. 프롬프트: "마지막 개입 이후 충분한 시간/이벤트가 지났는가", "너무 자주 개입하면 학습을 방해합니다".
- `state_agent`도 프롬프트 3번 항목으로 `should_intervene`/`urgency`를 결정하고, `orchestrator.py:43`이 False면 파이프라인을 멈춘다.
- `backend/app/trace/monitor.py`가 이미 규칙으로 같은 판단을 한다 — `_cooldown()`(30초 또는 다음 Run까지), R1 cooldown 게이트, R3 진전 가드, R0 HELP_REQUESTED.

**monitor 쪽이 맞다. 근거는 팀 계획서다.**
- `plans/agent_plan.md:63-64` — "모든 이벤트에 LLM을 호출하지 않는다 / Process Monitor는 규칙 기반으로 구현한다"
- 같은 문서 `:41` — "Monitor가 trigger를 만들 때만 Agent가 호출된다. 호출 시점 판단은 이미 끝나 있으므로 Agent는 '무엇을 할 것인가'만 결정하면 된다"
- `:368` — "어떤 방식으로 학습시킬지 선택 (호출 여부는 Monitor가 이미 결정)", `:371` — "이 분리를 통해 비용과 지연을 줄인다"
- `plans/backend_plan.md:639` — "Monitor는 Agent가 아니다. LLM을 부르지 않고 결정론적 규칙만으로 판정한다"

**구조적으로도 agent 쪽이 이길 수 없다.** entry_agent/state_agent는 cooldown 이력(`AGENT_TRIGGER` 이벤트), `same_region_edit_count`, `progress_delta` 같은 판단 근거를 아예 갖고 있지 않다. 게다가 backend 경로에서 agent가 호출되는 시점 자체가 monitor가 trigger를 발화한 직후라(`trace/router.py:171-178`, `judge/router.py:90-96`), LLM이 `should_enter=False`를 내면 **monitor는 이미 `AGENT_TRIGGER` 이벤트를 기록해 cooldown만 소진하고 아무 개입도 못 하는 최악의 조합**이 된다.

**결정 후 작업 (agent 담당)**
- `TutorPipeline.run()`의 entry 단계를 backend 연동 경로에서 제거. backend가 만든 trigger/status/evidence를 그대로 입력으로 받는다.
- `entry_agent.py`를 남기려면 agent 단독 데모 전용 경로로 격리하고 `agent/README.md`에 "백엔드 연동 시 미사용" 명시.
- `StudentState`에서 `should_intervene`을 삭제하거나 연동 경로에서 무시. **state_agent의 나머지 절반(상태 해석, `struggle_signals`, 막힌 개념 추정)은 중복이 아니라 agent 고유 역할이다** — `agent_plan.md §3.1`이 요구하는 `suspected_concept`/`confidence`는 monitor에 없다(monitor는 `ProcessStatus` 6종만 낸다).
- `urgency`는 개입 여부가 아니라 action 강도 선택 입력으로만 쓴다.

---

## 2단계 — [5]~[7] 결정 직후 착수 (데모 전까지)

### [8] AgentContext ↔ agent 어댑터 계약 — 이게 이 프로젝트의 진짜 seam이다

**누가 결정하는가**: **agent 담당 + backend 담당 공동 설계.** 구현은 agent 쪽 어댑터 + backend 3필드 추가로 나눈다.

세 층위에서 전부 어긋난다. **단순 글루가 아니라 계약 재협상이 필요하다.**

**(1) 입력 — 필드 이름 교집합이 정확히 0이다**

`AgentContext`(frozen dataclass, 11필드): `session_id, problem, current_code, current_code_version, judge_result, recent_trace, features, process_status, trigger, evidence, previous_interventions`
`SessionContext`(Pydantic BaseModel, 7필드): `student_id, problem_id, code, run_history, elapsed_seconds, idle_seconds, last_error`

- agent가 **필수로 요구하는데 backend가 안 주는 것**: `student_id`(기본값 없음 — `build_context()`에 넣는 줄이 없다), `problem_id`(backend에선 `ctx.problem["problem_id"]`로 한 단계 중첩). 둘 다 Pydantic ValidationError 사유다.
- **`idle_seconds`는 backend에 대응 필드가 아예 없다.** 가장 가까운 `seconds_without_progress`는 정의상 "마지막 **진전**(채점 점수 상승) 이후"라 학생이 활발히 편집·실행 중이어도 점수가 안 오르면 무한히 커진다. 그대로 매핑하면 **열심히 푸는 학생을 방치 상태로 오판한다.** state_agent 프롬프트의 "학생이 정상적으로 사고 중인 짧은 정적은 개입하지 마세요"가 이 값으로는 성립하지 않는다.
- `elapsed_seconds`: agent는 float 최상위, backend는 `features` dict 안에 int로 중첩.
- `run_history`: agent 도구는 `"3/5 tests passed"` 형태의 실행 결과 로그를 가정하는데, backend의 `recent_trace_labels()`는 `"accumulator 영역 수정 (3줄)"`, `"AGENT TRIGGER: NO_PROGRESS"` 같은 편집/에이전트 라벨까지 섞어 넣는다.
- **backend가 주는데 agent가 못 받는 것 — 전부 버려진다**: `features` 19개 필드 전부(`same_result_count`, `progress_delta`, `improved_recently`, `same_region_edit_count`, `repeated_edit_region`, `undo_count`, `large_change_detected`, `consecutive_error_count` …), `process_status`, `trigger`, `evidence`, `previous_interventions`, `judge_result`, `problem{title,concepts,description_summary,function_name}`.

> **이게 특히 아픈 이유**: `context.py` 상단 독스트링이 "trace 데이터가 실제로 충분한지를 오늘 증명한다"고 선언한 그 payload가 **통째로 agent에 도달하지 못한다는 뜻이다.** 이 프로젝트의 논지를 정면으로 약화시킨다.

- 타입 종류도 다르다. 5개 에이전트가 전부 `ctx.model_dump_json(indent=2)`를 프롬프트에 붓기 때문에 frozen dataclass를 그대로 넘기면 AttributeError.

**(2) 진입점 — 이름·시그니처가 다르다**
backend가 기대하는 계약은 `decide(ctx: AgentContext) -> AgentDecision` 단 하나(`interface.py:40-43`). agent 진입점은 `TutorPipeline.run(ctx: SessionContext) -> PipelineResult`.

**(3) 출력 action — 두 enum이 직교한다 (교집합 0)**

| | 값 | 축 |
|---|---|---|
| backend `AgentAction` | `WAIT/HINT/TRACE/PREDICT/DEBUG/VERIFY` (대문자 6종) | **어떤 교수법으로 개입할 것인가** |
| agent `ActionPlan.action_type` | `send_message/highlight_code/show_example/no_op` (소문자 4종) | **UI에 무엇을 렌더할 것인가** |

억지로 대응시키면 `no_op↔WAIT` 하나만 맞고, `TRACE/PREDICT/DEBUG/VERIFY` 4개는 agent에 대응 값이 없고 `highlight_code/show_example` 2개는 backend에 대응 값이 없다. `GuidancePlan.hint_level`(`nudge/hint/explain`)까지 합치면 행동 분류 체계가 3개다.

**대외 계약은 이미 backend `AgentAction`으로 정해져 있다** — `plans/FRONTEND_INTEGRATION.md §6`이 `agent_decision.action` 6종을 프론트가 렌더 준비해야 할 계약으로 명문화했고, `agent_plan.md:494`도 "이 스키마는 확정이다"라고 적었다.

**(4) 출력 필드 — 학생에게 보여줄 텍스트를 실을 자리가 없다**
`AgentDecision(state, concept, action, reason, activity)` 5개뿐이다. `GuidancePlan.message_draft` / `ActionPlan.payload["message"]`를 실을 필드가 없다 — **`reason`은 "개입 이유"이지 학생용 메시지가 아니다.** `EntryDecision`, `StudentState.struggle_signals/urgency`, `Evaluation.effectiveness_score/notes` 대부분도 담을 자리가 없다. `AgentDecision.state`는 `ProcessStatus` 6종 문자열이 오는 자리인데 `StudentState`는 자유 텍스트 `state_summary`를 낸다. **어휘 통일 없이 붙이면 화면에 두 종류의 상태 문자열이 섞인다.**

**합의해야 할 설계 (제안)**

*agent 쪽* — `agent/src/tutor_agent/backend_adapter.py`에 `class StrandsTutorAgent: name='llm'; def decide(self, ctx) -> AgentDecision` 어댑터를 만든다.
- `AgentContext` → 내부 컨텍스트 변환(`SessionContext.from_backend(ctx)` 클래스메서드). `SessionContext`에 `features: dict = {}` 같은 **passthrough 필드를 두어 backend가 계산한 19개 feature가 실제로 프롬프트에 실리게 하는 것이 이 프로젝트 논지상 가장 중요하다.**
- entry 단계 스킵([7])
- `GuidancePlan`에 `pedagogy: Literal["WAIT","HINT","TRACE","PREDICT","DEBUG","VERIFY"]`를 추가해 **LLM이 backend `AgentAction`을 직접 생산**하게 한다(문자열 매핑 테이블보다 6지선다가 정확하다). `send_message/highlight_code/show_example`은 HINT의 표현 수단이므로 별도 필드로 강등.
- `StudentState.state`를 `Literal[ProcessStatus 6종]`으로 제약. 기본값은 backend가 준 `ctx.process_status`로 두고 **agent가 뒤집을 때만 근거를 요구**한다.

*backend 쪽* — 필드 3개 추가와 응답 스키마 2필드 확장:
- `AgentContext`에 `student_id: str`(= `session.user_id`), `idle_seconds: float`(**정의 신설**: "마지막 `CODE_SNAPSHOT`/`RUN`/`SUBMIT` 이벤트의 `server_timestamp` 이후 경과 초". `features.py`가 이미 이벤트 타임스탬프를 전부 스캔하므로 계산은 싸다), `last_error: str | None`(마지막 `TEST_RESULT` payload의 message)
- `AgentDecision`/`AgentDecisionRead`에 `message: str | None`(학생에게 보여줄 텍스트)과 `render: Literal[...]`(전달 방식) 추가. **`FRONTEND_INTEGRATION.md` §6을 함께 갱신해야 한다.**
- 어댑터에 매핑 실패 시 `WAIT` 폴백을 두되 `reason`에 원본 값을 남겨 **침묵하지 않게** 한다. 지금 `judge/router.py`의 `except Exception: log.exception(...)` → `decision=None`은 데모 중 가장 찾기 어려운 종류의 침묵이다.

### [9] LLM 호출 예산과 동기 호출 타임아웃

**누가 결정하는가**: **agent 담당(파이프라인 접기) + backend 담당(타임아웃).** [8] 설계에 포함시켜 한 번에 처리.

- `TutorPipeline.run()`은 개입 1회에 entry/state/guidance/action/evaluation **5번의 `structured_output`을 순차 호출**한다. `agent_plan.md:66`은 "실제 구현은 2~3회의 LLM 호출로 단순화한다", `:59`는 "세션당 5~10회 이하"를 개발 조건으로 못박았다. **trigger 두 번이면 세션 예산이 소진된다.**
- 지연이 더 큰 문제다. backend는 `agent.decide()`를 `POST /sessions/{id}/results` 핸들러 안에서 **동기로 부르고 타임아웃이 없다**(`interface.py:43`의 `decide`는 sync def). 5회 순차 LLM 호출이면 학생이 Run을 누른 뒤 **채점 결과 응답 자체가 수십 초 지연된다.** `backend_plan §14`의 "Judge 결과는 Agent 실패와 무관하게 반드시 반환한다"는 예외는 잡지만 지연은 못 막는다.

**할 일**: 어댑터에서 파이프라인을 2회로 접는다 — ① analyze+plan(state+guidance+action을 하나의 `structured_output`으로 병합해 `AgentDecision`을 바로 산출), ② `action != WAIT`일 때만 activity 생성. entry는 [7]대로 제거, evaluation은 [11]대로 이동. backend 쪽에 **agent 호출 타임아웃(예: 8초) + 초과 시 `action=WAIT` 폴백**을 넣는다(`backend_plan §14` 폴백 규정이 이미 그 모양이다).

### [10] Learning Activity 생성 주체가 없다 — 3개 서브시스템이 서로 상대가 만든다고 가정 중

**누가 결정하는가**: **agent 담당에게 소유권 배정 필요.** 데모까지 못 붙으면 backend로 이관(그 경우 팀에 명시 공유).

- backend `AgentDecision.activity: dict|None`이 존재하고 `POST /sessions/{id}/results` 응답으로 프론트에 그대로 전달된다.
- `agent_plan.md §3.3`이 TRACE/PREDICT/DEBUG Activity 스키마(`code`/`instruction`/`fields`/`answer_key`)를 확정했고 `§4 호출 2`가 `generate_activity()`를 **agent 담당으로 배정**했다.
- 그런데 agent 구현에 Activity 생성기가 없다(`agents/`에 entry/state/guidance/action/evaluation 5개뿐). 가장 가까운 `action_agent`의 출력은 `send_message/highlight_code/show_example/no_op` payload뿐이고 `fields`/`answer_key`를 만드는 코드가 없다.
- 동시에 `frontend/src/traceActivity.tsx`는 `TRACE_CODE`를 모듈 상수로 하드코딩하고 관찰 변수도 `['i','total']` 고정, 컴포넌트 prop은 `{onExit}` 하나뿐이라 **서버가 준 activity를 받을 자리가 없다.** 정답 판정도 클라이언트에서 Pyodide로 직접 실행해 만든다.

**결과적으로 같은 산출물을 세 곳이 서로 상대가 만든다고 가정하고 아무도 만들지 않는다. 데모 시나리오 B(반복 실패 → TRACE 제시)가 정확히 이 공백 위에 서 있다.**

**할 일**
- `activity`를 free dict로 두지 말고 discriminated union으로 못박는다. 최소한 데모용 TRACE 하나만이라도:
  `{"kind":"TRACE", "code": str, "variables": [str], "steps": [{"iteration": int, "locals": {...}}]}`
  이 shape는 `traceActivity.tsx`가 이미 내부적으로 만들고 있는 것과 동일하므로, **프론트는 하드코딩을 prop으로 바꾸기만 하면 된다** (`<TraceActivity activity={decision.activity} onExit={...} />`). agent가 붙기 전까지는 현재 하드코딩을 fallback으로 남긴다.
- agent 쪽 `ActionPlan.payload`도 Literal별 모델로 분리(`SendMessagePayload`/`HighlightCodePayload`/…)해 LLM `structured_output`이 키를 보장하게 한다. 지금은 규약이 `action_agent.py`의 SYSTEM_PROMPT 자연어에만 있어 LLM이 다른 키를 내도 아무도 못 잡는다.
- 정한 shape를 `plans/FRONTEND_INTEGRATION.md`에 추가한다. **(참고: 이 문서는 `origin/docs` 브랜치에 실재한다. "존재하지 않는다"는 보고가 있었는데 6개 브랜치 중 5개만 본 결과였다. `plans/FRONTEND_INTEGRATION.md`, `backend_plan.md`, `agent_plan.md`, `feature_plan.md`, `frontend_plan.md` 모두 거기 있다.)**

---

## 3단계 — 나중에 해도 되는 것 (데모 이후 / 여유 있을 때)

### [11] evaluation_agent를 학생 답변 평가로 재정의 + `ACTIVITY_RESPONSE` 경로 담당 배정
**결정자: agent 담당 + backend 담당.** 지금 `evaluation_agent`는 방금 만든 `ActionPlan`이 적절했는지를 **학생이 아직 아무 반응도 하기 전에, 같은 요청 안에서** LLM에게 묻는다. `agent_plan.md §3.4`는 정반대로 학생이 Activity에 낸 답을 채점해 `result/understanding/next_step`을 내라고 하고, **TRACE/PREDICT는 LLM 없이 결정론적으로, DEBUG는 Judge 실행으로** 검증하라고 명시한다. backend에는 `ACTIVITY_OPENED`/`ACTIVITY_RESPONSE` 이벤트 타입과 `payload.result=='CORRECT'`를 진전 anchor로 인정하는 규약이 이미 있지만, 이를 받아 평가할 함수도 `POST /activities/{id}/answers`도 없다. **필요한 평가는 주인이 없고, 필요 없는 자기평가에 개입당 LLM 1회를 쓰고 있다.** `effectiveness_score`가 발표 지표로 필요하면 요청 경로 밖 오프라인 로깅으로 옮긴다.

### [12] `INTERNAL_ERROR` — judge가 인프라 장애를 학생 에러로 보고한다

> **해결됨.** ①②는 구현 완료, ③은 PR #13에서 이미 들어갔다(`problemService.ts`의
> `normalizeJudgeStatus`가 화이트리스트 체크까지 한다). 추가로 monitor에 R1s 게이트를
> 넣었다 — ①②만으로는 `consecutive_error_count`는 막히지만 R7(90초 무진전 + 실행 2회)이
> 채점기 장애 중에도 발화한다. 회귀 테스트는 `backend/tests/test_internal_error.py`(14개),
> `judge/tests/test_internal_error.py`(10개).
>
> 발견한 부수 사실: 로컬 `judge-sandbox` 이미지가 capture 하네스 2개가 추가되기 전
> 버전이면 컨테이너가 "No such file"을 뱉는데, **그게 정확히 이 버그로 `RUNTIME_ERROR`로
> 보고되고 있었다.** 이미지를 다시 빌드하면 해결된다(`docker build -t judge-sandbox .`).
> 이제 같은 상황이 `INTERNAL_ERROR`로 나와 원인을 바로 알 수 있다.

아래는 최초 감사 시점의 원문이다.
**담당: judge(BE1) 4줄 + backend 1곳 + frontend 2곳.** `judge_service.py`가 Docker 데몬 연결 실패(`:140`), 컨테이너 실행 실패(`:177`), 무출력(`:199`), 로그 JSON 파싱 실패(`:204`)를 **전부 `RUNTIME_ERROR`로 반환한다.** backend `ERROR_STATUSES`가 이를 학생 에러로 분류해 `consecutive_error_count`를 올리고, 임계값 3을 넘으면 `REPEATED_FAILURE` 트리거가 발화한다. → **도커가 죽어 있으면 학생이 3번 실행하는 것만으로 '반복 실패' 판정이 나고 agent가 개입한다.** `INTERNAL_ERROR`가 enum에 존재하는 이유가 정확히 이 케이스인데 judge가 한 번도 쓰지 않는다.
할 일: ① judge는 인프라 실패 4곳을 `INTERNAL_ERROR`로(학생 코드가 던진 예외만 `RUNTIME_ERROR`로 남긴다), ② backend는 `INTERNAL_ERROR`를 `ERROR_STATUSES`에서 빼고 `SYSTEM_STATUSES`로 분리해 feature 집계에서 제외, ③ 프론트는 `JudgeStatus` 유니온에 `'INTERNAL_ERROR'` 추가 + `JUDGE_LABELS`에 `'채점 서버에 문제가 생겼어요 (코드 문제가 아니에요)'` 추가. `problemService.ts:103`의 `payload as JudgeResult` 무검증 캐스트를 화이트리스트 체크로 바꾸면 다음 enum 추가 때 또 안 터진다.
**(`FRONTEND_INTEGRATION.md` §5는 이미 `INTERNAL_ERROR`를 프론트가 보내야 할 정식 status 6종에 포함시켜뒀다. 오늘은 `JUDGE_BACKEND=none`이라 이 경로가 실제로 열려 있지 않다.)**

### [13] 에러 봉투 모양 통일
**담당: frontend.** judge는 `{"detail": "문자열"}`, backend는 `{"detail": {"code","message","context"}}`다. 프론트 `judgeCode()`는 `typeof payload.detail === 'string'`일 때만 서버 메시지를 쓰고 아니면 `'Judge API returned 404'`로 대체한다. **backend로 전환하는 순간 모든 서버 에러가 상태코드만 남은 문자열로 퇴화해 디버깅이 어려워진다.** 에러 추출을 한 함수로 모아 세 형태(문자열 / `detail.message`+`detail.code` / FastAPI 422 배열의 첫 `msg`)를 모두 처리하게 한다. backend 봉투가 상위 계약이다.

### [14] 채점 주체 확정과 데드코드 정리
**담당: frontend + backend 합의.** backend는 "오늘은 브라우저 Pyodide가 채점하고 `POST /results`로 보낸다"를 설계 전제로 삼았고 그 흔적이 `EventSource.CLIENT_JUDGE`, `JudgeResultIn` docstring, `UnavailableJudge` 에러 메시지에 박혀 있다. **그런데 프론트는 Pyodide를 채점에 쓰지 않는다.** `preparePython()`으로 런타임 배지만 띄우고 채점은 전부 서버에 위임하며, `runPython()`은 **호출처 0건의 죽은 코드**다. Pyodide 실사용처는 `traceActivity`의 `runTrace` 하나뿐.
- 서버 채점으로 단일화한다면(권장, [5]와 함께): `pythonRunner.runPython`과 `problem.ts`의 `STARTER_CODE`/`TESTS`/`TestCase`를 삭제. **TestCase 타입이 4종에서 3종으로 준다.** backend의 `CLIENT_JUDGE` 전제 문서도 갱신.
- Pyodide 폴백을 살리려면 **"부활"이 아니라 "재작성"이다.** `runPython`의 하네스는 `sum_even(__case["input"])`을 하드코딩하고 문제의 `function_name`을 전혀 참조하지 않으며 `stdout_match`도 지원하지 않는다. `runPython(code, tests, functionName)`으로 일반화하고 `ExecutionResult`(`error.type: 'syntax'|'runtime'` 소문자, `passed`/`total` 없음) → `JudgeResultIn` 매퍼를 새로 써야 한다.
- 곁다리: `sum_even`은 어느 카탈로그에도 없는 데모 잔재인데 `frontend/src/problem.ts`(**`origin/frontend`에도 main과 바이트 동일하게 남아 있다 — 머지해도 사라지지 않는다**)와 `agent/examples/run_session_demo.py:24` 양쪽에 박혀 있다. agent 데모의 `problem_id`도 `func_sum_list`로 바꿔 카탈로그와 맞춘다.

### [15] hidden 테스트 노출 — 정책 결정
**결정자: 팀 전체(정책).** `judge/problems` 26개 파일에 hidden 테스트 입력·정답 **178개**, `backend/app/problems/data` 3개 파일에 **7개**가 원문 그대로 공개 GitHub 레포에 올라가 있다. 추가로 `frontend/src/problem.ts`가 `hidden: true` 케이스 2개를 소스에 하드코딩해 브라우저 번들에 실린다(다만 그건 `sum_even` 데모 문제 것이고 `sum_even`은 어느 카탈로그에도 없다 — 실질 피해는 거의 없다. 그리고 **머지로는 제거되지 않는다**).
아이러니는 backend가 유출 방지에 공을 들였다는 점이다(`ProblemDetail`에 hidden을 담을 그릇을 두지 않는 구조적 가드, allowlist 테스트, judge 하네스가 자식 프로세스에 expected를 안 넘기는 설계). 그 방어는 API 응답 경로의 위협 모델을 다루고, 레포 공개는 별개 축이다.
**캠프 데모 한정이면 README에 "의도된 것이고 실제 서비스가 아님"을 명시하는 것으로 충분할 수 있다.** 그게 아니라면 hidden을 private 경로(`judge/problems-private/` + `.gitignore`)로 분리하고 공개 파일엔 `hidden_test_case_count`/`category`만 남긴다. **이건 팀이 명시적으로 "괜찮다"고 결정하고 넘어가야지, 아무도 안 정한 채로 두면 안 된다.**

### [16] 스키마 문서와 생성 스크립트
**담당: judge(BE1) 주도 + backend 리뷰.**
- `judge/README.md:22`가 "JSON 스키마와 API 응답 스펙은 `CLAUDE.md` 참고"라고 안내하는데 **`.gitignore` 1행이 `CLAUDE.md`를 제외해 어느 브랜치에도 트래킹되어 있지 않다. 깨진 링크다.** 4개 서브시스템이 공유해야 할 문제 데이터 스키마의 명세가 각자 로컬에만 있고, 팀원은 JSON 파일을 역공학해서 필수 필드를 추론해야 한다. **[2], [3]의 어긋남이 전부 "스키마 문서가 없어서" 생긴 종류다.** → `docs/problem-schema.md`(또는 `judge/SCHEMA.md`)를 트래킹 파일로 만들어 필수/선택 필드, `check_type`별 테스트케이스 키, `concept` 어휘, `difficulty` 허용값을 한 페이지로 고정. 가능하면 JSON Schema 파일 하나를 두고 양쪽 테스트에서 26개를 검증하면 drift가 CI에서 잡힌다.
- `judge/scripts/build_index.py`(가칭)를 추가해 `problems/*.json`에서 index/detail을 생성하고, CI에서 "재생성 결과 == 커밋된 파일"을 검사. 두 파일 상단에 생성물임을 주석으로 명시.
- 프론트의 크로스 디렉터리 import(`'../../judge/*.json'`)는 생성물을 `frontend/src/data/`로 복사하는 npm 스크립트로 대체하면 Vite 루트 밖 의존이 사라진다([0]의 `fs.allow` 우회도 불필요해진다).
- `concept` 통제 어휘를 한 곳에 문서화(`docs/concepts.md` 또는 `Concept` enum). 지금 `condition` vs `conditional` 같은 어휘 분기가 있고 taxonomy를 정의한 문서나 enum이 어디에도 없다.

---

## 결정 요약표

| # | 결정 사항 | 결정자 | 시점 |
|---|---|---|---|
| 0 | 머지 순서 + App.tsx 단독 담당자 지정 | 전원 | **오늘** |
| 1 | 문제 데이터 정본 = `judge/problems` 26개 | judge(BE1) + backend | **오늘** |
| 3 | 응답 키 `concept` vs `concepts` | backend + frontend + 문서 소유자 | **오늘** |
| 4 | 8000 포트 = backend 단독 / `judge/main.py` 은퇴 | judge(BE1) + backend | **오늘** |
| 5 | 프론트 진입점 = 호환 어댑터(A) vs 세션 계약(B) | frontend + backend | **오늘** |
| 6 | agent 연결 = in-process vs HTTP | agent + backend | **오늘** |
| 7 | 개입 판단 소유권 = monitor (계획서에 명문화됨) | agent | **오늘** |
| 8 | 어댑터 계약 3층(입력/action enum/출력 필드) | agent + backend 공동 | 결정 직후 |
| 10 | Activity 생성 소유권 = agent (미이행 시 backend 이관) | agent 담당 배정 | 결정 직후 |
| 11 | `ACTIVITY_RESPONSE` 평가 경로 담당 | agent + backend | 데모 이후 |
| 15 | hidden 테스트 공개 노출 허용 여부 | 팀 전체(정책) | 데모 전 한 번은 |

**결정 없이 지금 바로 고칠 수 있는 것 (담당자 재량, 5~10분)**
- `get_agent()`의 `NotImplementedError` → `WaitAgent` 폴백 + 로그 (backend) — FastAPI `Depends`라 라우터의 `except`가 못 잡는다
- `vite.config.ts`에 `server: { fs: { allow: ['..'] } }` (frontend)
- `context.py:63`의 `description_summary` 첫 줄 추출 로직 (backend)
- backend/README.md 병합 체크리스트 3번에 "[2] 완료 전 실행 금지" 경고 (backend)