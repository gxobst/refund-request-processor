"""Live integration tests for AWS Bedrock invocation."""

import os
import boto3
import pytest

from app.agents.llm import get_bedrock_llm
from app.core.config import get_settings


def _has_aws_credentials() -> bool:
    """Check if environment has AWS credentials configured."""
    settings = get_settings()
    if settings.aws_access_key_id or os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("AWS_PROFILE"):
        return True
    try:
        session = boto3.Session()
        credentials = session.get_credentials()
        return credentials is not None and credentials.access_key is not None
    except Exception:
        return False


@pytest.mark.aws
def test_bedrock_live_invocation():
    """Verify live Bedrock model invocation when AWS credentials are configured."""
    if not _has_aws_credentials():
        pytest.skip("AWS credentials not present in environment for live invocation.")

    llm = get_bedrock_llm()
    response = llm.invoke("Hello, reply with one word.")
    assert response is not None
    assert len(response.content) > 0
