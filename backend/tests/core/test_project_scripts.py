"""Tests verifying Makefile and start.ps1 script interfaces and targets."""

from pathlib import Path
import re
import pytest

ROOT_DIR = Path(__file__).resolve().parents[3]


def test_makefile_targets():
    """Verify Makefile defines expected targets."""
    makefile_path = ROOT_DIR / "Makefile"
    assert makefile_path.exists(), "Makefile not found at repository root"
    content = makefile_path.read_text(encoding="utf-8")

    expected_targets = [
        "help",
        "setup",
        "install",
        "backend",
        "frontend",
        "dev",
        "stop",
        "seed",
        "test",
        "test-offline",
        "test-aws",
        "test-frontend",
        "test-e2e",
        "typecheck",
        "generate-types",
        "build",
        "clean",
    ]

    for target in expected_targets:
        pattern = rf"^{re.escape(target)}:"
        assert re.search(pattern, content, re.MULTILINE), f"Makefile missing target: '{target}'"


def test_start_ps1_modes():
    """Verify start.ps1 defines and handles expected parameter modes."""
    start_ps1_path = ROOT_DIR / "start.ps1"
    assert start_ps1_path.exists(), "start.ps1 not found at repository root"
    content = start_ps1_path.read_text(encoding="utf-8")

    expected_modes = [
        "all",
        "backend",
        "frontend",
        "setup",
        "seed",
        "test",
        "test-backend",
        "test-offline",
        "test-aws",
        "test-frontend",
        "test-e2e",
        "typecheck",
        "generate-types",
        "build",
        "stop",
        "help",
    ]

    # ValidateSet block
    match = re.search(r'\[ValidateSet\((.*?)\)\]', content, re.DOTALL)
    assert match, "ValidateSet not found in start.ps1 param block"
    validate_set_str = match.group(1)

    for mode in expected_modes:
        assert f'"{mode}"' in validate_set_str, f"start.ps1 ValidateSet missing mode '{mode}'"

    # Execution blocks
    for mode in ["setup", "seed", "test", "test-aws", "test-e2e", "typecheck", "generate-types", "build", "stop"]:
        assert f'$Mode -eq "{mode}"' in content or f'$Mode -eq \'{mode}\'' in content, (
            f"start.ps1 missing execution handler for mode: '{mode}'"
        )
