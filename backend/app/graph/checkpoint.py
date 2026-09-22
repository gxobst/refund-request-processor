"""Checkpointer factory for LangGraph state persistence."""

import boto3
from typing import Any
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from app.core.config import Settings, get_settings


def get_checkpointer(
    use_dynamodb: bool | None = None,
    table_name: str | None = None,
    settings: Settings | None = None,
) -> BaseCheckpointSaver:
    """Return a checkpointer instance (DynamoDB or in-memory fallback).

    Args:
        use_dynamodb: Whether to use real DynamoDB checkpointing. If None,
            resolves to True in non-test environments.
        table_name: DynamoDB table name for checkpoints. Defaults to settings.
        settings: Application Settings instance. Defaults to get_settings().

    Returns:
        Configured BaseCheckpointSaver instance.
    """
    if settings is None:
        settings = get_settings()

    if use_dynamodb is None:
        use_dynamodb = settings.app_env != "test"

    if not use_dynamodb:
        return MemorySaver()

    try:
        from langgraph_checkpoint_aws import DynamoDBSaver

        target_table = (
            table_name
            or settings.dynamodb_table_checkpoints
            or "langgraph-checkpoints"
        )

        session = None
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            session_kwargs: dict[str, Any] = {
                "aws_access_key_id": settings.aws_access_key_id,
                "aws_secret_access_key": settings.aws_secret_access_key,
                "region_name": settings.aws_region,
            }
            if settings.aws_session_token:
                session_kwargs["aws_session_token"] = settings.aws_session_token
            session = boto3.Session(**session_kwargs)

        saver_kwargs: dict[str, Any] = {
            "table_name": target_table,
            "region_name": settings.aws_region,
        }
        if session is not None:
            saver_kwargs["session"] = session
        if settings.dynamodb_endpoint_url:
            saver_kwargs["endpoint_url"] = settings.dynamodb_endpoint_url

        return DynamoDBSaver(**saver_kwargs)
    except Exception:
        # Fall back to MemorySaver if DynamoDB initialization fails
        return MemorySaver()

