from __future__ import annotations

import pytest
from src.core.services.tool_identity_resolver import ToolIdentityResolver


@pytest.fixture()
def resolver() -> ToolIdentityResolver:
    return ToolIdentityResolver()


def test_scan_for_pytest_detects_input_string(
    resolver: ToolIdentityResolver,
) -> None:
    arguments = {"input": "pytest -q"}

    result = resolver.scan_for_pytest(tool_name="bash", arguments=arguments)

    assert result == "pytest -q"


def test_scan_for_pytest_handles_mixed_case_tool_name(
    resolver: ToolIdentityResolver,
) -> None:
    """Ensure detection works when the tool name uses different casing."""

    arguments = "pytest --maxfail=1"

    result = resolver.scan_for_pytest(tool_name="Bash", arguments=arguments)

    assert result == "pytest --maxfail=1"
