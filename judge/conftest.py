# pytest가 이 파일을 발견하면 judge/ 디렉터리를 sys.path에 추가한다.
# 이 덕분에 tests/에서 `import judge_service`가 어떤 방식으로 pytest를
# 실행해도(=`pytest tests/`, `python -m pytest` 등) 동작한다.
"""judge 테스트 전제 조건 검사.

**낡은 샌드박스 이미지는 테스트를 조용히 무의미하게 만든다.**

하네스(`harness/*.py`)는 이미지 안으로 복사되어 들어가고, 컨테이너는 레포의
파일이 아니라 **이미지에 굳어 있는 사본**을 실행한다. 그래서 하네스를 고친 뒤
재빌드하지 않으면 테스트가 검증하는 코드가 레포의 코드가 아니다.

실측한 실패 양상 (이게 이 파일이 존재하는 이유다):
  - `run_stdout_match.py`의 채점 판정을 `passed = False`로 망가뜨린 뒤
    재빌드하지 않고 `pytest tests/test_stdout_match.py` 를 돌렸더니 **3개 전부
    통과했다.** judge를 망가뜨렸는데 테스트가 초록색이다.
  - 반대 방향도 같다. 하네스를 고쳐도 테스트는 옛 동작을 계속 본다.
  - 결과 조작 취약점 회귀 테스트(`test_cannot_forge_result_via_sys_exit`)도
    이 상태에서는 아무것도 보장하지 않는다.

파일이 아예 없는 경우는 그나마 시끄럽게 터진다. capture 하네스 2개가 추가된
뒤 재빌드하지 않으면 컨테이너가 "No such file"을 뱉고 테스트 7개가 실패하는데,
에러 메시지가 채점 실패처럼 보여서 원인을 찾는 데 시간이 든다.

그래서 세션 시작 시 **이미지 안의 하네스 내용을 해시로 대조**한다. 누락과 수정을
모두 잡고, N개의 알쏭달쏭한 실패를 재빌드 명령 한 줄이 적힌 메시지 하나로 바꾼다.

`harness/` 는 이 프로젝트에서 이미 6번 바뀐 고빈도 영역이다. 사람의 기억에
의존할 자리가 아니다.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

HARNESS_DIR = Path(__file__).parent / "harness"

# 이미지 안에서 /harness/*.py 를 해시해 JSON 한 줄로 낸다.
# `python` 을 쓴다 -- 이미지에 확실히 있는 유일한 실행기다(sha256sum 등 coreutils
# 유무에 의존하지 않는다).
_HASH_SCRIPT = (
    "import hashlib,json,pathlib;"
    "print(json.dumps({p.name: hashlib.sha256(p.read_bytes()).hexdigest()"
    " for p in sorted(pathlib.Path('/harness').glob('*.py'))}))"
)


def _local_harness_hashes() -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(HARNESS_DIR.glob("*.py"))
    }


def _image_harness_hashes(client, image: str) -> dict[str, str]:
    raw = client.containers.run(
        image,
        entrypoint=["python", "-c", _HASH_SCRIPT],
        network_disabled=True,
        remove=True,
    )
    return json.loads(raw.decode("utf-8", errors="replace").strip().splitlines()[-1])


@pytest.fixture(scope="session", autouse=True)
def sandbox_image_matches_repo() -> None:
    """샌드박스 이미지가 레포의 하네스와 같은 내용인지 확인한다.

    Docker 자체가 없으면 skip 한다(테스트를 돌릴 수 없는 환경일 뿐 잘못이 아니다).
    Docker 는 있는데 이미지가 없거나 낡았으면 **실패**시킨다 -- 재빌드 한 줄로
    해결되는 일을 조용히 넘기면 그 뒤의 모든 통과가 거짓이 된다.
    """
    import docker
    from docker.errors import DockerException, ImageNotFound

    build = "cd judge && docker build -t judge-sandbox ."

    try:
        client = docker.from_env()
        client.ping()
    except DockerException as e:
        pytest.skip(
            f"Docker 를 사용할 수 없어 judge 테스트를 건너뜁니다 ({e}). "
            "Docker Desktop/Engine 을 실행한 뒤 다시 시도하세요."
        )

    # judge_service 가 실제로 쓰는 이미지 이름을 그대로 읽는다(상수 중복 방지).
    from judge_service import SANDBOX_IMAGE

    try:
        in_image = _image_harness_hashes(client, SANDBOX_IMAGE)
    except ImageNotFound:
        pytest.fail(
            f"샌드박스 이미지 '{SANDBOX_IMAGE}' 가 없습니다.\n    {build}",
            pytrace=False,
        )
    except DockerException as e:
        pytest.fail(
            f"샌드박스 이미지 '{SANDBOX_IMAGE}' 를 검사할 수 없습니다 ({e}).\n    {build}",
            pytrace=False,
        )

    local = _local_harness_hashes()
    if local == in_image:
        return

    missing = sorted(set(local) - set(in_image))
    stale = sorted(n for n in set(local) & set(in_image) if local[n] != in_image[n])
    extra = sorted(set(in_image) - set(local))

    lines = [
        f"샌드박스 이미지 '{SANDBOX_IMAGE}' 가 레포의 harness/ 와 다릅니다.",
        "",
        "컨테이너는 레포의 파일이 아니라 이미지에 굳어 있는 사본을 실행합니다.",
        "이 상태로 테스트를 돌리면 **레포의 코드가 아닌 옛 코드를 검증**하게 되고,",
        "판정이 통과로 나와도 아무것도 보장하지 않습니다.",
        "",
    ]
    if missing:
        lines.append(f"  이미지에 없음 (추가된 하네스): {', '.join(missing)}")
    if stale:
        lines.append(f"  내용이 다름 (수정된 하네스): {', '.join(stale)}")
    if extra:
        lines.append(f"  이미지에만 있음 (삭제된 하네스): {', '.join(extra)}")
    lines += ["", "다시 빌드하세요:", f"    {build}"]

    pytest.fail("\n".join(lines), pytrace=False)
