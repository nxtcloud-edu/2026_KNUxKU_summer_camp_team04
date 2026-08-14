#!/usr/bin/env bash
# 실 서비스(현재 떠 있는 backend/agent/docker judge)에 대고 **복습 문제 생성**
# 전 구간이 실제로 동작하는지 검증하는 스모크 스크립트.
#
# `verify_agent_live.sh`가 "Monitor -> agent 개입" 경로를 검증하는 것과 같은 역할을
# 복습 문제 경로에 대해 한다. 단위 테스트(backend/tests/test_review_problems.py,
# agent/tests/test_problem_generator*.py)는 mock으로 로직을 커버하지만, 다음은
# 증명하지 못한다:
#
#   * backend_entry가 `get_problem_generator` seam을 실제로 override했는지
#     (override가 조용히 실패해도 단위 테스트는 전부 통과한다 -- 그쪽은 fake를
#      직접 꽂으니까. 실패하면 런타임에는 UnavailableProblemGenerator가 남아
#      모든 요청이 FAILED가 된다)
#   * 진짜 LLM이 judge 스키마에 맞는 문제를 만들어내는지
#   * 그 문제가 진짜 도커 judge를 통과하는지
#   * 생성된 파일이 ProblemRepository로 서빙되어 **큐레이션 문제와 똑같이** 풀리는지
#
# 사전 준비 (CLAUDE.md "전체 스택 띄우기"):
#   agent(8100), backend(8000, tutor_agent.backend_entry로 기동), docker judge.
#   agent 소스를 고쳤다면 agent 프로세스를 반드시 재시작할 것 -- --reload 없이
#   떠 있으면 예전 코드 그대로 응답한다.
#
# 사용법:
#   cd backend && bash scripts/verify_review_live.sh
#   POLL_TIMEOUT=300 bash scripts/verify_review_live.sh

set -uo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
STUDENT_EMAIL="${STUDENT_EMAIL:-demo.student@tutory.dev}"
STUDENT_PASSWORD="${STUDENT_PASSWORD:-Demo1234!}"
#: 복습의 바탕이 될 원본 문제. func_sum_list는 function_call 타입이라 생성 결과의
#: function_name/테스트 모양을 확인하기 쉽다.
SOURCE_PROBLEM_ID="${SOURCE_PROBLEM_ID:-func_sum_list}"
#: LLM 생성 ~25초 + judge 재시도 최대 2회. 여유를 둔다.
POLL_TIMEOUT="${POLL_TIMEOUT:-240}"

PASS_COUNT=0
FAIL_COUNT=0

pass() { echo "  ✅ PASS: $1"; PASS_COUNT=$((PASS_COUNT + 1)); }
fail() { echo "  ❌ FAIL: $1"; FAIL_COUNT=$((FAIL_COUNT + 1)); }

assert_eq() {
  # $1=설명 $2=실제 $3=기대
  if [[ "$2" == "$3" ]]; then pass "$1"; else fail "$1 (기대: '$3' / 실제: '$2')"; fi
}

assert_ne() {
  if [[ "$2" != "$3" ]]; then pass "$1"; else fail "$1 (같으면 안 되는 값: '$3')"; fi
}

assert_nonempty() {
  if [[ -n "$2" && "$2" != "null" ]]; then pass "$1"; else fail "$1 (비어 있음: '$2')"; fi
}

auth() { curl -s -H "Authorization: Bearer $TOKEN" "$@"; }

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

echo "=== 대상: $BASE_URL (학생: $STUDENT_EMAIL, 원본 문제: $SOURCE_PROBLEM_ID) ==="

TOKEN=$(curl -s -X POST "$BASE_URL/auth/login" -H "Content-Type: application/json" \
  -d "{\"email\":\"$STUDENT_EMAIL\",\"password\":\"$STUDENT_PASSWORD\"}" | jq -r .access_token)
if [[ -z "$TOKEN" || "$TOKEN" == "null" ]]; then
  echo "로그인 실패. backend(8000)가 떠 있는지, 계정이 맞는지 확인하세요." >&2
  exit 1
fi
echo

