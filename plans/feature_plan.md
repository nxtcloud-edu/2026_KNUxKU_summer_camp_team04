# CodeTrace MVP 기능 목록

체크박스는 **현재 실제 구현 상태**다. 백엔드 테스트 217개 통과.

| 레이어 | 상태 |
|---|---|
| Backend — Trace / Feature / Monitor / Timeline | 완료 |
| Backend — 인증 · 도토리 · 진행 상태 | 완료 |
| Backend — 교육기관 (기관·강의·대시보드) | 완료 (UI 없음) |
| Backend — Judge | 어댑터 완료. `JUDGE_BACKEND=docker` 로 켠다 |
| Backend — Agent LLM | seam (항상 `WAIT`, 어댑터 없음) |
| Backend — Activity, Learner State, Analytics | 미착수 |
| Frontend — 문제 화면 / Monaco / Pyodide 실행 | 완료 |
| Frontend — Coding Trace 수집 | 완료 |
| Frontend — 인증 연결 | **미착수** (화면만 있음) |
| Agent — 에이전트 4종 + 문제 생성기 | 코드 완료, backend 미연결 |

---

## 0. 핵심 사용자 흐름

MVP에서 반드시 끝까지 동작해야 하는 흐름은 아래 하나입니다.

```text
문제 선택
→ 코드 작성
→ Run / Submit
→ 테스트 결과 확인
→ Coding Trace 기록
→ Process 상태 분석
→ Agent 개입 여부 판단
→ TRACE / PREDICT / HINT / DEBUG / VERIFY 중 선택
→ 학생 학습 활동 수행
→ 다시 코드 수정
→ 재실행
→ 상태 재평가
```

---

# 1. 문제풀이 플랫폼

### 문제 기능

* [ ] 문제 목록
* [ ] 문제 상세 페이지
* [ ] 문제 제목
* [ ] 문제 설명
* [ ] 입력/출력 또는 함수 specification
* [ ] 예제 입력/출력
* [ ] 문제별 학습 Concept 태그

  * `variable`
  * `condition`
  * `loop`
  * `function`
* [ ] 문제 난이도
* [ ] 문제별 Public Test Case
* [ ] 문제별 Hidden Test Case

### MVP 권장 문제

* [ ] 리스트 합 구하기
* [ ] 최댓값 찾기
* [ ] 양수 개수 세기

시간이 남으면:

* [ ] 문자열 뒤집기
* [ ] Two Sum

---

# 2. Web Coding Environment

### 코드 에디터

* [ ] Monaco Editor
* [ ] Python syntax highlighting
* [ ] 기본 코드 template
* [ ] 코드 수정
* [ ] Undo / Redo
* [ ] Run 버튼
* [ ] Submit 버튼
* [ ] Reset 버튼

### 실행 결과

* [ ] stdout 표시
* [ ] Runtime Error 표시
* [ ] Syntax Error 표시
* [ ] 테스트 성공/실패 표시

예:

```text
Tests

✓ 1
✓ 2
✕ 3

3 / 5 Passed
```

---

# 3. Python Judge

### 실행 기능

* [ ] 학생 Python 코드 실행
* [ ] 문제별 test case 실행
* [ ] Timeout
* [ ] Exception capture
* [ ] 결과 반환

### Judge 결과

```json
{
  "passed": 3,
  "total": 5,
  "status": "WRONG_ANSWER"
}
```

가능한 status:

* [x] `ACCEPTED` — 점수로 셈
* [x] `WRONG_ANSWER` — 점수로 셈
* [x] `RUNTIME_ERROR` — 관측 없음
* [x] `SYNTAX_ERROR` — 관측 없음
* [x] `TIME_LIMIT` — 관측 없음
* [x] `INTERNAL_ERROR` — 관측 없음

채점은 서버가 한다. `POST /sessions/{id}/run|submit` 하나가 스냅샷·채점·기록·판정을
전부 처리한다. `JUDGE_BACKEND=docker` 를 켜야 동작한다 (기본값 `none` 이면 503).

### Agent 내부용 정보

학생에게는:

