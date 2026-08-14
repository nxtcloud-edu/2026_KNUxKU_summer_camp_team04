#!/usr/bin/env bash
# 실 서비스(현재 떠 있는 backend/agent 프로세스)에 대고 "Monitor -> agent 호출"이
# 실제로 동작하는지 검증하는 스모크 스크립트.
#
# 단위 테스트(backend/tests, agent/tests)는 규칙/파이프라인 로직을 mock으로
# 커버하지만, "지금 이 컴퓨터에서 backend(8000)와 agent(8100)가 실제로 붙어서
# 진짜 LLM 응답을 돌려주는가"는 그 테스트들이 증명하지 못한다. 이 스크립트는
# 그 틈을 메운다 -- curl로 실제 API를 때리고 실제 이벤트/응답을 검사한다.
#
# 사전 준비:
#   backend(8000), agent(8100)가 떠 있어야 한다 (CLAUDE.md "전체 스택 띄우기" 참고).
#   agent 소스를 고쳤다면 agent 프로세스를 반드시 재시작할 것 -- --reload 없이
#   떠 있으면 코드가 바뀌어도 예전 동작 그대로 응답한다 (실제로 이 스크립트를
#   만들며 겪었다: 재시작 전엔 구 코드의 LLM 문구가, 재시작 후엔 새 코드의
#   결정론적 문구가 나왔다).
#
# 사용법:
#   cd backend && bash scripts/verify_agent_live.sh
#   BASE_URL=http://localhost:8000 STUDENT_EMAIL=... STUDENT_PASSWORD=... bash scripts/verify_agent_live.sh
#
# 각 TC는 **독립된 세션**을 새로 만든다 -- 이전 TC의 쿨다운/트리거 이력이
# 다음 TC 판정에 섞이면 안 되기 때문이다 (쿨다운 TC만 예외로 직전 TC의
# 세션을 이어받는다).

set -uo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
STUDENT_EMAIL="${STUDENT_EMAIL:-demo.student@tutory.dev}"
STUDENT_PASSWORD="${STUDENT_PASSWORD:-Demo1234!}"
PROBLEM_ID="${PROBLEM_ID:-func_sum_list}"

PASS_COUNT=0
FAIL_COUNT=0

pass() { echo "  ✅ PASS: $1"; PASS_COUNT=$((PASS_COUNT + 1)); }
fail() { echo "  ❌ FAIL: $1"; FAIL_COUNT=$((FAIL_COUNT + 1)); }

# $1=설명 $2=실제값 $3=기대값(문자열 포함 검사)
assert_contains() {
  if [[ "$2" == *"$3"* ]]; then pass "$1"; else fail "$1 (기대: '$3' 포함 / 실제: '$2')"; fi
}

assert_true() {
  if [[ "$2" == "true" ]]; then pass "$1"; else fail "$1 (실제: '$2')"; fi
}

login() {
  TOKEN=$(curl -s -X POST "$BASE_URL/auth/login" -H "Content-Type: application/json" \
    -d "{\"email\":\"$STUDENT_EMAIL\",\"password\":\"$STUDENT_PASSWORD\"}" | jq -r .access_token)
  if [[ -z "$TOKEN" || "$TOKEN" == "null" ]]; then
    echo "로그인 실패. backend(8000)가 떠 있는지, 계정이 맞는지 확인하세요." >&2
    exit 1
  fi
}

new_session() {
  curl -s -X POST "$BASE_URL/sessions" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "{\"problem_id\":\"$PROBLEM_ID\"}" | jq -r .session_id
}

snapshot() {
  # $1=session_id $2=code
  curl -s -X POST "$BASE_URL/sessions/$1/events" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "{\"events\":[{\"type\":\"CODE_SNAPSHOT\",\"payload\":{\"code\":\"$2\"}}]}" > /dev/null
}

submit() {
  # $1=session_id $2=code -> submit 응답(JSON) 그대로 출력
  curl -s -X POST "$BASE_URL/sessions/$1/submit" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "{\"code\":\"$2\"}"
}

# 대규모 재작성으로 통할 코드. func_sum_list 정답이며 for 루프가 있어
# comprehension_check의 앵커 문구("for 반복문")로 정체를 확인하기 좋다.
PASTE_CODE='def sum_list(arr):\n    total = 0\n    for x in arr:\n        total += x\n    return total\n'
WRONG_CODE='def sum_list(arr):\n    return 0\n'

echo "=== 대상: $BASE_URL (학생: $STUDENT_EMAIL, 문제: $PROBLEM_ID) ==="
login
echo

# ---------------------------------------------------------------------------
echo "[TC1] agent 배선 확인 -- 트리거 조건 없이도 SOS(HELP_REQUESTED)는 항상 응답한다"
echo "      (R0는 Monitor 트리거와 무관하게 작동해야 하므로, 이게 실패하면 agent 서비스가"
echo "       안 붙었거나 WAIT로만 폴백 중이라는 뜻이다)"
SID=$(new_session)
RESP=$(curl -s -X POST "$BASE_URL/agent/decide" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SID\",\"trigger\":\"HELP_REQUESTED\"}")
ACTION=$(echo "$RESP" | jq -r .action)
MESSAGE=$(echo "$RESP" | jq -r '.activity.message // ""')
if [[ "$ACTION" != "null" && -n "$MESSAGE" ]]; then
  pass "SOS 호출이 실제 응답을 받음 (action=$ACTION)"
  echo "      학생 화면: $MESSAGE"
