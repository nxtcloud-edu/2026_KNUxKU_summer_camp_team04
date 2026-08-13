"""LLM 프로바이더 스위치.

이 프로젝트는 **로컬 에이전트**입니다 — AWS(Bedrock) 없이, 각자 발급받은 API 키로
Anthropic/OpenAI 등을 직접 호출하는 것을 기본으로 합니다. 아직 어떤 모델을 최종
사용할지는 정해지지 않았으므로, 에이전트 코드(`agents/*.py`)는 `get_model(role)`이
반환하는 값만 받아 `Agent(model=...)`에 넘긴다. `.env`만 바꾸면 Anthropic / OpenAI /
LiteLLM(로컬 Ollama 포함) 중 무엇을 넣어도 나머지 코드는 그대로 동작한다.

`MODEL_PROVIDER`를 아무것도 설정하지 않으면 `DEFAULT_PROVIDER`(anthropic)를 쓴다.
AWS 계정을 쓰기로 팀에서 정하면 `MODEL_PROVIDER=bedrock`으로 옵트인할 수 있다.
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

# .env 파일의 값을 프로세스 환경변수로 로드한다. 이 모듈이 import되는 시점(대개
# get_model()을 처음 호출하기 전)에 한 번 실행되므로, 어떤 진입점(예제 스크립트,
# 테스트, backend 연동 등)에서 시작하든 .env가 자동으로 적용된다. 이미 셸에서
# export된 환경변수는 override하지 않는다.
load_dotenv()

#: MODEL_PROVIDER가 비어 있을 때 쓰는 기본값. "로컬 에이전트" 방침에 따라
#: AWS 자격증명이 필요 없는 Anthropic 다이렉트 API를 기본으로 둔다.
DEFAULT_PROVIDER = "anthropic"


def get_model(role: str = "default") -> Any | None:
    """역할별(role) 모델 프로바이더를 환경변수에서 읽어 Strands Model을 만들어 반환한다.

    Args:
        role: 에이전트 역할 이름 (예: "entry", "state", "guidance", "action", "evaluation").
              `MODEL_PROVIDER_{ROLE}`이 있으면 우선 사용하고, 없으면 공통 `MODEL_PROVIDER`,
              그마저도 없으면 `DEFAULT_PROVIDER`를 따른다.

    Returns:
        Strands `Model` 인스턴스. `MODEL_PROVIDER=none`으로 지정한 경우에만 `None`을
        반환해 Strands 자체 기본 프로바이더(Bedrock, AWS 필요)로 폴백한다.
    """
    provider = (
        os.getenv(f"MODEL_PROVIDER_{role.upper()}")
        or os.getenv("MODEL_PROVIDER")
        or DEFAULT_PROVIDER
    )
    provider = provider.strip().lower()

    if provider == "none":
        return None

    if provider == "anthropic":
        from strands.models.anthropic import AnthropicModel

        # Anthropic Messages API는 max_tokens가 필수 필드라, Strands AnthropicModel도
        # 이 값 없이 생성하면 요청 조립 단계에서 KeyError('max_tokens')를 낸다.
        return AnthropicModel(
            client_args={"api_key": os.getenv("ANTHROPIC_API_KEY")},
            model_id=os.getenv("ANTHROPIC_MODEL_ID", "claude-sonnet-4-5"),
            max_tokens=int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096")),
        )

    if provider == "openai":
        from strands.models.openai import OpenAIModel

        return OpenAIModel(
            client_args={"api_key": os.getenv("OPENAI_API_KEY")},
            model_id=os.getenv("OPENAI_MODEL_ID", "gpt-4o"),
        )

    if provider == "litellm":
        # Ollama 등 완전 로컬 모델도 LiteLLM 경유로 붙일 수 있다.
        # 예: LITELLM_MODEL_ID=ollama/llama3.1
        from strands.models.litellm import LiteLLMModel

        return LiteLLMModel(model_id=os.getenv("LITELLM_MODEL_ID"))

    if provider == "bedrock":
        # AWS 계정을 쓰기로 정했을 때만 선택 (기본값 아님).
        from strands.models import BedrockModel

        return BedrockModel(
            model_id=os.getenv(
                "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0"
            )
        )

    raise ValueError(
        f"알 수 없는 MODEL_PROVIDER='{provider}' (role={role}). "
        "anthropic | openai | litellm | bedrock | none 중 하나를 사용하세요."
    )
