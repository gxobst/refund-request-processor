"""Static policy loader module."""

import json
from pathlib import Path
from app.policy.schema import PolicyConfig

DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent / "data" / "policies.json"


def load_policies(file_path: Path | str | None = None) -> PolicyConfig:
    """Load and validate refund policy configuration from disk.

    Args:
        file_path: Path to the JSON policy file. If None, defaults to app/data/policies.json.

    Returns:
        Validated PolicyConfig instance.

    Raises:
        FileNotFoundError: If the specified policy file does not exist.
        json.JSONDecodeError: If the policy file is not valid JSON.
        pydantic.ValidationError: If the loaded data violates the PolicyConfig schema.
    """
    path = Path(file_path) if file_path is not None else DEFAULT_POLICY_PATH

    if not path.is_file():
        raise FileNotFoundError(f"Policy file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return PolicyConfig.model_validate(data)
