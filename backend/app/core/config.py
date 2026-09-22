"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global configuration settings for the application."""

    # AWS Credentials & Region
    aws_region: str = "us-east-1"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None

    # AWS Bedrock
    bedrock_model_id: str = "us.amazon.nova-2-lite-v1:0"
    bedrock_thinking_effort: str = "low"

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

    # Environment
    app_env: str = "development"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Retrieve cached singleton Settings instance."""
    return Settings()
