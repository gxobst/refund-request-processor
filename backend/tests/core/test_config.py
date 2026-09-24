import os
import pytest

from app.core.config import Settings, get_settings, setup_langsmith_environment


def test_settings_default_values(monkeypatch: pytest.MonkeyPatch):
    # Ensure environment variables are isolated for default value testing
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_ENDPOINT", raising=False)
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    monkeypatch.delenv("BEDROCK_THINKING_EFFORT", raising=False)
    monkeypatch.delenv("DYNAMODB_TABLE_REFUNDS", raising=False)
    monkeypatch.delenv("DYNAMODB_TABLE_ORDERS", raising=False)
    monkeypatch.delenv("DYNAMODB_TABLE_CHECKPOINTS", raising=False)
    monkeypatch.delenv("DYNAMODB_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("S3_BUCKET_EVIDENCE", raising=False)
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("LOCAL_STORAGE_DIR", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

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
    assert settings.s3_bucket_evidence == "refund-request-evidence"
    assert settings.s3_endpoint_url is None
    assert settings.local_storage_dir == "uploads"
    assert settings.app_env == "development"


def test_settings_custom_environment_variables(monkeypatch: pytest.MonkeyPatch):
    # Arrange: set custom env vars
    monkeypatch.setenv("AWS_REGION", "eu-central-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "custom.nova-model-id")
    monkeypatch.setenv("BEDROCK_THINKING_EFFORT", "high")
    monkeypatch.setenv("DYNAMODB_TABLE_REFUNDS", "custom-refunds-table")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-api-key-12345")
    monkeypatch.setenv("S3_BUCKET_EVIDENCE", "custom-evidence-bucket")
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://localhost:9000")
    monkeypatch.setenv("LOCAL_STORAGE_DIR", "custom_uploads")
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
    assert settings.s3_bucket_evidence == "custom-evidence-bucket"
    assert settings.s3_endpoint_url == "http://localhost:9000"
    assert settings.local_storage_dir == "custom_uploads"
    assert settings.app_env == "production"


def test_get_settings_cached_singleton():
    # Arrange & Act
    settings_1 = get_settings()
    settings_2 = get_settings()

    # Assert: verify both return identical cached object
    assert settings_1 is settings_2


def test_setup_langsmith_environment_enabled(monkeypatch: pytest.MonkeyPatch):
    # Arrange
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    monkeypatch.delenv("LANGSMITH_ENDPOINT", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)

    settings = Settings(
        langsmith_tracing=True,
        langsmith_api_key="lsv2_pt_test_key_12345",
        langsmith_endpoint="https://eu.api.smith.langchain.com",
        langsmith_project="custom-langsmith-project",
        _env_file=None,
    )

    # Act
    enabled = setup_langsmith_environment(settings)

    # Assert
    assert enabled is True
    assert os.environ.get("LANGSMITH_TRACING") == "true"
    assert os.environ.get("LANGCHAIN_TRACING_V2") == "true"
    assert os.environ.get("LANGSMITH_ENDPOINT") == "https://eu.api.smith.langchain.com"
    assert os.environ.get("LANGSMITH_API_KEY") == "lsv2_pt_test_key_12345"
    assert os.environ.get("LANGSMITH_PROJECT") == "custom-langsmith-project"


def test_setup_langsmith_environment_disabled(monkeypatch: pytest.MonkeyPatch):
    # Arrange: preexisting enabled flags should be overridden to false
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")

    settings = Settings(
        langsmith_tracing=False,
        langsmith_api_key="lsv2_pt_test_key_12345",
        _env_file=None,
    )

    # Act
    enabled = setup_langsmith_environment(settings)

    # Assert
    assert enabled is False
    assert os.environ.get("LANGSMITH_TRACING") == "false"
    assert os.environ.get("LANGCHAIN_TRACING_V2") == "false"


@pytest.mark.parametrize("invalid_key", [None, "", "   "])
def test_setup_langsmith_environment_missing_or_empty_key(
    monkeypatch: pytest.MonkeyPatch, invalid_key: str | None
):
    # Arrange: preexisting enabled flags should be overridden to false
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")

    settings = Settings(
        langsmith_tracing=True,
        langsmith_api_key=invalid_key,
        _env_file=None,
    )

    # Act
    enabled = setup_langsmith_environment(settings)

    # Assert
    assert enabled is False
    assert os.environ.get("LANGSMITH_TRACING") == "false"
    assert os.environ.get("LANGCHAIN_TRACING_V2") == "false"


def test_setup_langsmith_environment_resolves_get_settings_when_none(monkeypatch: pytest.MonkeyPatch):
    # Arrange: mock get_settings to return isolated dummy settings
    dummy_settings = Settings(
        langsmith_tracing=True,
        langsmith_api_key="lsv2_default_test_key",
        langsmith_endpoint="https://eu.api.smith.langchain.com",
        langsmith_project="default-test-project",
        _env_file=None,
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: dummy_settings)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)

    # Act
    enabled = setup_langsmith_environment(None)

    # Assert
    assert enabled is True
    assert os.environ.get("LANGSMITH_TRACING") == "true"
    assert os.environ.get("LANGCHAIN_TRACING_V2") == "true"
    assert os.environ.get("LANGSMITH_ENDPOINT") == "https://eu.api.smith.langchain.com"
    assert os.environ.get("LANGSMITH_API_KEY") == "lsv2_default_test_key"
    assert os.environ.get("LANGSMITH_PROJECT") == "default-test-project"

