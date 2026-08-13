# TUTORY B2B Backend 제품 요구사항

> 대상: Backend 개발 담당자  
> 목적: TUTORY Course를 초기 시장 진입 상품으로 출시하고, 이후 Department와 Enterprise까지 재설계 없이 확장할 수 있는 Backend 기반을 정의한다.

## 1. 제품 계층

### TUTORY Course

교수자 한 명이 직접 도입하는 기본 상품이다.

- 과제와 테스트케이스 등록
- 단계별 AI 힌트
- 코드 오류 및 개념 설명
- 학생별 질문 기록
- 자주 발생한 오류 통계
- 교수자 대시보드

초기 구현과 판매의 최우선 범위다.

### TUTORY Department

학과 단위 관리 상품이다.

- 여러 강의와 교수자 관리
- Python, Java, C 등 언어별 설정
- 선수·후속 과목 간 학습 분석
- 학과 공통 문제은행
- 학과 수준 성취도 보고서
- 조교 계정과 세부 권한

### TUTORY Enterprise

대학 본부 또는 교수학습개발센터 대상 상품이다.

- 학교 계정 SSO 및 SCIM
- LMS 연동
- 데이터 보관 기간 설정
- 대학별 AI 정책
- 관리자 감사 로그
- 전용 서버 또는 Private Cloud
- 기술지원 및 SLA

세 상품을 별도 서비스로 만들지 않는다. 하나의 멀티테넌트 플랫폼에서 구독 플랜과 기능 권한으로 구분한다.

```text
Organization
└── Department
    ├── Course
    │   ├── Educators / Teaching Assistants
    │   ├── Students
    │   ├── Assignments
    │   └── Learning Records
    └── Shared Problem Bank
```

## 2. 현재 Backend와의 차이

현재 구현되어 있는 기반:

- 문제 데이터 및 Problem API
- 문제 풀이 Session
- Code Snapshot / Diff
- Coding Trace Event
- Judge 결과 수집
- Process Feature와 Monitor
- Agent Context Builder

새로 구현해야 하는 핵심 영역:

- 실제 사용자 DB와 인증
- 학생·교수자·조교·관리자 권한
- 기관·학과·강의·수강 관계
- 과제와 학생별 제출 현황
- 질문·AI 대화 기록
- 교수자용 통계와 분석 API
- 플랜·구독·기능 제한

현재 `sessions.user_id`의 `demo-user` 문자열은 실제 User FK로 전환해야 한다.

## 3. 멀티테넌시 원칙

Course MVP부터 다음 식별자를 데이터 모델에 포함한다.

```text
organization_id
department_id
course_id
user_id
```

필수 원칙:

1. 모든 교육 데이터는 Organization 경계를 가진다.
2. 교수자는 자신이 담당하거나 권한을 부여받은 Course만 조회한다.
3. 프런트가 전달한 `organization_id`나 `course_id`만 신뢰하지 않는다.
4. 인증 토큰의 사용자 ID와 Membership을 기준으로 접근을 검증한다.
5. 다른 기관 데이터에 대한 IDOR 공격을 반드시 차단한다.

## 4. 사용자와 인증

### 4.1 역할

```text
PLATFORM_ADMIN
ORGANIZATION_ADMIN
DEPARTMENT_ADMIN
EDUCATOR
TEACHING_ASSISTANT
STUDENT
AUDITOR
```

Course MVP에서는 우선 `EDUCATOR`, `STUDENT`, `PLATFORM_ADMIN`만 구현해도 된다. 역할 컬럼은 위 확장을 수용할 수 있어야 한다.

### 4.2 users

| 필드 | 설명 |
|---|---|
| `id` | UUID 또는 접두어 UUID PK |
| `email` | 정규화된 로그인 이메일, UNIQUE |
| `password_hash` | Argon2 또는 bcrypt 해시 |
| `name` | 실명 |
| `nickname` | 서비스 표시명 |
| `role` | 사용자 기본 역할 |
| `avatar_url` | Object Storage 이미지 URL |
| `acorn_balance` | 사용 가능한 도토리 |
| `total_acorns_earned` | 누적 획득 도토리 |
| `is_active` | 계정 활성 여부 |
| `created_at` | 가입 시각 |
| `updated_at` | 수정 시각 |
| `last_login_at` | 최근 로그인 |

### 4.3 인증 API

```http
POST /auth/signup
POST /auth/login
POST /auth/logout
POST /auth/refresh
GET  /auth/me
POST /auth/password-reset/request
POST /auth/password-reset/confirm
```

회원가입 요청:

```json
{
  "name": "김민서",
  "email": "minseo@univ.ac.kr",
  "password": "password123",
  "role": "STUDENT"
}
```