# ---------------------------------------------------------------------------
echo "[TC1] POST /users/me/review-problems -> 즉시 201 PENDING (25초를 학생이 기다리지 않는다)"
START=$(date +%s)
CREATED=$(curl -s -X POST "$BASE_URL/users/me/review-problems" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"source_problem_id\":\"$SOURCE_PROBLEM_ID\"}")
ELAPSED=$(( $(date +%s) - START ))
REQ_ID=$(echo "$CREATED" | jq -r .id)
assert_nonempty "요청 id를 받음" "$REQ_ID"
assert_eq "status=PENDING" "$(echo "$CREATED" | jq -r .status)" "PENDING"
assert_eq "problem_id는 아직 null" "$(echo "$CREATED" | jq -r .problem_id)" "null"
if [[ "$ELAPSED" -le 5 ]]; then
  pass "응답이 즉시 돌아옴 (${ELAPSED}초) -- 생성은 백그라운드"
else
  fail "응답에 ${ELAPSED}초 걸림 -- 백그라운드로 돌지 않는 것 같다"
fi
echo

# ---------------------------------------------------------------------------
echo "[TC2] 버튼 연타 -> 새 요청을 만들지 않고 같은 PENDING 행을 돌려준다 (LLM 호출 누적 방지)"
AGAIN=$(curl -s -X POST "$BASE_URL/users/me/review-problems" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"source_problem_id\":\"$SOURCE_PROBLEM_ID\"}")
assert_eq "두 번째 POST가 같은 id 반환" "$(echo "$AGAIN" | jq -r .id)" "$REQ_ID"
echo

# ---------------------------------------------------------------------------
echo "[TC3] GET 폴링 -> READY (LLM 생성 + 도커 judge 검증. 최대 ${POLL_TIMEOUT}초)"
START=$(date +%s)
STATUS="PENDING"
PROBLEM_ID="null"
ERROR_MESSAGE=""
while :; do
  ROW=$(auth "$BASE_URL/users/me/review-problems" | jq -c --arg id "$REQ_ID" '.items[] | select(.id==$id)')
  STATUS=$(echo "$ROW" | jq -r .status)
  PROBLEM_ID=$(echo "$ROW" | jq -r .problem_id)
  ERROR_MESSAGE=$(echo "$ROW" | jq -r '.error_message // ""')
  ELAPSED=$(( $(date +%s) - START ))
  [[ "$STATUS" != "PENDING" ]] && break
  if [[ "$ELAPSED" -ge "$POLL_TIMEOUT" ]]; then break; fi
  sleep 3
done
echo "      ${ELAPSED}초 후 status=$STATUS"
assert_eq "status=READY" "$STATUS" "READY"
if [[ "$STATUS" != "READY" ]]; then
  echo "      error_message: $ERROR_MESSAGE"
  echo
  echo "=== 결과: PASS $PASS_COUNT / FAIL $FAIL_COUNT (생성이 안 됐으므로 이후 TC는 건너뜀) ==="
  exit 1
fi
assert_nonempty "problem_id가 채워짐" "$PROBLEM_ID"
echo "      생성된 problem_id: $PROBLEM_ID"
echo

# ---------------------------------------------------------------------------
echo "[TC4] GET /problems/{생성id} -> 큐레이션 문제와 **같은 경로로** 서빙된다"
DETAIL=$(auth "$BASE_URL/problems/$PROBLEM_ID")
assert_eq "problem_id 일치" "$(echo "$DETAIL" | jq -r .problem_id)" "$PROBLEM_ID"
assert_ne "원본과 다른 문제다" "$PROBLEM_ID" "$SOURCE_PROBLEM_ID"
assert_nonempty "title 있음" "$(echo "$DETAIL" | jq -r .title)"
assert_nonempty "description 있음" "$(echo "$DETAIL" | jq -r .description)"
assert_nonempty "code_template 있음" "$(echo "$DETAIL" | jq -r .code_template)"
PUB_COUNT=$(echo "$DETAIL" | jq '.public_test_cases | length')
HID_COUNT=$(echo "$DETAIL" | jq -r .hidden_test_case_count)
if [[ "$PUB_COUNT" -ge 1 ]]; then pass "public_test_cases $PUB_COUNT개"; else fail "public_test_cases가 없다"; fi
if [[ "$HID_COUNT" -ge 1 ]]; then pass "hidden_test_case_count=$HID_COUNT (개수만 노출)"; else fail "hidden 테스트가 없다"; fi
if echo "$DETAIL" | jq -e 'has("hidden_test_cases")' > /dev/null; then
  fail "응답에 hidden_test_cases 원본이 들어 있다 (유출)"
