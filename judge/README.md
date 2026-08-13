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

## 테스트
```
pytest tests/
```

## 문제 추가
`problems/*.json`에 파일을 추가하면 코드 수정 없이 바로 채점 가능하다.
JSON 스키마와 API 응답 스펙은 [CLAUDE.md](CLAUDE.md) 참고.

DMOJ류 문제 패키지(problem.md + init.yml + N.in/N.out)가 있으면 변환 스크립트로
일괄 등록 가능:
```
python scripts/convert_dmoj_package.py <소스폴더1> [<소스폴더2> ...]
```