주의사항:

- 교수자 가입은 기관 코드 또는 관리자 승인을 요구하는 것이 안전하다.
- Access Token은 짧게 유지한다.
- Refresh Token은 HttpOnly, Secure, SameSite Cookie를 권장한다.
- 회원 존재 여부가 비밀번호 재설정 응답으로 노출되지 않아야 한다.

### 4.4 게스트 정책

| 기능 | 게스트 | 인증 사용자 |
|---|---:|---:|
| 홈·문제 목록 | 허용 | 허용 |
| 문제 지문 조회 | 허용 | 허용 |
| 에디터 코드 작성 | 허용 | 허용 |
| 실행·제출 | 차단 | 허용 |
| TRACE | 차단 | 허용 |
| AI 튜터 | 차단 | 허용 |
| 서버 Checkpoint | 차단 | 허용 |
| 도토리창고 | 차단 | 학생 허용 |
| 교육자 Console | 차단 | 교수자 허용 |

보호 기능은 Backend에서도 인증을 검사해야 한다.

## 5. 기관·학과·강의 모델

### organizations

```text
id, name, domain, invite_code, plan_id, is_active,
data_region, retention_policy_days, created_at
```

### departments

```text
id, organization_id, name, code, is_active, created_at
```

### courses

```text
id, organization_id, department_id, title, term,
primary_educator_id, start_at, end_at, is_active, created_at
```

### course_memberships

```text
id, course_id, user_id, role, status, enrolled_at
UNIQUE(course_id, user_id)
```

Course 내 역할은 사용자 기본 역할과 별도로 둔다. 한 사용자가 한 강의에서는 교수자이고 다른 강의에서는 학생일 가능성도 모델이 수용해야 한다.

### 기본 API

```http
GET    /courses
POST   /courses
GET    /courses/{course_id}
PATCH  /courses/{course_id}
POST   /courses/{course_id}/members
DELETE /courses/{course_id}/members/{user_id}
```

## 6. 문제은행과 다중 언어

### problem_banks

```text
id, organization_id, department_id, owner_id, name,
visibility, created_at, updated_at
```

### problem_bank_items

```text
problem_bank_id, problem_id, created_by, created_at
```

가시성 예시:

```text
PRIVATE
COURSE
DEPARTMENT
ORGANIZATION
```

Java와 C 지원은 언어별 Judge Adapter로 분리한다.

```text
LanguageAdapter
├── build_command
├── run_command
├── docker_image
├── error_parser
├── trace_adapter
└── resource_limits
```

## 7. 과제

### assignments

```text
id, course_id, title, description, due_at,
created_by, status, published_at, created_at, updated_at
```

### assignment_problems

```text
assignment_id, problem_id, display_order, points
```

### assignment_progress

```text
assignment_id, student_id, status, completed_count,
score, submitted_at, updated_at
```

상태:

```text
DRAFT
PUBLISHED
NOT_STARTED
IN_PROGRESS
SUBMITTED
LATE
```

API:

```http
POST   /courses/{course_id}/assignments
GET    /courses/{course_id}/assignments
GET    /assignments/{assignment_id}
PATCH  /assignments/{assignment_id}
DELETE /assignments/{assignment_id}
POST   /assignments/{assignment_id}/publish
```

## 8. 학생 진행 상태

### user_problem_progress

```text
id, organization_id, course_id, user_id, problem_id,
status, current_code, best_passed, total_tests,
attempt_count, last_judge_status, first_started_at,
last_attempted_at, solved_at, updated_at

UNIQUE(course_id, user_id, problem_id)
```

상태:

```text
NOT_STARTED
IN_PROGRESS
SOLVED
```

API:

```http
GET /courses/{course_id}/my-progress
GET /courses/{course_id}/problems/{problem_id}/progress
PUT /courses/{course_id}/problems/{problem_id}/checkpoint
```

현재 브라우저 LocalStorage Checkpoint를 서버 저장으로 교체할 때 사용한다.

## 9. 교육자 대시보드 API

### 9.1 요약

```http
GET /educator/courses/{course_id}/dashboard
```

```json
{
  "course": {
    "id": "course_python_01",
    "title": "Python 기초 01",
    "term": "2026 여름학기",
    "educator_name": "김튜토리"
  },
  "metrics": {
    "student_count": 28,
    "student_count_delta": 2,
    "average_progress": 64,
    "weekly_progress_delta": 8,
    "completion_rate": 71,
    "total_attempts": 728,
    "needs_attention_count": 2
  }
}
```

### 9.2 학생 목록