```text
3 / 5 Passed
```

정도만 보여주고,

Agent에는 선택적으로:

```json
{
  "failed_categories": [
    "negative_numbers",
    "boundary_case"
  ]
}
```

를 전달할 수 있다.

---

# 4. Coding Trace 수집

CodeTrace의 핵심 기능.

### 수집 Event

서버가 생성:

* [x] `SESSION_START`
* [x] `TEST_RESULT`
* [x] `AGENT_TRIGGER`
* [ ] `AGENT_INTERVENTION` — Agent가 붙으면

클라이언트가 전송:

* [x] `CODE_SNAPSHOT`
* [x] `RUN`
* [x] `SUBMIT`
* [x] `UNDO`
* [x] `RESET`
* [x] `HINT_REQUEST`
* [x] `ACTIVITY_OPENED`
* [x] `ACTIVITY_RESPONSE`
* [x] `SESSION_END`

`RUNTIME_ERROR` / `SYNTAX_ERROR`는 별도 이벤트를 만들지 않는다. 상태는
`TEST_RESULT.payload.status`가 운반하고, 타임라인이 그걸 `kind: "ERROR"`로 표시한다.
한 번의 실행이 두 행을 만들면 오류 횟수를 셀 지점이 둘이 된다.

"누가 보냈나"는 타입 이름이 아니라 `source` 컬럼(`CLIENT` / `CLIENT_JUDGE` / `SERVER`)에 기록된다.

---

# 5. Code Snapshot / Diff

매 keystroke마다 LLM에 코드를 전달하지 않는다.

### 저장

* [x] 특정 시점 코드 snapshot
* [x] 이전 버전과 code diff
* [x] 수정된 line 또는 영역 — 태그 7종 (`loop` `condition` `accumulator` `initialization` `return` `function_def` `other`)
* [x] 코드 변화량 — `change_size`, `change_ratio`

예:

```text
v5 → v6

- for i in range(len(arr)):
+ for i in range(len(arr) - 1):

changed_lines: [4]  primary_region: "loop"  summary: "반복문 영역 수정 (1줄)"
```

추가로:

* [x] 짧은 시간 내 큰 코드 변화 탐지 — 비율 ≥0.5 **그리고** ≥5줄 **그리고** ≤60초
* [x] 동일 영역 반복 수정 탐지
* [x] 바이트 동일한 스냅샷은 새 버전을 만들지 않음 (undo/redo 흡수)

영역 태깅은 `ast`가 아니라 regex다. 편집 중인 학생 코드는 상당 비율이 문법적으로
무효인데, `ast.parse`는 그 경우 파일 전체를 태그 0개로 만든다.

---

# 6. Process Feature Extraction

Raw Event를 Agent가 이해하기 쉬운 Feature로 변환한다.

### 기본 Feature — 20종 전부 구현

* [x] 문제 풀이 시간 `elapsed_seconds`
* [x] Run / Submit 횟수 `run_count` `submit_count` `attempt_count`
* [x] 최근 test score `recent_scores`
* [x] test score 변화 `progress_delta` `improved_recently`
* [x] 동일 결과 반복 횟수 `same_result_count`
* [x] 오류 반복 횟수 `consecutive_error_count` `recent_error_types`
* [x] Undo / Hint 횟수 `undo_count` `hint_count`
* [x] 마지막 진전 이후 경과 시간 `seconds_without_progress`
* [x] 반복 수정 영역 `same_region_edit_count` `repeated_edit_region`
* [x] 큰 코드 변화 여부 `large_change_detected`
* [x] 편집 수 `edits_since_progress` `edits_in_result_streak` `snapshot_count`
* [x] 마지막 결과 `last_result`

예:

```json
{
  "run_count": 5,
  "recent_scores": [2, 3, 3, 3],
  "same_result_count": 3,
  "progress_delta": 0,
  "repeated_edit_region": "loop",
  "seconds_without_progress": 94
}
```

### 정의상 결정 세 가지

