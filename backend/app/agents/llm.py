"""AWS Bedrock LLM client initialization and factory."""

from typing import Any
from langchain_aws import ChatBedrockConverse

from app.core.config import Settings, get_settings


def get_bedrock_llm(
    model_id: str | None = None,
    region_name: str | None = None,
    temperature: float = 0.0,
    settings: Settings | None = None,
    **kwargs: Any,
) -> ChatBedrockConverse:
    """Instantiate and configure a ChatBedrockConverse LLM client.

    Args:
        model_id: AWS Bedrock model identifier. Defaults to settings.bedrock_model_id.
        region_name: AWS region. Defaults to settings.aws_region.
        temperature: Sampling temperature for model output. Defaults to 0.0.
        settings: Optional custom Settings instance. Defaults to cached get_settings().
        **kwargs: Additional parameters passed to ChatBedrockConverse.

    Returns:
        Configured ChatBedrockConverse instance.
    """
    app_settings = settings or get_settings()

    target_model_id = model_id or app_settings.bedrock_model_id
    target_region = region_name or app_settings.aws_region

    params: dict[str, Any] = {
        "model_id": target_model_id,
        "region_name": target_region,
    }

    # Pass explicit credentials if defined in settings
    if app_settings.aws_access_key_id and app_settings.aws_secret_access_key:
        params["aws_access_key_id"] = app_settings.aws_access_key_id
        params["aws_secret_access_key"] = app_settings.aws_secret_access_key
        if app_settings.aws_session_token:
            params["aws_session_token"] = app_settings.aws_session_token

    # Detect if reasoningConfig is enabled:
    # (a) Caller provides additional_model_request_fields containing reasoningConfig with type == "enabled"
    caller_fields = kwargs.get("additional_model_request_fields")
    caller_reasoning_enabled = (
        isinstance(caller_fields, dict)
        and caller_fields.get("reasoningConfig", {}).get("type") == "enabled"
    )

    # (b) Model is an Amazon Nova model and bedrock_thinking_effort is non-empty and not "disabled"
    is_nova = "nova" in target_model_id.lower()
    effort = (app_settings.bedrock_thinking_effort or "").strip()
    nova_reasoning_enabled = (
        is_nova
        and bool(effort)
        and effort.lower() != "disabled"
    )

    reasoning_enabled = caller_reasoning_enabled or nova_reasoning_enabled

    if reasoning_enabled:
        # Amazon Bedrock rejects requests containing temperature when reasoningConfig is enabled
        kwargs.pop("temperature", None)
        if "additional_model_request_fields" not in kwargs:
            params["additional_model_request_fields"] = {
                "reasoningConfig": {
                    "type": "enabled",
                    "maxReasoningEffort": effort.lower(),
                }
            }
    else:
        params["temperature"] = kwargs.pop("temperature", temperature)

    # Override/merge with explicit user kwargs
    params.update(kwargs)

    return ChatBedrockConverse(**params)