```http
GET /educator/courses/{course_id}/students
  ?q=민서
  &status=NEEDS_HELP
  &sort=progress_asc
  &page=1
  &size=30
```

```json
{
  "items": [
    {
      "student_id": "user_001",
      "name": "김민서",
      "email": "minseo@univ.ac.kr",
      "avatar_url": null,
      "progress": 82,
      "solved_count": 21,
      "attempt_count": 31,
      "last_active_at": "2026-08-13T14:48:00Z",
      "learning_status": "ON_TRACK",
      "weak_concepts": ["loop"]
    }
  ],
  "total": 28
}
```

### 9.3 학생 상세

```http
GET /educator/courses/{course_id}/students/{student_id}
```

응답에 포함할 항목:

- 진도와 완료 문제 수
- 실행·제출 횟수
- 최근 학습 활동
- 취약 개념
- 반복 실패 이유
- 최근 Session과 Snapshot
- 추천 교수자 행동

## 10. 도움 필요 학생 탐지

기존 Trace / Monitor를 활용해 Course 수준의 `risk_score`를 계산한다.

입력 지표:

- 동일 Judge 결과 반복
- 동일 코드 영역 반복 수정
- 일정 시간 진전 없음
- 시도 횟수 대비 통과율
- 최근 활동 시각
- AI 튜터 호출 횟수
- TRACE 결과
- 과제 마감 임박 및 미진행

상태:

```text
ON_TRACK
WATCH
NEEDS_HELP
INACTIVE
```

권장 요약 모델:

```text
student_course_stats
├── course_id
├── student_id
├── progress_rate
├── solved_count
├── attempt_count
├── last_active_at
├── learning_status
├── primary_weak_concept
├── risk_score
└── calculated_at
```

API:

```http
GET /educator/courses/{course_id}/attention
```

## 11. AI 힌트와 질문 기록

### tutor_conversations

```text
id, organization_id, course_id, student_id,
problem_id, session_id, created_at, closed_at
```

### tutor_messages

```text
id, conversation_id, sender, content,
action_type, model_name, token_usage, created_at
```

저장할 추가 메타데이터:

- 제공한 힌트 단계
- Agent가 판단한 개념
- 학생이 힌트를 수락했는지
- 도토리 사용량
- 개인정보 제거 여부

교육자 조회 API는 학생 질문 원문 공개 정책을 확인한 뒤 구현한다.

```http
GET /educator/courses/{course_id}/questions
GET /educator/courses/{course_id}/students/{student_id}/questions
```

## 12. 오류 통계

오류 분류 예시:

```text
SYNTAX_ERROR
INDENTATION_ERROR
NAME_ERROR
TYPE_ERROR
INDEX_ERROR
WRONG_ANSWER
TIME_LIMIT
CONCEPT_CONDITIONAL
CONCEPT_LOOP
CONCEPT_FUNCTION
```

집계 API:

```http
GET /educator/courses/{course_id}/analytics/errors
GET /educator/courses/{course_id}/analytics/concepts
```

원본 오류 메시지와 정규화된 `error_code`를 함께 저장한다.

## 13. 공지와 메시지

```text
announcements: id, course_id, author_id, title, content, published_at
messages: id, course_id, sender_id, recipient_id, content, read_at, created_at
```

API:

```http
POST /educator/courses/{course_id}/announcements
GET  /courses/{course_id}/announcements
POST /educator/courses/{course_id}/students/{student_id}/messages
```

## 14. 도토리 원장

현재 프런트의 도토리는 데모 LocalStorage 데이터다. 서버에서는 원장 방식으로 처리한다.

### acorn_transactions

```text
id, user_id, amount, balance_after, transaction_type,
reference_type, reference_id, idempotency_key, description, created_at
```

원칙:

- 도토리 지급·차감은 서버만 수행한다.
- 문제 최초 ACCEPTED 보상은 중복 지급하지 않는다.
- 프로필 변경과 도토리 차감을 한 DB Transaction으로 처리한다.
- `idempotency_key`와 UNIQUE 제약으로 중복 요청을 방지한다.

## 15. 플랜과 기능 제한

```text
plans
subscriptions
features
plan_features
organization_feature_overrides
usage_records
```

기능 예시:

```json
{
  "plan": "COURSE",
  "features": {
    "max_courses": 1,
    "max_students": 100,
    "shared_problem_bank": false,
    "multi_language": false,
    "sso": false,
    "lms_integration": false,
    "audit_logs": false,
    "custom_ai_policy": false
  }
}
```

기능 제한은 Backend에서 검사한다.

## 16. Department 확장 요구사항

- 학과 관리자 역할
- 여러 교수자와 강의 관리
- 조교 권한 관리
- 공통 문제은행
- 학기 간 학생 분석
- 선수·후속 교과목 그래프
- 언어별 Judge 설정
- 학과 수준 보고서