**에러 결과는 0점이 아니라 "관측 없음"이다.** `SYNTAX_ERROR` 등은 점수 계산에서 제외한다.
0으로 세면 `3/5 → 오타 → 3/5`가 `[3, 0, 3]`이 되어 "+3 진전"으로 읽히고, 막힌 학생이
방치된다. 덕분에 "syntax error 1회는 개입하지 않는다"가 특례 없이 자동으로 나온다.

**진전은 개인 최고 기록 갱신이다.** `4/5 → 3/5 → 4/5`의 두 번째 4/5는 회복이지 진전이 아니다.

**결과 동일성은 `(status, passed, total)` 3요소다.** `passed`만 보면 run과 submit이 섞인다.

---

# 7. Lightweight Process Monitor

LLM을 계속 호출하지 않고 rule 기반으로 먼저 판단한다.

### 상태 — 6종 전부 구현

* [x] `PROGRESSING`
* [x] `PRODUCTIVE_STRUGGLE`
* [x] `POSSIBLE_STUCK`
* [x] `STUCK`
* [x] `UNDERSTANDING_UNCERTAIN`
* [x] `HELP_REQUESTED`

### Trigger Rule — first match wins. 순서가 설계다

| # | 조건 | status | 개입 |
|---|---|---|---|
| R0 | 도움 요청 (**cooldown 무시**) | `HELP_REQUESTED` | 발화 |
| R1 | cooldown 게이트 | 분류는 유지 | 죽임 |
| R2 | 통과 + 대규모 변경 | `UNDERSTANDING_UNCERTAIN` | 발화 |
| R3 | 점수 개선 중 | `PROGRESSING` | 없음 |
| R4 | 통과 | `PROGRESSING` | 없음 |
| R5 | 동일 결과 ≥3 + 같은 영역 ≥2 | `STUCK` | 발화 |
| R5b | 동일 결과 ≥3 + 편집 0 | `STUCK` | 발화 |
| R6 | 연속 에러 ≥3 | `STUCK` | 발화 |
| R7 | 90초 무진전 + 실행 ≥2 | `POSSIBLE_STUCK` | 발화 |
| R8 | 실행 ≥2 | `PRODUCTIVE_STRUGGLE` | 없음 |
| R9 | 그 외 | `PROGRESSING` | 없음 |

**R2가 R3보다 위에 있어야 한다.** `3/5 → 5/5`는 진전(+2)이라 R3가 먼저 잡아버리는데,
이 시나리오의 요점이 바로 "겉보기 진전이 의심스러운 경우"다. 진전 가드가 보호할 대상은
기어오르는 학생이지, 재작성을 붙여넣고 점프한 학생이 아니다.

반면:

```text
2/5 → 3/5 → 4/5
→ R3에서 걸려 개입하지 않는다
```

### status와 trigger는 별개다

cooldown 중이면 `status: "STUCK"` + `trigger: null`이 나온다.
막힘을 *알면서도* 끼어들지 않기로 *선택*한 상태를 그대로 표현할 수 있다.

* [x] 근거 문자열(`evidence[]`)을 서버가 한국어로 생성
* [x] 판정 함수는 읽기 전용 — `/process-state` 폴링이 상태를 바꾸지 않는다

---

# 8. Agent Context Builder

LLM에 전체 history를 던지지 않고 필요한 정보만 압축한다.

### Agent 입력

* [ ] 문제 설명
* [ ] 학습 Concept
* [ ] 현재 코드
* [ ] 현재 테스트 결과
* [ ] 최근 code diff
* [ ] 최근 의미 있는 Event
* [ ] Process Feature
* [ ] 이전 Agent intervention
* [ ] 학생의 learning activity 응답

예:

```json
{
  "concept": "loop",
  "current_code": "...",
  "test_score": "3/5",

  "recent_events": [
    "RUN 3/5",
    "loop boundary edited",
    "RUN 3/5",
    "loop boundary edited",
    "RUN 3/5"
  ],

  "process_state": {
    "same_result_count": 3,
    "progress": false
  }
}
```

---

# 9. Process Analysis Agent

Agent가 현재 학생의 문제 해결 상태를 판단한다.

### 출력