else
  pass "hidden 원본값은 응답 스키마에 담길 곳이 없다"
fi
echo "      제목: $(echo "$DETAIL" | jq -r .title)"
echo

# ---------------------------------------------------------------------------
echo "[TC5] GET /problems 목록에는 안 뜬다 (복습 문제는 그 학생 개인의 것)"
# /problems는 배열을 그대로 돌려준다 (ProblemSummary[]).
IN_LIST=$(auth "$BASE_URL/problems" | jq -r --arg id "$PROBLEM_ID" '[.[].problem_id] | index($id) // "no"')
assert_eq "전체 문제 목록에 생성 문제 미포함" "$IN_LIST" "no"
echo

# ---------------------------------------------------------------------------
echo "[TC6] 생성 문제로 세션 시작 + 제출 -> 진짜 도커 judge가 실제로 채점한다"
SID=$(curl -s -X POST "$BASE_URL/sessions" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"problem_id\":\"$PROBLEM_ID\"}" | jq -r .session_id)
assert_nonempty "생성 문제로 세션이 열림" "$SID"
# 정답을 쓰지 않고 code_template을 그대로 낸다 -- 여기서 보려는 건 "맞았는가"가
# 아니라 "생성된 문제로 judge가 실제로 돌아가는가"다 (총 테스트 수 >= 1).
# 본문은 파일로 넘긴다 -- 코드에 줄바꿈/따옴표가 섞이면 -d "문자열"이 셸을
# 거치며 깨져 400 "error parsing the body"가 난다 (실제로 겪었다).
echo "$DETAIL" | jq -r .code_template > "$TMP_DIR/tpl.py"
jq -n --rawfile code "$TMP_DIR/tpl.py" '{code:$code}' > "$TMP_DIR/body.json"
SUBMIT=$(curl -s -X POST "$BASE_URL/sessions/$SID/submit" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d @"$TMP_DIR/body.json")
J_STATUS=$(echo "$SUBMIT" | jq -r '.process_state.features.last_result.status // "null"')
J_TOTAL=$(echo "$SUBMIT" | jq -r '.process_state.features.last_result.total // 0')
assert_nonempty "judge가 채점 결과를 냄 (status=$J_STATUS)" "$J_STATUS"
if [[ "$J_TOTAL" -ge 1 ]]; then
  pass "테스트케이스 $J_TOTAL개가 실제로 실행됨"
else
  fail "실행된 테스트가 0개 -- judge가 문제를 못 읽은 것 같다"
fi
echo "      제출 결과: $J_STATUS ($(echo "$SUBMIT" | jq -r '.process_state.features.last_result.passed // 0')/$J_TOTAL)"
echo

# ---------------------------------------------------------------------------
echo "[TC7] 생성 문제가 파일로 남았다 (재기동 후에도 풀 수 있다)"
GEN_DIR="${GENERATED_PROBLEMS_DIR:-generated_problems}"
if [[ -f "$GEN_DIR/$PROBLEM_ID.json" ]]; then
  pass "$GEN_DIR/$PROBLEM_ID.json 존재"
  if jq -e --arg id "$PROBLEM_ID" '.problem_id == $id and (.hidden_test_cases | length) >= 1' \
      "$GEN_DIR/$PROBLEM_ID.json" > /dev/null; then
    pass "파일에 problem_id와 hidden 테스트가 들어 있다"
  else
    fail "파일 내용이 기대와 다르다"
  fi
else
  fail "$GEN_DIR/$PROBLEM_ID.json 이 없다"
fi
echo

echo "=== 결과: PASS $PASS_COUNT / FAIL $FAIL_COUNT ==="
[[ "$FAIL_COUNT" -eq 0 ]]
