# CodeTrace Agent 개발 계획서

## 1. 목적

CodeTrace의 Agent는 학생에게 정답을 생성하는 챗봇이 아니라, **학생의 Coding Trace를 분석하여 현재 학습 상태를 판단하고 다음 학습 활동을 자율적으로 선택하는 학습 의사결정 시스템**이다.

핵심 루프는 다음과 같다.

```text
Observe Coding Trace
→ Analyze Process State
→ Select Pedagogical Action
→ Generate Learning Activity
→ Evaluate Student Response
→ Update State
→ Replan
```

프로젝트의 차별점은 단순한 힌트 생성이 아니라 다음 두 가지에 있다.

1. 최종 코드뿐 아니라 `수정 → 실행 → 실패 → 재수정`의 과정을 Agent의 관찰값으로 사용한다.
2. `WAIT`, `HINT`, `TRACE`, `PREDICT`, `DEBUG`, `VERIFY` 중 **어떤 방식으로 학습시킬지**를 Agent가 결정한다.

---

## 1.1 현재 상태 — 지금 당장 쓸 수 있는 것

| 항목 | 상태 |
|---|---|
| Process Monitor (규칙 기반 trigger) | **완료** — 4종 trigger 발화 |
| Agent Context Builder | **완료** — `build_context()`가 실제 trace로 payload를 채운다 |
| `POST /agent/decide` 엔드포인트 | **완료** — 스키마 확정, 지금은 항상 `WAIT` |
| `AgentProtocol` 인터페이스 | **완료** — 이걸 구현하면 끝 |
| 에이전트 4종 (state/guidance/action/evaluation) | 코드 완료 |
| 문제 생성기 (오답 기반 복습) | 코드 완료 (`problem_generator_agent.py`) |
| LLM provider 스위치 | 완료 (Anthropic/OpenAI/LiteLLM/Bedrock) |
| **backend 어댑터** | **없음** — `AGENT_BACKEND=llm` 을 켜도 `WaitAgent` 로 폴백한다 |
| Activity 생성 | 미착수 |
| Activity 저장소 · 답변 평가 API | 미착수 |

**아직 꽂히지 않았다.** `backend/app/agent/__init__.py` 의 `get_agent()` 에 `llm` 분기가
없어서 `AGENT_BACKEND=llm` 을 넣어도 경고만 찍고 `WaitAgent` 를 돌려준다.
연결하려면 `AgentProtocol` 을 구현하는 어댑터와 그 분기가 필요하다.
입력(`AgentContext`)은 이미 실제 데이터로 채워져 오고, 출력 스키마도 고정되어 있다.

Monitor가 `trigger`를 만들 때만 Agent가 호출된다. 호출 시점 판단은 이미 끝나 있으므로
Agent는 **"무엇을 할 것인가"만** 결정하면 된다.

```bash
python -m scripts.seed_demo   # 4개 시나리오 세션을 만들어 context를 눈으로 확인
```

---

## 2. MVP 범위와 개발 원칙

### 개발 조건

- 개발 기간: 2일
- 지원 언어: Python
- 핵심 개념: 반복문, 조건문, 변수 상태 변화
- 핵심 데모 개념: `for`, `range`, accumulator, boundary
- 문제 수: 3개
- LLM 호출 목표: 문제 풀이 세션당 5~10회 이하

### 원칙

- 모든 이벤트에 LLM을 호출하지 않는다.
- Process Monitor는 규칙 기반으로 구현한다.
- Agent 출력은 자유 텍스트가 아니라 JSON Schema로 강제한다.
- 논리적으로는 여러 Agent 역할을 분리하되, 실제 구현은 2~3회의 LLM 호출로 단순화한다.
- Agent가 판단하기 어려운 경우에는 정답을 생성하지 않고 안전한 `WAIT` 또는 짧은 질문으로 폴백한다.

---

## 3. Agent 구성

## 3.1 Process Analyst Agent

### 핵심 질문