* [ ] 학생 상태
* [ ] 문제가 있을 가능성이 높은 Concept
* [ ] 판단 근거
* [ ] intervention 필요 여부

예:

```json
{
  "state": "STUCK",
  "concept": "loop_boundary",
  "reason": "학생이 반복문의 범위를 반복 수정하고 있으나 테스트 결과가 개선되지 않음",
  "need_intervention": true
}
```

---

# 10. Pedagogical Action Selector

Agent의 가장 중요한 기능.

다음 행동 중 하나를 선택한다.

* [ ] `WAIT`
* [ ] `HINT`
* [ ] `TRACE`
* [ ] `PREDICT`
* [ ] `DEBUG`
* [ ] `VERIFY`

---

# 11. WAIT

학생이 스스로 해결하고 있으면 방해하지 않는다.

조건 예:

```text
2/5
→ 3/5
→ 4/5
```

Agent:

```text
Action: WAIT
Reason: Student is making progress.
```

이 기능은 반드시 있어야 한다.

**“언제 도와주지 않을 것인가”도 Agent가 결정한다는 것이 핵심이다.**

---

# 12. HINT

최소한의 힌트를 제공한다.

예:

> 반복문이 리스트의 마지막 원소까지 실제로 방문하는지 확인해보세요.

제한:

* [ ] 정답 코드 직접 제공 금지
* [ ] 문제 해결 전체 절차 제공 금지
* [ ] 한 번에 하나의 핵심 힌트만 제공

---

# 13. TRACE Activity

가장 중요한 학습 기능 중 하나.

학생이 **코드의 실행 과정을 직접 따라가게 한다.**

예:

```python
total = 0

for i in range(1, 4):
    total += i
```

UI:

```text
Iteration │ i │ total
──────────┼───┼──────
1         │ ? │ ?
2         │ ? │ ?
3         │ ? │ ?
```

필요 기능:

* [ ] Trace 문제 생성
* [ ] 빈칸 입력
* [ ] 정답 확인
* [ ] Agent 평가
* [ ] 원래 문제로 복귀

---

# 14. PREDICT Activity

학생이 코드 실행 결과를 먼저 예측한다.

예:

```python
for i in range(2, 5):
    print(i)
```

질문:

> 실행 전에 출력 결과를 적어보세요.

기능:

* [ ] Agent가 code snippet 생성
* [ ] 학생 prediction 입력
* [ ] 실제 실행 결과와 비교
* [ ] Agent에게 결과 전달

---

# 15. DEBUG Activity

학생이 오류가 있는 코드를 분석한다.

예:

```python
def find_max(nums):
    max_value = 0

    for x in nums:
        if x > max_value:
            max_value = x

    return max_value
```

Agent:

> 이 코드가 실패하는 입력을 하나 찾아보세요.

기능:

* [ ] 오류 코드 제공
* [ ] 반례 입력
* [ ] 코드 수정
* [ ] 테스트 실행

---

# 16. VERIFY Activity

학생이 코드를 통과시켰더라도 이해가 불확실할 때 사용한다.

예:

> 이 반복문이 정확히 `len(arr)`번 실행되는 이유를 설명해주세요.

또는:

> 이 조건문의 순서를 변경하면 어떤 일이 발생하나요?

기능:

* [ ] 자신의 코드 기반 질문 생성
* [ ] 자연어 답변 입력
* [ ] Agent 평가
* [ ] `UNDERSTANDING_CONFIRMED`
* [ ] `NEEDS_REVIEW`

---

# 17. 학습 Activity 결과 평가

Agent intervention 이후 학생 반응을 다시 평가한다.

예:

```text
STUCK
→ TRACE
→ 학생 정답
→ 원래 문제 복귀
→ 코드 수정
→ 5/5
```

상태:

```text
Concept recovery detected
```

필요:

* [ ] Activity 성공 여부
* [ ] 이후 코드 개선 여부
* [ ] 동일 오류 재발 여부
* [ ] 다음 Agent action 결정

---

# 18. Agent Replanning

한 번 개입하고 끝나는 것이 아니라 결과에 따라 다시 판단한다.

