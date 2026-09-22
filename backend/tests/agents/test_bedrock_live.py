"""Live integration tests for AWS Bedrock invocation."""

import os
import pytest

from app.agents.llm import get_bedrock_llm


@pytest.mark.aws
def test_bedrock_live_invocation():
    """Verify live Bedrock model invocation when AWS credentials are configured."""
    if not (
        os.getenv("AWS_ACCESS_KEY_ID")
        or os.getenv("AWS_PROFILE")
        or os.getenv("AWS_DEFAULT_REGION")
    ):
        pytest.skip("AWS credentials not present in environment for live invocation.")

    llm = get_bedrock_llm()
    response = llm.invoke("Hello, reply with one word.")
    assert response is not None
    assert len(response.content) > 0