else
  fail "SOS 호출이 빈 응답 또는 에러 (action=$ACTION) -- agent(8100) 헬스체크와 AGENT_WIRING 확인 필요"
fi
echo

# ---------------------------------------------------------------------------
echo "[TC2] R2 -- 붙여넣고 즉시 통과 -> UNDERSTANDING_UNCERTAIN, LLM 미호출(결정론적 문구)"
SID=$(new_session)
snapshot "$SID" "$PASTE_CODE"
RESP=$(submit "$SID" "$PASTE_CODE")
TRIGGER=$(echo "$RESP" | jq -r .process_state.trigger)
MESSAGE=$(echo "$RESP" | jq -r '.agent_decision.activity.message // ""')
assert_contains "trigger=UNDERSTANDING_UNCERTAIN" "$TRIGGER" "UNDERSTANDING_UNCERTAIN"
assert_contains "붙여넣기 분기 문구(코드가 한 번에 많이 바뀌었네요)가 LLM 아닌 comprehension_check에서 옴" \
  "$MESSAGE" "코드가 한 번에 많이 바뀌었네요"
echo "      학생 화면: $MESSAGE"
echo

# ---------------------------------------------------------------------------
echo "[TC3] R7b -- 검증된 코드 이후 대규모 재작성을 붙여넣고 실행하지 않음 (하트비트 배경 경로)"
SID=$(new_session)
submit "$SID" "$WRONG_CODE" > /dev/null   # 먼저 뭔가 실행해 '검증된 코드'를 만든다 (첫 편집 예외 회피)
snapshot "$SID" "$PASTE_CODE"
echo "      paste_settle_seconds(기본 5초) 초과까지 대기 중..."
sleep 6
HB=$(curl -s -X POST "$BASE_URL/sessions/$SID/heartbeat" -H "Authorization: Bearer $TOKEN")
HB_TRIGGER=$(echo "$HB" | jq -r .trigger)
assert_contains "하트비트가 UNDERSTANDING_UNCERTAIN을 감지" "$HB_TRIGGER" "UNDERSTANDING_UNCERTAIN"
sleep 1.5   # 백그라운드 agent 호출이 AGENT_INTERVENTION을 기록할 시간
EVENTS=$(curl -s "$BASE_URL/sessions/$SID/events?since_seq=0" -H "Authorization: Bearer $TOKEN")
INTERVENTION_MSG=$(echo "$EVENTS" | jq -r '[.events[] | select(.type=="AGENT_INTERVENTION")][0].payload.activity.message // ""')
assert_contains "AGENT_INTERVENTION이 결정론적 문구로 기록됨(LLM 미사용 확인)" \
  "$INTERVENTION_MSG" "코드가 한 번에 많이 바뀌었네요"
echo "      학생 화면: $INTERVENTION_MSG"
echo

# ---------------------------------------------------------------------------
echo "[TC4] R5b -- 편집 없이 같은 오답을 반복 제출 -> STUCK/REPEATED_FAILURE"
SID=$(new_session)
submit "$SID" "$WRONG_CODE" > /dev/null
submit "$SID" "$WRONG_CODE" > /dev/null
RESP=$(submit "$SID" "$WRONG_CODE")
TRIGGER=$(echo "$RESP" | jq -r .process_state.trigger)
STATUS=$(echo "$RESP" | jq -r .process_state.status)
assert_contains "3연속 동일 오답 -> REPEATED_FAILURE" "$TRIGGER" "REPEATED_FAILURE"
assert_contains "status=STUCK" "$STATUS" "STUCK"
echo

# ---------------------------------------------------------------------------
echo "[TC5] R1 -- 트리거 직후 쿨다운 동안은 재발화가 억제된다 (GET은 읽기전용이라 안전하게 확인 가능)"
# TC4의 세션을 그대로 이어받는다 -- 방금 트리거된 쿨다운을 봐야 하므로.
CD=$(curl -s "$BASE_URL/sessions/$SID/process-state" -H "Authorization: Bearer $TOKEN")
CD_ACTIVE=$(echo "$CD" | jq -r .cooldown_active)
CD_TRIGGER=$(echo "$CD" | jq -r .trigger)
CD_STATUS=$(echo "$CD" | jq -r .status)
assert_true "cooldown_active=true" "$CD_ACTIVE"
if [[ "$CD_TRIGGER" == "null" ]]; then pass "쿨다운 중엔 trigger가 억제됨"; else fail "쿨다운 중인데 trigger=$CD_TRIGGER (억제 안 됨)"; fi
assert_contains "그래도 status 분류는 유지됨(STUCK)" "$CD_STATUS" "STUCK"
echo

# ---------------------------------------------------------------------------
echo "[TC6] R3/R8 -- 서로 다른 오답을 반복 시도 -> 강제 개입 없음 (스스로 풀 여지가 있다고 봄)"
SID=$(new_session)
submit "$SID" 'def sum_list(arr):\n    return -1\n' > /dev/null
RESP=$(submit "$SID" 'def sum_list(arr):\n    return 1\n')
TRIGGER=$(echo "$RESP" | jq -r .process_state.trigger)
if [[ "$TRIGGER" == "null" ]]; then pass "서로 다른 시도 중엔 트리거 없음"; else fail "트리거가 발생함(trigger=$TRIGGER) -- 오탐 의심"; fi
echo

# ---------------------------------------------------------------------------
echo "=== 결과: PASS $PASS_COUNT / FAIL $FAIL_COUNT ==="
[[ "$FAIL_COUNT" -eq 0 ]]