```text
STUCK
 ↓
TRACE
 ↓
학생 실패
 ↓
PREDICT
 ↓
학생 성공
 ↓
원 문제
 ↓
PASS
```

즉:

```text
Observe
→ Analyze
→ Act
→ Observe
→ Replan
```

Closed-loop를 구현한다.

---

# 19. Agent Structured Output

Agent 출력은 무조건 JSON Schema로 고정한다.

예:

```json
{
  "state": "STUCK",
  "concept": "loop_boundary",
  "action": "TRACE",
  "reason": "반복문의 범위를 반복 수정하고 있지만 테스트 결과가 개선되지 않음",

  "activity": {
    "type": "TRACE_TABLE",
    "code": "for i in range(4): print(i)",
    "question": "i의 값을 순서대로 적어보세요."
  }
}
```

이게 FE/BE 협업에 매우 중요하다.

---

# 20. Agent UI

학생 화면에서 Agent action을 표시한다.

### 기본 영역

```text
AI Learning Agent
────────────────────────

현재 스스로 해결 과정에서
진전하고 있습니다.

지금은 힌트를 제공하지 않겠습니다.
```

또는:

```text
반복문의 실행 흐름을 먼저
확인해보는 것이 좋겠습니다.

[Trace 시작]
```

---

# 21. Agent 상태 시각화

대회 데모에서는 반드시 넣는 게 좋다.

학생에게 꼭 모든 정보를 보여줄 필요는 없지만, 시연 화면에서는:

```text
Learning Process State
─────────────────────────

State
STUCK

Evidence
• Same result ×3
• Loop area edited ×4
• No improvement for 96 sec

Concept
Loop Boundary

Agent Decision
TRACE
```

를 보여준다.

**심사위원에게 Agent가 실제 판단하고 있다는 것을 보여주는 기능이다.**

---

# 22. Coding Timeline

학생의 문제 해결 과정을 시간순으로 표시한다.

```text
START
 │
 ├─ CODE
 ├─ RUN 2/5
 ├─ EDIT
 ├─ RUN 3/5
 ├─ EDIT
 ├─ RUN 3/5
 ├─ EDIT
 ├─ RUN 3/5
 │
 ├── AGENT: TRACE
 │
 ├── TRACE SUCCESS
 │
 ├─ EDIT
 ├─ RUN 5/5
 │
 └─ ACCEPTED
```

---

# 23. Process Replay

우선순위는 낮지만 데모 효과는 큼.

* [ ] 특정 Event 선택
* [ ] 해당 시점 code snapshot 표시
* [ ] 이전/다음 Event 이동
* [ ] Test 결과 표시
* [ ] Agent intervention 위치 표시

실제 녹화 영상이 아니라 snapshot replay면 충분하다.

---

# 24. 간단한 Learner State

MVP에서는 복잡한 Knowledge Tracing 필요 없음.

학생 세션 단위로:

```json
{
  "loop": {
    "trace_success": 2,
    "debug_success": 1,
    "repeated_failure": 3
  }
}
```

정도로 저장.

UI에는 굳이 `% mastery`를 보여주지 않아도 됨.

대신:

```text
Loop

✓ Basic iteration
✓ State tracing
△ Boundary handling
```

처럼 observable evidence 중심으로 표시.

---

# 25. AI 시대 확장 기능

MVP에서 전부 만들 필요 없음.

향후 기능:

* [ ] AI-generated code review 문제
* [ ] AI 코드에서 오류 찾기
* [ ] AI에게 작성한 Prompt 분석
* [ ] Student ↔ Coding Agent interaction recording
* [ ] AI 결과 검증 능력 평가
* [ ] 단계별 AI Code Generation 허용
* [ ] Specification exercise
* [ ] Test generation exercise

학습 경로:

```text
TRACE
 ↓
PREDICT
 ↓
CODE
 ↓
DEBUG
 ↓
CODE REVIEW
 ↓
AI CODE VERIFICATION
```

---

# 26. 교수자 기능 — MVP에서는 최소

시간 남으면:

