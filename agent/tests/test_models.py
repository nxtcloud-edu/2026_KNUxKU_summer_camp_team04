"""`models.get_model()` 프로바이더/모델 스위치 테스트.

실제 클라이언트를 만들지 않는 경로(`MODEL_PROVIDER=none`)와 순수 환경변수
해석 로직(`_for_role`)만 검증한다. 프로바이더 SDK 생성은 API 키가 필요하고
네트워크를 건드릴 수 있으므로 여기서 다루지 않는다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tutor_agent import models  # noqa: E402


def test_provider_none_returns_none(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_PROVIDER", "none")

    assert models.get_model("state") is None


def test_role_specific_provider_wins(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_PROVIDER", "anthropic")
    monkeypatch.setenv("MODEL_PROVIDER_TUTOR_MESSAGE", "none")

    assert models.get_model("tutor_message") is None


def test_unknown_provider_is_a_loud_error(monkeypatch) -> None:
    """조용히 기본값으로 넘어가면 "왜 저 모델을 쓰고 있지?"를 나중에 추적하게 된다."""
    monkeypatch.setenv("MODEL_PROVIDER", "gpt5-turbo-max")

    with pytest.raises(ValueError, match="알 수 없는 MODEL_PROVIDER"):
        models.get_model("state")


# --- 역할별 모델 id (_for_role) -----------------------------------------------


def test_for_role_prefers_the_role_specific_value(monkeypatch) -> None:
    """작문 단계만 더 작은 모델로 내리는 것이 이 함수의 목적이다."""
    # .env가 이제 ANTHROPIC_MODEL_ID_STATE 등을 실제로 설정해 두므로, 이 값이
    # 테스트에 새어 들어와 "state는 공통값을 따른다"는 기대를 깨지 않도록 지운다.
    monkeypatch.delenv("ANTHROPIC_MODEL_ID_STATE", raising=False)
    monkeypatch.setenv("ANTHROPIC_MODEL_ID", "claude-sonnet-4-5")
    monkeypatch.setenv("ANTHROPIC_MODEL_ID_TUTOR_MESSAGE", "claude-haiku-4-5")

    assert models._for_role("ANTHROPIC_MODEL_ID", "tutor_message", "x") == "claude-haiku-4-5"
    assert models._for_role("ANTHROPIC_MODEL_ID", "state", "x") == "claude-sonnet-4-5"


def test_for_role_falls_back_to_the_shared_value_then_the_default(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_MODEL_ID", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL_ID_STATE", raising=False)

    assert models._for_role("ANTHROPIC_MODEL_ID", "state", "기본값") == "기본값"

    monkeypatch.setenv("ANTHROPIC_MODEL_ID", "공통값")
    assert models._for_role("ANTHROPIC_MODEL_ID", "state", "기본값") == "공통값"


def test_for_role_uppercases_the_role(monkeypatch) -> None:
    """role 문자열은 소문자(`tutor_message`)지만 환경변수는 대문자 관례를 따른다."""
    monkeypatch.setenv("SOME_VAR_GUIDED_ACTION", "값")

    assert models._for_role("SOME_VAR", "guided_action", "기본값") == "값"