> 학생은 지금 어떤 문제 해결 상태에 있으며, 어떤 개념에서 막혀 있는가?

### 입력

- 문제 설명 및 개념 태그
- 현재 코드
- 현재 테스트 결과
- 최근 테스트 점수 변화
- 최근 코드 diff
- 반복 수정 영역
- 오류 종류 및 반복 횟수
- 이전 Agent 개입과 학생 반응
- Process Monitor가 계산한 feature

### 출력

```json
{
  "state": "STUCK",
  "suspected_concept": "loop_boundary",
  "confidence": 0.87,
  "evidence": [
    "최근 세 번의 실행에서 테스트 결과가 3/5로 동일함",
    "range 표현이 포함된 동일 코드 영역을 반복 수정함"
  ],
  "needs_intervention": true
}
```

### 상태 분류

- `PROGRESSING`: 테스트 결과 또는 코드 품질이 지속적으로 개선됨
- `PRODUCTIVE_STRUGGLE`: 실패 중이지만 다양한 전략을 시도하고 진전이 있음
- `STUCK`: 동일한 실패 또는 동일 영역 수정이 반복되며 진전이 없음
- `UNDERSTANDING_UNCERTAIN`: 정답은 통과했지만 이해 근거가 부족함
- `HELP_REQUESTED`: 학생이 직접 도움을 요청함

---

## 3.2 Pedagogical Planner Agent

### 핵심 질문

> 현재 학생에게 어떤 학습 행동을 제공하는 것이 가장 적절한가?

### Action Space

| Action | 사용 조건 | 목적 |
|---|---|---|
| `WAIT` | 스스로 진전 중 | Productive struggle 보호 |
| `HINT` | 작은 방향 교정으로 해결 가능 | 최소한의 scaffold 제공 |
| `TRACE` | 상태 변화·반복 흐름 이해 부족 | 실행 과정 mental model 형성 |
| `PREDICT` | 출력·분기·반복 횟수 이해 확인 필요 | 실행 전 추론 유도 |
| `DEBUG` | 오류 탐색·반례 사고가 필요 | 코드 검증 능력 훈련 |
| `VERIFY` | 정답은 맞지만 이해가 불확실 | 실제 이해 여부 확인 |

### 출력

```json
{
  "action": "TRACE",
  "target_concept": "range_stop_exclusive",
  "reason": "학생이 range의 경계만 반복 수정하고 있어 실행 범위를 직접 추론하는 활동이 필요함",
  "difficulty": "EASY",
  "return_policy": "RETURN_TO_ORIGINAL_AFTER_SUCCESS"
}
```

### Planner 정책

- `PROGRESSING`이면 기본적으로 `WAIT`
- `STUCK + execution-flow issue`이면 `TRACE` 또는 `PREDICT`
- `STUCK + localized mistake`이면 `HINT`
- 정답 통과 후 이해 근거가 부족하면 `VERIFY`
- 동일 Activity를 연속 두 번 실패하면 더 단순한 Activity로 낮춘다.
- 정답 코드 또는 전체 구현을 직접 제공하지 않는다.

---

## 3.3 Learning Activity Agent

### 핵심 질문

> 선택된 학습 행동을 학생이 수행할 수 있는 구체적인 활동으로 어떻게 만들 것인가?

### TRACE 출력 예시

```json
{
  "type": "TRACE",
  "title": "반복문의 실행 흐름 확인",
  "code": "total = 0\nfor i in range(1, 4):\n    total += i",
  "instruction": "각 반복이 끝난 뒤 i와 total의 값을 입력하세요.",
  "fields": [
    {"iteration": 1, "keys": ["i", "total"]},
    {"iteration": 2, "keys": ["i", "total"]},
    {"iteration": 3, "keys": ["i", "total"]}
  ],
  "answer_key": [
    {"i": 1, "total": 1},
    {"i": 2, "total": 3},
    {"i": 3, "total": 6}
  ]
}
```

### PREDICT 출력 예시

