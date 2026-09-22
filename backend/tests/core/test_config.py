"""Unit tests for application settings and configuration."""

import pytest

from app.core.config import Settings, get_settings


def test_settings_default_values():
    # Arrange & Act: construct settings without env overrides
    settings = Settings(
        _env_file=None,  # ignore any local .env file
    )

    # Assert
    assert settings.aws_region == "us-east-1"
    assert settings.bedrock_model_id == "us.amazon.nova-2-lite-v1:0"
    assert settings.bedrock_thinking_effort == "low"
    assert settings.dynamodb_table_refunds == "refund-requests"
    assert settings.dynamodb_table_orders == "mock-orders"
    assert settings.dynamodb_table_checkpoints == "langgraph-checkpoints"
    assert settings.dynamodb_endpoint_url is None
    assert settings.langsmith_tracing is False
    assert settings.langsmith_endpoint == "https://eu.api.smith.langchain.com"
    assert settings.langsmith_project == "refund-request-processor"
    assert settings.app_env == "development"


def test_settings_custom_environment_variables(monkeypatch: pytest.MonkeyPatch):
    # Arrange: set custom env vars
    monkeypatch.setenv("AWS_REGION", "eu-central-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "custom.nova-model-id")
    monkeypatch.setenv("BEDROCK_THINKING_EFFORT", "high")
    monkeypatch.setenv("DYNAMODB_TABLE_REFUNDS", "custom-refunds-table")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-api-key-12345")
    monkeypatch.setenv("APP_ENV", "production")

    # Act
    settings = Settings(_env_file=None)

    # Assert
    assert settings.aws_region == "eu-central-1"
    assert settings.bedrock_model_id == "custom.nova-model-id"
    assert settings.bedrock_thinking_effort == "high"
    assert settings.dynamodb_table_refunds == "custom-refunds-table"
    assert settings.langsmith_tracing is True
    assert settings.langsmith_api_key == "test-api-key-12345"
    assert settings.app_env == "production"


def test_get_settings_cached_singleton():
    # Arrange & Act
    settings_1 = get_settings()
    settings_2 = get_settings()

    # Assert: verify both return identical cached object
    assert settings_1 is settings_2
