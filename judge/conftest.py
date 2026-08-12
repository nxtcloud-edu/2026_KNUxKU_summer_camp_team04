# pytest가 이 파일을 발견하면 judge/ 디렉터리를 sys.path에 추가한다.
# 이 덕분에 tests/에서 `import judge_service`가 어떤 방식으로 pytest를
# 실행해도(=`pytest tests/`, `python -m pytest` 등) 동작한다.
