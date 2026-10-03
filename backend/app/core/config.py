"""Application configuration using Pydantic Settings."""

from functools import lru_cache
import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Global configuration settings for the application."""

    # AWS Credentials & Region
    aws_region: str = "us-east-1"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None

    # AWS Bedrock
    bedrock_model_id: str = "us.amazon.nova-2-lite-v1:0"
    bedrock_thinking_effort: str | None = "low"

    # AWS DynamoDB
    dynamodb_table_refunds: str = "refund-requests"
    dynamodb_table_orders: str = "mock-orders"
    dynamodb_table_checkpoints: str = "langgraph-checkpoints"
    dynamodb_endpoint_url: str | None = None

    # LangSmith Observability
    langsmith_tracing: bool = False
    langsmith_endpoint: str = "https://eu.api.smith.langchain.com"
    langsmith_api_key: str | None = None
    langsmith_project: str = "refund-request-processor"

    # AWS S3 & Evidence Storage
    s3_bucket_evidence: str = "refund-request-evidence"
    s3_endpoint_url: str | None = None
    local_storage_dir: str = "uploads"

    # AWS SES
    ses_sender_email: str = "noreply@refunds.example.com"

    # Amazon Cognito & OAuth2 JWT
    cognito_user_pool_id: str | None = None
    cognito_client_id: str | None = None
    jwt_secret_key: str = "dev-secret-key-change-in-production"
    auth_require_jwt: bool = False

    # Environment
    app_env: str = "development"

    model_config = SettingsConfigDict(
        env_file=(_BACKEND_DIR / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Retrieve cached singleton Settings instance."""
    return Settings()


def setup_langsmith_environment(settings: Settings | None = None) -> bool:
    """Configure LangSmith tracing environment variables based on application settings.

    When tracing is enabled and a valid API key is present:
    - Populates LANGSMITH_TRACING, LANGCHAIN_TRACING_V2, LANGSMITH_ENDPOINT,
      LANGSMITH_API_KEY, and LANGSMITH_PROJECT in os.environ.
    - Returns True.

    When tracing is disabled or the API key is missing/empty:
    - Disables LANGSMITH_TRACING and LANGCHAIN_TRACING_V2 in os.environ.
    - Returns False.
    """
    if settings is None:
        settings = get_settings()

    api_key = settings.langsmith_api_key
    has_valid_api_key = bool(api_key and api_key.strip())

    if settings.langsmith_tracing and has_valid_api_key:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
        os.environ["LANGSMITH_API_KEY"] = api_key
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
        return True

    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    return False

