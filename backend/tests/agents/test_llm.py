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
    assert llm.temperature is None
    assert llm.additional_model_request_fields == {
        "reasoningConfig": {"type": "enabled", "maxReasoningEffort": "low"}
    }


@pytest.mark.parametrize(
    "effort, expected_effort",
    [
        ("medium", "medium"),
        ("high", "high"),
        ("LOW", "low"),
        ("Medium", "medium"),
        ("HIGH", "high"),
    ],
)
def test_get_bedrock_llm_nova_reasoning_effort_levels(effort: str, expected_effort: str):
    # Arrange
    test_settings = Settings(
        bedrock_model_id="us.amazon.nova-2-lite-v1:0",
        bedrock_thinking_effort=effort,
        _env_file=None,
    )

    # Act
    llm = get_bedrock_llm(settings=test_settings)

    # Assert
    assert llm.temperature is None
    assert llm.additional_model_request_fields == {
        "reasoningConfig": {"type": "enabled", "maxReasoningEffort": expected_effort}
    }


@pytest.mark.parametrize(
    "disabled_effort",
    [None, "", "   ", "disabled", "Disabled", "DISABLED"],
)
def test_get_bedrock_llm_reasoning_disabled_or_empty(disabled_effort: str | None):
    # Arrange
    test_settings = Settings(
        bedrock_model_id="us.amazon.nova-2-lite-v1:0",
        bedrock_thinking_effort=disabled_effort,
        _env_file=None,
    )

    # Act
    llm = get_bedrock_llm(settings=test_settings)

    # Assert: reasoningConfig should be omitted and temperature should be 0.0
    assert llm.temperature == 0.0
    assert (
        llm.additional_model_request_fields is None
        or "reasoningConfig" not in llm.additional_model_request_fields
    )


def test_get_bedrock_llm_non_nova_model_omits_reasoning():
    # Arrange: non-Nova model with thinking effort configured
    test_settings = Settings(
        bedrock_model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
        bedrock_thinking_effort="high",
        _env_file=None,
    )

    # Act
    llm = get_bedrock_llm(settings=test_settings)

    # Assert: reasoningConfig should not be injected for non-Nova models and temperature should be 0.0
    assert llm.temperature == 0.0
    assert (
        llm.additional_model_request_fields is None
        or "reasoningConfig" not in llm.additional_model_request_fields
    )


def test_get_bedrock_llm_caller_additional_fields_precedence():
    # Arrange: Nova model with default effort, but caller explicitly provides additional_model_request_fields
    test_settings = Settings(
        bedrock_model_id="us.amazon.nova-2-lite-v1:0",
        bedrock_thinking_effort="low",
        _env_file=None,
    )
    custom_fields = {"customKey": "customValue"}

    # Act
    llm = get_bedrock_llm(
        settings=test_settings,
        additional_model_request_fields=custom_fields,
    )

    # Assert: caller's custom fields are preserved without being overwritten
    assert llm.additional_model_request_fields == {"customKey": "customValue"}


def test_get_bedrock_llm_caller_reasoning_config_omits_temperature():
    # Arrange: caller provides reasoningConfig directly
    test_settings = Settings(
        bedrock_model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
        bedrock_thinking_effort="disabled",
        _env_file=None,
    )
    custom_fields = {
        "reasoningConfig": {"type": "enabled", "maxReasoningEffort": "high"}
    }

    # Act
    llm = get_bedrock_llm(
        settings=test_settings,
        temperature=0.7,
        additional_model_request_fields=custom_fields,
    )

    # Assert: temperature must be None because reasoningConfig is enabled
    assert llm.temperature is None
    assert llm.additional_model_request_fields == custom_fields


def test_get_bedrock_llm_custom_temperature_when_reasoning_disabled():
    # Arrange: reasoning effort is disabled and caller supplies custom temperature
    test_settings = Settings(
        bedrock_model_id="us.amazon.nova-2-lite-v1:0",
        bedrock_thinking_effort="disabled",
        _env_file=None,
    )

    # Act
    llm = get_bedrock_llm(settings=test_settings, temperature=0.7)

    # Assert: custom temperature is preserved
    assert llm.temperature == 0.7


def test_get_bedrock_llm_non_nova_model_preserves_custom_temperature():
    # Arrange: non-Nova model with high thinking effort configured
    test_settings = Settings(
        bedrock_model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
        bedrock_thinking_effort="high",
        _env_file=None,
    )

    # Act
    llm = get_bedrock_llm(settings=test_settings, temperature=0.5)

    # Assert: non-Nova models retain temperature even when thinking effort is set
    assert llm.temperature == 0.5


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
