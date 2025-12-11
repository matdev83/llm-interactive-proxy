"""
Unit tests for DroidAntigravityPathFixHandler.

Tests the path fixing functionality for Droid + Gemini Antigravity sessions.
"""

from __future__ import annotations

import pytest
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.core.services.tool_call_handlers.droid_antigravity_path_fix_handler import (
    DroidAntigravityPathFixHandler,
)


class TestDroidAntigravityPathFixHandler:
    """Test suite for DroidAntigravityPathFixHandler."""

    @pytest.fixture
    def enabled_handler(self) -> DroidAntigravityPathFixHandler:
        """Create an enabled handler instance."""
        return DroidAntigravityPathFixHandler(enabled=True)

    @pytest.fixture
    def disabled_handler(self) -> DroidAntigravityPathFixHandler:
        """Create a disabled handler instance."""
        return DroidAntigravityPathFixHandler(enabled=False)

    def _create_context(
        self,
        *,
        calling_agent: str = "Droid",
        backend_name: str = "gemini-oauth-antigravity",
        model_name: str = "gemini-3-pro-high",
        tool_name: str = "Read",
        tool_arguments: dict | str | None = None,
    ) -> ToolCallContext:
        """Create a ToolCallContext for testing."""
        return ToolCallContext(
            session_id="test-session-123",
            backend_name=backend_name,
            model_name=model_name,
            full_response="",
            tool_name=tool_name,
            tool_arguments=tool_arguments or {},
            calling_agent=calling_agent,
        )

    # ==================== can_handle tests ====================

    @pytest.mark.asyncio
    async def test_can_handle_disabled_handler_returns_false(
        self, disabled_handler: DroidAntigravityPathFixHandler
    ) -> None:
        """Disabled handler should never handle anything."""
        context = self._create_context(
            tool_arguments={"file_path": "src/core/config/app_config.py"}
        )
        result = await disabled_handler.can_handle(context)
        assert result is False

    @pytest.mark.asyncio
    async def test_can_handle_matching_session_with_relative_path(
        self, enabled_handler: DroidAntigravityPathFixHandler
    ) -> None:
        """Handler should match when agent is Droid, backend is Antigravity, and path is relative."""
        context = self._create_context(
            calling_agent="Droid",
            backend_name="gemini-oauth-antigravity",
            tool_arguments={"file_path": "src/core/config/app_config.py"},
        )
        result = await enabled_handler.can_handle(context)
        assert result is True, "Should handle matching session with relative path"

    @pytest.mark.asyncio
    async def test_can_handle_case_insensitive_agent_match(
        self, enabled_handler: DroidAntigravityPathFixHandler
    ) -> None:
        """Agent matching should be case-insensitive and substring-based."""
        for agent_name in ["droid", "DROID", "Droid", "MyDroidAgent", "droid-test"]:
            context = self._create_context(
                calling_agent=agent_name,
                tool_arguments={"file_path": "src/file.py"},
            )
            result = await enabled_handler.can_handle(context)
            assert result is True, f"Should match agent name: {agent_name}"

    @pytest.mark.asyncio
    async def test_can_handle_factory_cli_user_agent(
        self, enabled_handler: DroidAntigravityPathFixHandler
    ) -> None:
        """Handler should match factory-cli user agent (Droid's actual User-Agent).

        Droid agent sends User-Agent: factory-cli/X.Y.Z, so we need to detect
        both 'droid' and 'factory' in the agent name.
        """
        factory_agents = [
            "factory-cli/0.35.0",
            "factory-cli/1.0.0",
            "Factory",
            "FACTORY",
            "MyFactoryAgent",
        ]
        for agent_name in factory_agents:
            context = self._create_context(
                calling_agent=agent_name,
                tool_arguments={"file_path": "src/file.py"},
            )
            result = await enabled_handler.can_handle(context)
            assert (
                result is True
            ), f"Should match factory-based agent name: {agent_name}"

    @pytest.mark.asyncio
    async def test_can_handle_non_matching_agent(
        self, enabled_handler: DroidAntigravityPathFixHandler
    ) -> None:
        """Handler should not match non-Droid agents."""
        context = self._create_context(
            calling_agent="Claude",
            tool_arguments={"file_path": "src/file.py"},
        )
        result = await enabled_handler.can_handle(context)
        assert result is False, "Should not match non-Droid agent"

    @pytest.mark.asyncio
    async def test_can_handle_non_matching_backend(
        self, enabled_handler: DroidAntigravityPathFixHandler
    ) -> None:
        """Handler should match even if backend is not Antigravity."""
        context = self._create_context(
            backend_name="openai",
            tool_arguments={"file_path": "src/file.py"},
        )
        result = await enabled_handler.can_handle(context)
        assert result is True, "Should match regardless of backend for Droid agents"

    @pytest.mark.asyncio
    async def test_can_handle_absolute_path_not_needed(
        self, enabled_handler: DroidAntigravityPathFixHandler
    ) -> None:
        """Handler should not match when path is already absolute."""
        context = self._create_context(
            tool_arguments={"file_path": r"\src\core\config\app_config.py"},
        )
        result = await enabled_handler.can_handle(context)
        assert result is False, "Should not match already-absolute path"

    # ==================== handle tests ====================

    @pytest.mark.asyncio
    async def test_handle_fixes_relative_path(
        self, enabled_handler: DroidAntigravityPathFixHandler
    ) -> None:
        """Handler should fix relative paths by prepending backslash and converting slashes."""
        context = self._create_context(
            tool_arguments={"file_path": "src/core/config/app_config.py"},
        )
        result = await enabled_handler.handle(context)

        assert result.should_swallow is False, "Should not swallow the tool call"
        assert context.tool_arguments["file_path"] == r"\src\core\config\app_config.py"

    @pytest.mark.asyncio
    async def test_handle_converts_forward_slashes(
        self, enabled_handler: DroidAntigravityPathFixHandler
    ) -> None:
        """Handler should convert forward slashes to backslashes."""
        context = self._create_context(
            tool_arguments={"file_path": "src/connectors/base.py"},
        )
        await enabled_handler.handle(context)

        assert context.tool_arguments["file_path"] == r"\src\connectors\base.py"

    @pytest.mark.asyncio
    async def test_handle_fixes_root_file_path(
        self, enabled_handler: DroidAntigravityPathFixHandler
    ) -> None:
        """Handler should fix paths without separators (files in root)."""
        context = self._create_context(
            tool_arguments={"file_path": "README.md"},
        )
        await enabled_handler.handle(context)

        assert context.tool_arguments["file_path"] == r"\README.md"

    @pytest.mark.asyncio
    async def test_handle_real_scenario_from_cbor(
        self, enabled_handler: DroidAntigravityPathFixHandler
    ) -> None:
        """Test the exact scenario from CBOR capture: READ (src/core/config/app_config.py)."""
        # This is the exact scenario that fails in production
        context = self._create_context(
            calling_agent="Droid",
            backend_name="gemini-oauth-antigravity",
            model_name="gemini-3-pro-high",
            tool_name="Read",
            tool_arguments={"file_path": "src/core/config/app_config.py"},
        )

        # First verify can_handle returns True
        can_handle = await enabled_handler.can_handle(context)
        assert can_handle is True, "Handler should match this scenario"

        # Then verify handle fixes the path
        result = await enabled_handler.handle(context)
        assert result.should_swallow is False
        assert context.tool_arguments["file_path"] == r"\src\core\config\app_config.py"

    @pytest.mark.asyncio
    async def test_handle_factory_cli_scenario_from_production(
        self, enabled_handler: DroidAntigravityPathFixHandler
    ) -> None:
        """Test the exact scenario that failed in production with factory-cli User-Agent.

        From production logs:
        - User-Agent: factory-cli/0.35.0
        - Path: tests/unit/services/test_steering_leak_protection.py (relative)
        - Expected: Should be fixed to \\tests\\unit\\services\\test_steering_leak_protection.py

        This test verifies the fix for the bug where Droid's actual User-Agent
        (factory-cli/X.Y.Z) wasn't being recognized.
        """
        context = self._create_context(
            calling_agent="factory-cli/0.35.0",  # Actual User-Agent from production
            backend_name="gemini-oauth-antigravity",
            model_name="gemini-3-pro-high",
            tool_name="Read",
            tool_arguments={
                "file_path": "tests/unit/services/test_steering_leak_protection.py"
            },
        )

        # Verify can_handle returns True for factory-cli
        can_handle = await enabled_handler.can_handle(context)
        assert can_handle is True, "Handler should match factory-cli/0.35.0 agent"

        # Verify handle fixes the path
        result = await enabled_handler.handle(context)
        assert result.should_swallow is False
        assert (
            context.tool_arguments["file_path"]
            == r"\tests\unit\services\test_steering_leak_protection.py"
        )

    # ==================== Internal method tests ====================

    def test_needs_path_fix_relative_path(
        self, enabled_handler: DroidAntigravityPathFixHandler
    ) -> None:
        """Relative paths need fixing."""
        assert enabled_handler._needs_path_fix("src/file.py") is True
        assert enabled_handler._needs_path_fix("scripts/test.py") is True
        assert enabled_handler._needs_path_fix("README.md") is True
        assert enabled_handler._needs_path_fix("pyproject.toml") is True

    def test_needs_path_fix_absolute_path(
        self, enabled_handler: DroidAntigravityPathFixHandler
    ) -> None:
        """Absolute paths don't need fixing."""
        assert enabled_handler._needs_path_fix(r"\src\file.py") is False
        assert enabled_handler._needs_path_fix("/src/file.py") is False
        assert enabled_handler._needs_path_fix("C:\\Users\\file.py") is False

    def test_fix_path_transforms_correctly(
        self, enabled_handler: DroidAntigravityPathFixHandler
    ) -> None:
        """Path fix should prepend backslash and convert slashes."""
        assert enabled_handler._fix_path("src/file.py") == r"\src\file.py"
        assert enabled_handler._fix_path("src/core/config.py") == r"\src\core\config.py"
        assert enabled_handler._fix_path("README.md") == r"\README.md"
        assert enabled_handler._fix_path("pyproject.toml") == r"\pyproject.toml"

    def test_extract_path_from_dict(
        self, enabled_handler: DroidAntigravityPathFixHandler
    ) -> None:
        """Should extract path from dict with various key names."""
        assert enabled_handler._extract_path({"file_path": "test.py"}) == "test.py"
        assert enabled_handler._extract_path({"path": "test.py"}) == "test.py"
        assert enabled_handler._extract_path({"AbsolutePath": "test.py"}) == "test.py"

    def test_extract_path_from_string(
        self, enabled_handler: DroidAntigravityPathFixHandler
    ) -> None:
        """Should extract path from string argument."""
        assert enabled_handler._extract_path("test.py") == "test.py"