```json
{
  "type": "PREDICT",
  "title": "실행 결과 예측",
  "code": "print(list(range(4)))",
  "instruction": "코드를 실행하기 전에 출력 결과를 입력하세요.",
  "answer_key": "[0, 1, 2, 3]"
}
```

### DEBUG 출력 예시

```json
{
  "type": "DEBUG",
  "title": "실패하는 입력 찾기",
  "code": "def find_max(nums):\n    m = 0\n    for x in nums:\n        if x > m:\n            m = x\n    return m",
  "instruction": "이 함수가 잘못된 결과를 반환하는 입력을 하나 제시하세요.",
  "evaluation_type": "EXECUTE_COUNTEREXAMPLE"
}
```

### Activity 생성 제약

- 원래 문제와 같은 개념을 다루되 표면 형태는 단순하게 만든다.
- 코드 길이는 3~8줄을 권장한다.
- 한 Activity는 한 개념만 검증한다.
- 예상 정답은 코드 실행 Tool로 검증한다.
- 프론트엔드가 렌더링할 수 있도록 Activity 유형별 스키마를 고정한다.

---

## 3.4 Learning Evaluator Agent

### 핵심 질문

> 학생이 방금 수행한 학습 활동을 통해 개념 이해가 개선되었는가?

### 평가 방식

- TRACE/PREDICT: 가능한 경우 deterministic rule로 먼저 채점
- DEBUG: 학생이 제시한 반례를 Code Judge로 실행해 검증
- VERIFY: 짧은 rubric과 LLM 평가를 결합
- HINT 후 원래 문제 재실행: 테스트 점수 변화와 동일 오류 재발 여부로 평가

### 출력

```json
{
  "result": "CORRECT",
  "understanding": "IMPROVED",
  "evidence": [
    "range(4)의 출력값을 정확히 예측함",
    "원래 문제에서 boundary 수정 후 5/5 통과함"
  ],
  "next_step": "RETURN_TO_ORIGINAL_TASK",
  "state_update": {
    "concept": "loop_boundary",
    "status": "RECOVERED"
  }
}
```

### Replanning 규칙

```text
TRACE 성공
→ 원래 문제 복귀

TRACE 실패
→ 더 쉬운 PREDICT

HINT 후 점수 개선
→ WAIT

HINT 후 동일 실패 반복
→ TRACE 또는 DEBUG

VERIFY 실패
→ 개념 Activity 제공
```

---

## 4. 실제 구현 단순화

논리적 역할은 네 개지만, 2일 MVP에서는 다음처럼 구현한다.

### 호출 1: Analyze + Plan

```python
analysis_and_plan = analyze_and_plan(context)
```

결과:

```json
{
  "state": "STUCK",
  "concept": "loop_boundary",
  "action": "TRACE",
  "reason": "..."
}
```

### 호출 2: Activity Generate

`WAIT`이 아니면 Activity를 생성한다.

```python
activity = generate_activity(analysis_and_plan, context)
```

### 호출 3: Evaluate

자연어 답변 또는 복합 Activity인 경우에만 호출한다.

```python
evaluation = evaluate_activity(activity, student_answer)
```

TRACE/PREDICT처럼 정답이 명확한 유형은 LLM 호출 없이 서버에서 채점한다.

---

## 5. Agent 상태 머신

```text
OBSERVING
   │
   ├─ Trigger 없음 → OBSERVING
   │
   └─ Trigger 발생
          ↓
      ANALYZING
          ↓
      PLANNING
          │
          ├─ WAIT → OBSERVING
          │
          └─ Activity 선택
                  ↓
              ACTIVITY
                  ↓
              EVALUATING
                  │
                  ├─ 성공 → RETURN_TO_TASK
                  ├─ 실패 → REPLAN
                  └─ 불확실 → SAFE_FALLBACK
```

---

## 6. Process Monitor와 Agent의 경계

Process Monitor는 Agent가 아니다.

### Monitor가 하는 일 — 구현 완료

