FROM python:3.11-slim

# 최소 권한 유저 생성 (root로 학생 코드를 실행하지 않음)
RUN useradd --create-home --uid 1000 sandbox

# check_type별 하네스 스크립트를 전부 담는다.
# 어떤 스크립트를 실행할지는 judge_service.py가 컨테이너 실행 시
# entrypoint를 오버라이드해서 결정한다 (HARNESS_BY_CHECK_TYPE 참고).
COPY harness/ /harness/

USER sandbox
WORKDIR /harness
