"""Unit tests for AWS Bedrock LLM client initialization and factory."""

from langchain_aws import ChatBedrockConverse
import pytest

from app.agents.llm import get_bedrock_llm
from app.core.config import Settings


def test_get_bedrock_llm_defaults():
    # Arrange
    test_settings = Settings(
        aws_region="us-east-1",
        bedrock_model_id="us.amazon.nova-2-lite-v1:0",
        bedrock_thinking_effort="low",
        _env_file=None,
    )

    # Act
    llm = get_bedrock_llm(settings=test_settings)

    # Assert
    assert isinstance(llm, ChatBedrockConverse)
    assert llm.model_id == "us.amazon.nova-2-lite-v1:0"
    assert llm.region_name == "us-east-1"
    assert llm.temperature == 0.0
    assert llm.additional_model_request_fields == {
        "inferenceConfig": {"thinking": {"type": "low"}}
    }


def test_get_bedrock_llm_custom_arguments():
    # Arrange
    test_settings = Settings(
        aws_region="us-east-1",
        bedrock_model_id="us.amazon.nova-2-lite-v1:0",
        _env_file=None,
    )

    # Act
    llm = get_bedrock_llm(
        model_id="custom-model-id-v2",
        region_name="us-west-2",
        temperature=0.5,
        settings=test_settings,
    )

    # Assert
    assert llm.model_id == "custom-model-id-v2"
    assert llm.region_name == "us-west-2"
    assert llm.temperature == 0.5


def test_get_bedrock_llm_with_explicit_credentials():
    # Arrange
    test_settings = Settings(
        aws_region="eu-central-1",
        aws_access_key_id="TEST_KEY_ID",
        aws_secret_access_key="TEST_SECRET",
        aws_session_token="TEST_TOKEN",
        _env_file=None,
    )

    # Act
    llm = get_bedrock_llm(settings=test_settings)

    # Assert
    assert llm.region_name == "eu-central-1"
    # SecretStr in ChatBedrockConverse
    assert llm.aws_access_key_id.get_secret_value() == "TEST_KEY_ID"
    assert llm.aws_secret_access_key.get_secret_value() == "TEST_SECRET"
    assert llm.aws_session_token.get_secret_value() == "TEST_TOKEN"


def test_get_bedrock_llm_passes_extra_kwargs():
    # Arrange
    test_settings = Settings(_env_file=None)

    # Act: pass extra kwargs such as max_tokens
    llm = get_bedrock_llm(settings=test_settings, max_tokens=1024)

    # Assert
    assert llm.max_tokens == 1024