* [ ] 학생 목록
* [ ] 문제별 상태
* [ ] Run 횟수
* [ ] Agent intervention 횟수
* [ ] 해결 시간
* [ ] Timeline 열람

예:

```text
Student    Result    Runs    AI Help
────────────────────────────────────
A          AC         5        0
B          AC        11        2
C          WA        14        3
```

완성형 Dashboard는 필요 없음.

---

# 27. 로그 / 평가 기능

대회 때문에 필수에 가까움.

### Agent Invocation Logging

* [ ] 호출 timestamp
* [ ] Trigger 이유
* [ ] token usage
* [ ] response latency
* [ ] 선택한 action
* [ ] intervention 결과

이를 이용해서:

```text
Editor Events       487
Agent Invocations     6
Invocation Rate     1.2%
```

같은 결과를 제시할 수 있다.

---

# 28. Agent 성능 평가 기능

미리 20개 정도의 Coding Trace scenario를 준비한다.

각 scenario에 정답 label:

```json
{
  "state": "STUCK",
  "recommended_action": "TRACE"
}
```

평가:

* [ ] Process State Accuracy
* [ ] Action Selection Accuracy
* [ ] LLM Invocation Count
* [ ] Average Latency

가능하면 ablation:

```text
Current Code only
vs
Current Code + Coding Trace
```

를 비교.

---

# 29. 반드시 필요한 기능 — 최종 압축

2일 MVP에서 **이것만 되면 된다.**

### Coding

* [x] 문제 화면
* [x] Monaco
* [x] Python 실행 (브라우저 Pyodide)
* [x] Public/Hidden Test — 문제 데이터 완비, hidden은 비노출
* [x] Run / Submit 버튼

### Trace — 백엔드 완료, 프론트 연동 대기

* [x] Code snapshot
* [x] Code diff
* [x] Run history
* [x] Test progress
* [x] Event Logger (서버측 수집 API)
* [ ] 프론트 Event Collector ← **다음 작업**

### Monitor — 완료

* [x] 반복 실패 탐지
* [x] Progress 탐지
* [x] No-progress 탐지
* [x] Agent Trigger

### Agent

* [x] Context Builder (LLM 없이 payload 생성)
* [ ] Process State 분석 (LLM)
* [ ] Concept 추정
* [ ] Action 선택
* [x] Structured JSON output — 응답 스키마 확정, stub이 `WAIT` 반환

### Learning

* [x] WAIT — stub의 기본 동작
* [ ] HINT
* [ ] TRACE
* [ ] PREDICT

### Closed Loop

* [ ] Activity 결과 수집 — 이벤트 수집은 가능, Activity 저장소 없음
* [ ] Agent 재평가
* [ ] 원래 문제 복귀

### Demo

* [x] Coding Timeline (API + 한국어 label)
* [x] Agent State Panel용 데이터 (status / reason / evidence)
* [ ] 두 화면의 프론트 렌더링

---

# 30. 시간이 남으면 추가하는 기능 순서

**1순위**

* [ ] DEBUG
* [ ] VERIFY

**2순위**

* [ ] Process Replay
* [ ] Learner State

**3순위**

* [ ] 간단한 교수 화면
* [ ] Agent evaluation dashboard

**4순위**

* [ ] AI-generated code review

---

# 최종 기능 구조

```text
                 Problem Platform
                        │
                        ▼
                    Web IDE
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
          Code Judge          Event Logger
              │                   │
              └─────────┬─────────┘
                        ▼
                 Process Monitor
                        │
                 Significant Event
                        ▼
                  Learning Agent
                        │
             ┌──────────┼───────────┐
             ▼          ▼           ▼
            WAIT      HINT      TRACE/PREDICT
                                    │
                                    ▼
                              Student Activity
                                    │
                                    ▼
                                Re-evaluate
                                    │
                                    ↺
```

이 프로젝트에서 **절대 놓치면 안 되는 세 기능은 `Coding Trace`, `Agent Action Selection`, `Learning Activity`**다.

나머지는 이 세 개가 제대로 연결된 뒤 추가하는 게 맞다.