- 동일 테스트 결과 반복 횟수 계산
- 최근 테스트 점수 추세 계산
- 동일 코드 영역 반복 수정 탐지 (태그 7종)
- 일정 시간 무진전 탐지
- 대규모 코드 변화 탐지
- Agent 호출 trigger 생성
- **개입하지 않기로 하는 판단** — cooldown, 진전 가드

Monitor가 만드는 `trigger` 4종:

| trigger | 발화 조건 |
|---|---|
| `HELP_REQUESTED` | 학생이 직접 요청 (cooldown 무시) |
| `UNDERSTANDING_UNCERTAIN` | 통과 + 직전 대규모 변경 |
| `REPEATED_FAILURE` | 동일 결과 ≥3 + 같은 영역 ≥2, 또는 편집 없이 반복 실행, 또는 연속 에러 ≥3 |
| `NO_PROGRESS` | 90초 무진전 + 실행 ≥2 |

Monitor는 `status`(6종)도 함께 분류한다. `status`와 `trigger`는 별개라서,
"막힌 걸 알지만 지금은 개입하지 않는다"(cooldown 중)가 표현된다.

### Agent가 하는 일

- 패턴의 교육적 의미 해석
- 학생이 막힌 개념 추정
- **어떤 방식으로** 학습시킬지 선택 (호출 여부는 Monitor가 이미 결정)
- Activity 생성 및 결과 평가

이 분리를 통해 비용과 지연을 줄인다. Agent는 세션당 5~10회만 호출된다.

---

## 7. LLM 및 도구 구성

### 권장 구현

- Backend: Python + FastAPI
- Agent orchestration: 직접 구현한 state machine
- 출력: JSON Schema 또는 Pydantic model
- 모델 Provider: 환경변수로 교체 가능하게 구성
- Code Judge: deterministic Tool
- Activity answer verification: rule + Judge 우선

### Provider 인터페이스

```python
class LLMProvider:
    async def generate_structured(
        self,
        system_prompt: str,
        payload: dict,
        output_schema: type,
    ) -> object:
        ...
```

환경변수 예시:

```env
LLM_PROVIDER=openai
LLM_MODEL=<selected-model>
```

### Agent Tool

- `get_problem(problem_id)`
- `get_current_code(session_id)`
- `get_recent_trace(session_id)`
- `run_code(code, tests)`
- `verify_generated_activity(activity)`
- `get_learner_state(session_id)`
- `save_intervention(result)`

---

## 8. Prompt 설계

### 공통 규칙

- 학생에게 전체 정답 코드를 제공하지 않는다.
- 한 번에 하나의 개념만 다룬다.
- Process Trace에 명시되지 않은 학습 상태를 확정적으로 단정하지 않는다.
- 근거가 약하면 confidence를 낮추고 질문 또는 `WAIT`을 선택한다.
- Action은 허용된 enum에서만 선택한다.
- 모든 판단에 짧은 evidence를 첨부한다.

### Analyst/Planner System Prompt 핵심

```text
당신은 프로그래밍 입문자의 문제 해결 과정을 분석하는 교육 Agent다.
최종 코드뿐 아니라 최근 테스트 추세, 코드 수정 패턴, 반복 오류를 함께 고려한다.
학생이 스스로 진전 중이면 개입하지 않는다.
정답을 직접 제공하지 않고 WAIT, HINT, TRACE, PREDICT, DEBUG, VERIFY 중 하나를 선택한다.
출력은 주어진 JSON Schema를 정확히 따른다.
```

---

## 9. Shared Learner State

MVP에서는 정교한 Knowledge Tracing을 구현하지 않는다.

```json
{
  "session_id": "sess_699b671f0ece44199bfd220977ff12f8",
  "concepts": {
    "loop_iteration": {
      "status": "OK",
      "evidence": ["predict_success"]
    },
    "loop_boundary": {
      "status": "NEEDS_REVIEW",
      "evidence": ["same_failure_x3", "trace_failed"]
    }
  },
  "interventions": 2
}
```

