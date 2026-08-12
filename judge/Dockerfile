FROM python:3.11-slim

# 최소 권한 유저 생성 (root로 학생 코드를 실행하지 않음)
RUN useradd --create-home --uid 1000 sandbox

COPY harness/run_function_call.py /harness/run_function_call.py

USER sandbox
WORKDIR /harness

# 컨테이너 실행 시 payload.json 경로를 인자로 받아 채점을 수행한다.
# (judge_service.py가 이 경로를 command로 넘겨준다)
ENTRYPOINT ["python", "/harness/run_function_call.py"]