교육과정 모델 예시:

```text
curriculum_nodes
curriculum_edges
course_outcomes
student_outcome_scores
```

## 17. Enterprise 확장 요구사항

### 인증과 사용자 관리

- SAML 2.0 또는 OIDC SSO
- SCIM 2.0 Provisioning
- 기관별 도메인과 Identity Provider 설정

### LMS

- LTI 1.3
- Canvas, Moodle, Blackboard 연동
- 과제 생성 및 성적 Passback

### 데이터 정책

- 기관별 보존 기간
- 기관별 데이터 삭제 요청
- 데이터 리전
- 기관별 AI Provider 허용 목록
- AI 전송 데이터 필드 설정

### 운영

- 관리자 감사 로그
- 전용 DB 또는 Schema
- 전용 배포
- Backup / Restore
- SLA 지표와 장애 기록

감사 이벤트 예시:

```text
EDUCATOR_VIEWED_STUDENT
EDUCATOR_VIEWED_CODE
EDUCATOR_SENT_MESSAGE
EDUCATOR_CREATED_ASSIGNMENT
EDUCATOR_EXPORTED_DATA
ADMIN_CHANGED_RETENTION_POLICY
```

## 18. 보안 체크리스트

- [ ] 비밀번호 원문 저장 금지
- [ ] Refresh Token Rotation
- [ ] 모든 교육자 API 역할 검사
- [ ] Course Membership 검사
- [ ] Organization 경계 검사
- [ ] 학생 코드 열람 감사 로그
- [ ] Hidden Test Case 응답 노출 금지
- [ ] CSV Formula Injection 방지
- [ ] 업로드 파일 MIME·크기 검사
- [ ] Rate Limit
- [ ] 페이지네이션
- [ ] 개인정보 최소 노출
- [ ] 데이터 보존·삭제 정책
- [ ] AI Provider 전송 데이터 필터링

## 19. Course MVP 우선순위

### Phase 1 — 인증과 강의

1. User / Role / Auth
2. Organization / Course
3. Course Membership 및 초대 코드
4. `sessions.user_id` 실제 User 연결

### Phase 2 — 학생 학습 데이터

1. User Problem Progress
2. 서버 Checkpoint
3. Judge 결과와 SOLVED 갱신
4. 도토리 원장

### Phase 3 — 교수자 핵심 기능

1. Dashboard Summary
2. Student List / Detail
3. Attention / Risk Score
4. Assignment CRUD
5. 공지와 개별 메시지

### Phase 4 — AI·통계

1. Tutor Conversation 저장
2. 오류 정규화
3. Concept Analytics
4. 단계별 Hint 정책

### Phase 5 — 유료화

1. Plan / Subscription
2. 학생 수와 강의 수 제한
3. Usage Metering
4. 결제 및 Invoice

## 20. 프런트 연동을 위해 먼저 필요한 API

아래 API가 1차 우선 계약이다.

```http
POST /auth/signup
POST /auth/login
POST /auth/logout
GET  /auth/me

GET  /courses
POST /courses
POST /courses/{course_id}/members

GET /educator/courses/{course_id}/dashboard
GET /educator/courses/{course_id}/students
GET /educator/courses/{course_id}/students/{student_id}
GET /educator/courses/{course_id}/attention

GET /courses/{course_id}/my-progress
PUT /courses/{course_id}/problems/{problem_id}/checkpoint
```

이 API가 구현되면 현재 하드코딩된 로그인, 교육자 Console, 마이페이지, 추천 문제, 학습 현황을 실제 데이터로 교체할 수 있다.

## 21. Backend 결정이 필요한 항목

- [ ] 교수자 가입 승인 방식
- [ ] Course 초대 방식
- [ ] 한 사용자의 복수 역할 허용 여부
- [ ] 진도율 계산 공식
- [ ] 도움 필요 Risk Score 기준
- [ ] 학생 질문 원문을 교수자에게 공개할지
- [ ] 학생 코드 실시간 열람 허용 여부
- [ ] 문제 최초 정답 도토리 지급량
- [ ] Course 기본 학생 수 제한
- [ ] AI 메시지 보존 기간
- [ ] 기관 데이터 삭제 정책
- [ ] Course MVP DB를 PostgreSQL로 시작할지

---

초기 개발의 기준 상품은 **TUTORY Course**다. 다만 모든 핵심 테이블에 Organization과 Course 경계를 포함하고, 역할과 기능 권한을 서버에서 검사해야 Department·Enterprise 단계에서 인증과 학습 데이터를 다시 만들지 않는다.