`mastery = 0.73`과 같은 근거 없는 정밀 수치는 사용하지 않는다. 관찰 가능한 evidence와 상태 label을 중심으로 관리한다.

---

## 10. Agent API 계약

### 분석 및 행동 결정 — 구현됨 (stub)

```http
POST /agent/decide
```

```json
{ "session_id": "sess_699b671f0ece44199bfd220977ff12f8" }
```

`trigger` 필드를 함께 보낼 수는 있지만 **서버가 무시한다.** Context Builder가 세션의
현재 Process State를 직접 평가해 붙이기 때문이다 — 클라이언트가 보낸 trigger를 신뢰하면
Monitor를 우회할 수 있다.

응답:

```json
{
  "state": "STUCK",
  "concept": "loop_boundary",
  "action": "TRACE",
  "reason": "동일 테스트 결과가 반복되고 같은 반복문 범위가 수정됨",
  "activity": {}
}
```

**이 스키마는 확정이다.** 오늘은 stub이 항상 `action: "WAIT"`을 반환하지만,
프론트는 6종 action UI를 지금 다 만들어둘 수 있다.

실전에서 Agent가 호출되는 주 경로는 이 엔드포인트가 아니라 **`POST /sessions/{id}/run|submit`**이다.
Monitor가 trigger를 만들면 서버가 내부에서 Context Builder → `agent.decide()`를 부르고,
결과를 응답의 `agent_decision` 필드에 실어 보낸다. `/agent/decide`는 수동 호출·디버그용이다.

Agent 호출이 실패하면 `agent_decision: null`로 나가고 **채점 결과는 정상 반환된다.**

### AgentContext — Agent가 받는 입력

`build_context()`가 만들어 넘긴다. §13(backend_plan)의 형태와 동일하며 실제 trace로 채워진다.

```python
@dataclass(frozen=True)
class AgentContext:
    session_id: str
    problem: dict              # title, concepts, description_summary, function_name
    current_code: str
    current_code_version: int
    judge_result: dict | None  # status, passed, total, failed_categories
    recent_trace: list[str]    # ["RUN 3/5", "반복문 영역 수정 (1줄)", "RUN 3/5"] -- 최근 10개
    features: dict             # Process Feature 전체
    process_status: str        # STUCK 등 6종
    trigger: str | None        # REPEATED_FAILURE 등 4종
    evidence: list[str]        # 서버가 만든 한국어 근거
    previous_interventions: list[dict]
```

DB 전체를 넘기지 않는다. `recent_trace`는 최근 의미 있는 이벤트 10개까지만 넣어 토큰을 아낀다.

`previous_interventions`는 `AGENT_TRIGGER` 이벤트 이력에서 나온다 — 별도 테이블이 없어도
"직전에 무엇으로 개입했는지"를 알 수 있다.

### Activity 답변 평가 — 미구현

```http
POST /activities/{activity_id}/answers
```

응답 (설계):

```json
{
  "result": "CORRECT",
  "next_step": "RETURN_TO_ORIGINAL_TASK",
  "learner_state_update": { "loop_boundary": "RECOVERING" }
}
```

Activity 저장소가 아직 없다. 다만 학생의 활동 결과는 이미 이벤트로 수집 가능하고,
`ACTIVITY_RESPONSE`의 `payload.result == "CORRECT"`를 **feature extractor가 진전 anchor로
인정**한다. 즉 Activity가 붙으면 "개입 → 성공 → 회복" 흐름이 trace에 자동으로 반영된다.

---

## 11. 평가 계획

### 필수 지표

1. **Process State Accuracy**  
   사전 라벨링한 trajectory에 대해 `PROGRESSING`, `STUCK`, `UNDERSTANDING_UNCERTAIN` 분류 정확도 측정

2. **Action Selection Accuracy**  
   사람이 정한 권장 action과 Agent 선택 비교

3. **Structured Output Success Rate**  
   JSON parsing 성공률

