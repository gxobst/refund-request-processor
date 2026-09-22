"""Checkpointer factory for LangGraph state persistence."""

import os
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver


def get_checkpointer(
    use_dynamodb: bool = False,
    table_name: str | None = None,
) -> BaseCheckpointSaver:
    """Return a checkpointer instance (DynamoDB or in-memory fallback).

    Args:
        use_dynamodb: Whether to use real DynamoDB checkpointing.
        table_name: DynamoDB table name for checkpoints. Defaults to env var.

    Returns:
        Configured BaseCheckpointSaver instance.
    """
    if use_dynamodb:
        try:
            from langgraph_checkpoint_aws import DynamoDBSaver

            target_table = (
                table_name
                or os.getenv("DYNAMODB_TABLE_CHECKPOINTS")
                or "langgraph-checkpoints"
            )
            return DynamoDBSaver(table_name=target_table)
        except Exception:
            # Fall back to MemorySaver if DynamoDB initialization fails
            return MemorySaver()

    return MemorySaver()
