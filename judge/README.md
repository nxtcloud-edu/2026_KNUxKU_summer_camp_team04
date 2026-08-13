# Judge 서비스

CodeTrace의 코드 실행/채점 서비스. 학생이 제출한 Python 코드를 Docker
컨테이너에서 격리 실행하고, 문제별 Public/Hidden 테스트케이스로 채점한다.

## 준비
- Docker Desktop/Engine이 실행 중이어야 함
- `pip install -r requirements.txt`

## 샌드박스 이미지 빌드
```
docker build -t judge-sandbox .
```

**`harness/` 를 고치거나 하네스를 추가했으면 반드시 다시 빌드한다.** 하네스는
이미지 안에 복사되어 들어가므로, 이미지가 낡으면 컨테이너가 "No such file" 을
뱉고 채점이 전부 실패한다. 그 경우 결과는 `INTERNAL_ERROR` 로 나온다 —
학생 코드 문제가 아니라 채점기 문제라는 신호다.

## 결과 status — 누구 잘못인지로 갈린다

| status | 의미 | backend 가 학생 오류로 세나 |
|---|---|---|
| `ACCEPTED` / `WRONG_ANSWER` | 채점됨 | — |
| `SYNTAX_ERROR` | 컨테이너 띄우기 전 `compile()` 실패 | ○ |
| `RUNTIME_ERROR` | **학생 코드**가 예외를 던졌다 | ○ |
| `TIME_LIMIT` | 제한시간 초과 | ○ |
| `INTERNAL_ERROR` | **채점 인프라 고장** (데몬 연결 실패, 컨테이너 실행 실패, 무출력, 로그 파싱 실패) | **✗** |

경계선은 "하네스가 실행돼서 결과를 보고했는가"다. 하네스는 `status` 키를 절대
쓰지 않고 `{"results"\|"outputs": ...}` 또는 `{"error": ...}` 만 내므로, 호스트가
만든 `status` 의 존재 자체가 "우리 쪽에서 뭔가 잘못됐다"의 판별자가 된다
(`judge_service.HOST_OUTCOME_STATUSES`).

**이 구분이 없으면**: 도커가 죽어 있을 때 학생이 Run 을 세 번 누르는 것만으로
backend 가 `REPEATED_FAILURE` 로 판정하고 agent 가 "반복문을 살펴보세요" 같은
엉뚱한 개입을 한다. 학생에게 필요한 말은 "채점 서버가 고장났어요"다.

## 테스트
```
pytest tests/
```
Docker 가 실행 중이어야 하고 `judge-sandbox` 이미지가 빌드돼 있어야 한다.

## 문제 추가
`problems/*.json`에 파일을 추가하면 코드 수정 없이 바로 채점 가능하다.
JSON 스키마와 API 응답 스펙은 [CLAUDE.md](CLAUDE.md) 참고.

DMOJ류 문제 패키지(problem.md + init.yml + N.in/N.out)가 있으면 변환 스크립트로
일괄 등록 가능:
```
python scripts/convert_dmoj_package.py <소스폴더1> [<소스폴더2> ...]
```

## API 서버 (임시 — backend 생기기 전까지 프론트 연동용)
```
python -m uvicorn main:app --reload --port 8000
```
- `GET /problems` — 문제 목록
- `GET /problems/{problem_id}` — 문제 상세 (hidden 테스트케이스 제외)
- `POST /judge` — `{ "student_code", "problem_id", "mode" }` → 채점 결과

CORS는 전체 허용(`*`)해뒀음 — 로컬 데모용이라 그런 거고, 실제 배포 시엔
반드시 프론트 도메인으로 제한할 것.