4. **Average Latency**  
   Agent 결정 및 Activity 생성 응답 시간

5. **Token Cost per Session**  
   세션당 입력·출력 토큰과 호출 횟수

6. **Intervention Outcome**  
   개입 전후 테스트 점수 개선 또는 Activity 성공 여부

### Ablation

```text
Baseline A: Current Code + Current Test Result
CodeTrace: Current Code + Test Result + Coding Trace
```

동일한 시나리오에서 상태 판단과 action 선택이 얼마나 개선되는지 비교한다.

---

## 12. 2일 개발 일정

## Day 1 오전

- Pydantic 기반 Agent 입력·출력 Schema 확정
- 10개 synthetic trajectory 작성
- Process Analyst + Planner prompt 작성
- Provider wrapper 구현
- mock context로 JSON 출력 검증

## Day 1 오후

- Backend trace context와 Agent 연결
- `WAIT`, `HINT`, `TRACE`, `PREDICT` 지원
- Activity Generator 구현
- Code Judge를 이용한 Activity 정답 검증
- 첫 E2E: 반복 실패 → TRACE 표시

## Day 2 오전

- Evaluator와 replanning 구현
- `DEBUG`, `VERIFY` 추가
- shared learner state 저장
- fallback 및 오류 처리
- 모델 응답 안정화

## Day 2 오후

- 20개 trajectory 자동 평가
- 코드만 제공한 baseline과 비교
- latency/token logging
- 데모 시나리오 3개 고정
- 발표용 Agent workflow 시각화

---

## 13. 담당자 산출물

Agent/Integration 담당자는 다음을 최종 책임진다.

- Agent schemas
- prompts
- LLM provider wrapper
- `analyze_and_plan()`
- `generate_activity()`
- `evaluate_activity()`
- Agent API 연동
- token/latency logging
- synthetic evaluation dataset
- 데모 시나리오
- 전체 E2E integration

---

## 14. 완료 기준

다음 세 시나리오가 안정적으로 실행되면 Agent MVP를 완료한 것으로 본다.

**세 시나리오의 탐지는 이미 동작한다.** Monitor가 올바른 상태와 trigger를 만들어내는 것까지
로컬 서버에서 검증됐다. 남은 것은 trigger를 받아 action을 고르고 Activity를 만드는 부분이다.

### 시나리오 A: Productive Struggle

```text
2/5 → 3/5 → 4/5
Monitor:      PROGRESSING, trigger 없음        [검증됨]
Agent Action: (호출 자체가 일어나지 않음)
```

개입하지 않는 것이 정답이므로 **Agent 없이도 이 시나리오는 완성이다.**

### 시나리오 B: 반복문 경계에서 정체

```text
3/5 → 3/5 → 3/5, 같은 loop 영역 반복 수정
Monitor:      STUCK / REPEATED_FAILURE          [검증됨]
              근거: "동일 결과 3/5 ×3", "반복문 영역 ×2 반복 수정"
Agent Action: TRACE                             [미구현]
학생 활동 성공 → 원래 문제 복귀 → 5/5           [미구현]
```

### 시나리오 C: 이해 불확실

```text
대규모 코드 변화 → 즉시 5/5
Monitor:      UNDERSTANDING_UNCERTAIN            [검증됨]
Agent Action: VERIFY                             [미구현]
학생 설명 평가                                    [미구현]
```

이 시나리오 때문에 규칙 순서를 조정했다. `3/5 → 5/5`는 점수상 진전(+2)이라
진전 가드가 먼저 잡아버리는데, 요점이 바로 "겉보기 진전이 의심스러운 경우"이므로
`UNDERSTANDING_UNCERTAIN` 규칙을 진전 가드보다 위에 둔다.

최종적으로 Agent는 다음 문장을 시스템 동작으로 증명해야 한다.

> **CodeTrace는 학생에게 항상 답하지 않는다. 학생의 문제 해결 과정을 보고, 지금 어떤 방식으로 학습시켜야 하는지를 결정한다.**
