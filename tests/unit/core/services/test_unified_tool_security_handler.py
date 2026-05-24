"""
Tests for Unified Tool Security Handler.

These tests verify the unified security framework that combines dangerous command
detection and file sandboxing into a single, efficient handler.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.configuration.unified_security_config import (
    DangerousCommandRuleConfig,
    DangerousCommandsConfig,
    FileSandboxingConfig,
    LoopPreventionConfig,
    UnifiedSecurityConfig,
)
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.core.services.command_extraction_service import CommandExtractionService
from src.core.services.path_validation_service import PathValidationService
from src.core.services.unified_tool_security_handler import (
    DangerousCommandCheck,
    FileSandboxingCheck,
    UnifiedToolSecurityHandler,
)

# =============================================================================
# Command Extraction Service Tests
# =============================================================================


class TestCommandExtractionService:
    """Tests for shared command extraction functionality."""

    def test_extract_command_from_string(self) -> None:
        """Should extract command from raw string."""
        service = CommandExtractionService()
        result = service.extract_command_string("git reset --hard")
        assert result == "git reset --hard"

    def test_extract_command_from_json_string(self) -> None:
        """Should extract command from JSON string."""
        service = CommandExtractionService()
        result = service.extract_command_string('{"command": "rm -rf /tmp"}')
        assert result == "rm -rf /tmp"

    def test_extract_command_from_dict(self) -> None:
        """Should extract command from dictionary."""
        service = CommandExtractionService()
        result = service.extract_command_string({"command": "git push --force"})
        assert result == "git push --force"

    def test_extract_command_from_nested_dict(self) -> None:
        """Should extract command from nested input structure."""
        service = CommandExtractionService()
        result = service.extract_command_string({"input": {"command": "git clean -fd"}})
        assert result == "git clean -fd"

    def test_normalize_command_strips_env_prefix(self) -> None:
        """Should strip environment variable prefixes."""
        service = CommandExtractionService()
        result = service.normalize_command("FOO=bar BAZ=qux git reset --hard")
        assert "git reset --hard" in result

    def test_normalize_command_collapses_whitespace(self) -> None:
        """Should collapse multiple whitespace."""
        service = CommandExtractionService()
        result = service.normalize_command("git   reset    --hard")
        assert result == "git reset --hard"

    def test_is_shell_tool_matches_patterns(self) -> None:
        """Should identify shell tools by pattern."""
        service = CommandExtractionService()
        assert service.is_shell_tool("bash") is True
        assert service.is_shell_tool("execute_command") is True
        assert service.is_shell_tool("run_shell_command") is True
        assert service.is_shell_tool("local_shell") is True

    def test_is_shell_tool_no_match(self) -> None:
        """Should not match non-shell tools."""
        service = CommandExtractionService()
        assert service.is_shell_tool("write_file") is False
        assert service.is_shell_tool("read_content") is False

    def test_extract_paths_from_command(self) -> None:
        """Should extract file paths from shell commands."""
        service = CommandExtractionService()
        paths = service.extract_paths_from_command("rm -rf /tmp/dangerous")
        assert "/tmp/dangerous" in paths

    def test_extract_paths_from_windows_cd_command(self) -> None:
        """Should extract Windows paths from cd command (single backslashes)."""
        service = CommandExtractionService()
        # Windows paths use single backslashes
        paths = service.extract_paths_from_command(
            r"cd C:\Users\Test\project ; git diff"
        )
        # The cd pattern should extract the path
        assert r"C:\Users\Test\project" in paths

    def test_extract_paths_does_not_match_relative_paths(self) -> None:
        """Should NOT extract Unix-style relative paths like ./.venv/..."""
        service = CommandExtractionService()
        # Relative path starting with ./ should not be treated as absolute
        paths = service.extract_paths_from_command(
            r"./.venv/Scripts/python.exe -m pytest"
        )
        assert "/.venv/Scripts/python.exe" not in paths
        # Only explicit rm -rf etc patterns should extract paths
        assert len(paths) == 0

    def test_extract_paths_handles_unc_paths(self) -> None:
        """Should extract UNC paths from commands."""
        service = CommandExtractionService()
        paths = service.extract_paths_from_command(r"cd \\server\share\folder")
        # UNC paths should be extracted
        assert any("server" in p for p in paths)

    def test_extract_paths_does_not_match_pytest_nodeid_suffix(self) -> None:
        """Should NOT treat `.py::Test...` as a Windows drive (false positive)."""
        service = CommandExtractionService()
        paths = service.extract_paths_from_command(
            "./.venv/Scripts/python.exe -m pytest "
            "tests/property/core/test_backend_lifecycle_manager_properties.py::"
            "TestBackendCacheLRUProperty::test_lru_eviction_on_limit -v"
        )
        assert not paths

    def test_truncates_long_commands(self) -> None:
        """Should truncate commands exceeding max length."""
        service = CommandExtractionService(max_command_length=10)
        result = service.extract_command_string("short" * 100)
        assert result is not None
        assert len(result) == 10


# =============================================================================
# Dangerous Command Check Tests
# =============================================================================


class TestDangerousCommandCheck:
    """Tests for dangerous command detection."""

    @pytest.fixture
    def config(self) -> DangerousCommandsConfig:
        return DangerousCommandsConfig(
            enabled=True,
            use_builtin_rules=True,
        )

    @pytest.fixture
    def check(self, config: DangerousCommandsConfig) -> DangerousCommandCheck:
        return DangerousCommandCheck(config)

    @pytest.fixture
    def command_service(self) -> CommandExtractionService:
        return CommandExtractionService()

    def _make_context(self, tool_name: str, arguments: dict | str) -> ToolCallContext:
        return ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name=tool_name,
            tool_arguments=arguments if isinstance(arguments, dict) else {},
            calling_agent=None,
        )

    @pytest.mark.asyncio
    async def test_blocks_git_reset_hard(
        self, check: DangerousCommandCheck, command_service: CommandExtractionService
    ) -> None:
        """Should block git reset --hard commands."""
        context = self._make_context("bash", {"command": "git reset --hard"})
        result = await check.check(context, command_service)
        assert result.blocked is True
        assert "git_reset_hard" in result.reason

    @pytest.mark.asyncio
    async def test_blocks_git_push_force(
        self, check: DangerousCommandCheck, command_service: CommandExtractionService
    ) -> None:
        """Should block git push --force commands."""
        context = self._make_context(
            "bash", {"command": "git push origin main --force"}
        )
        result = await check.check(context, command_service)
        assert result.blocked is True
        assert "git_push_force" in result.reason

    @pytest.mark.asyncio
    async def test_blocks_rm_rf(
        self, check: DangerousCommandCheck, command_service: CommandExtractionService
    ) -> None:
        """Should block rm -rf commands."""
        context = self._make_context("Execute", {"command": "rm -rf /tmp/test"})
        result = await check.check(context, command_service)
        assert result.blocked is True
        assert "rm" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_allows_safe_git_commands(
        self, check: DangerousCommandCheck, command_service: CommandExtractionService
    ) -> None:
        """Should allow safe git commands."""
        context = self._make_context("bash", {"command": "git status"})
        result = await check.check(context, command_service)
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_ignores_non_shell_tools(
        self, check: DangerousCommandCheck, command_service: CommandExtractionService
    ) -> None:
        """Should ignore tools not in the monitored list."""
        context = self._make_context("write_file", {"command": "git reset --hard"})
        result = await check.check(context, command_service)
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_disabled_check_allows_all(
        self, command_service: CommandExtractionService
    ) -> None:
        """Disabled check should allow everything."""
        config = DangerousCommandsConfig(enabled=False)
        check = DangerousCommandCheck(config)
        context = self._make_context("bash", {"command": "git reset --hard"})
        result = await check.check(context, command_service)
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_custom_rule(self, command_service: CommandExtractionService) -> None:
        """Should support custom rules."""
        config = DangerousCommandsConfig(
            enabled=True,
            use_builtin_rules=False,
            rules=[
                DangerousCommandRuleConfig(
                    name="custom_danger",
                    pattern=r"danger\s+command",
                    description="Test custom rule",
                )
            ],
        )
        check = DangerousCommandCheck(config)
        context = self._make_context("bash", {"command": "danger command here"})
        result = await check.check(context, command_service)
        assert result.blocked is True
        assert "custom_danger" in result.reason


class TestDangerousCommandProjectRootProtection:
    """Tests for project root integrity protection."""

    @pytest.fixture
    def config(self) -> DangerousCommandsConfig:
        return DangerousCommandsConfig(enabled=True)

    @pytest.fixture
    def session_service(self) -> AsyncMock:
        service = AsyncMock()
        session = MagicMock()
        session.state.project_dir = r"C:\Users\User\Project"
        service.get_session.return_value = session
        return service

    @pytest.fixture
    def check(
        self, config: DangerousCommandsConfig, session_service: AsyncMock
    ) -> DangerousCommandCheck:
        return DangerousCommandCheck(config, session_service)

    @pytest.fixture
    def command_service(self) -> CommandExtractionService:
        return CommandExtractionService()

    def _make_context(self, tool_name: str, arguments: dict | str) -> ToolCallContext:
        return ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name=tool_name,
            tool_arguments=arguments if isinstance(arguments, dict) else {},
            calling_agent=None,
        )

    @pytest.mark.asyncio
    async def test_blocks_mv_project_root(
        self, check: DangerousCommandCheck, command_service: CommandExtractionService
    ) -> None:
        """Should block moving project root."""
        cmd = r"mv C:\Users\User\Project C:\Users\User\Project_Old"
        context = self._make_context("bash", {"command": cmd})
        result = await check.check(context, command_service)
        assert result.blocked is True
        assert "move_project_root" in result.reason

    @pytest.mark.asyncio
    async def test_blocks_rmdir_project_root(
        self, check: DangerousCommandCheck, command_service: CommandExtractionService
    ) -> None:
        """Should block rmdir of project root."""
        cmd = r"rmdir C:\Users\User\Project"
        context = self._make_context("bash", {"command": cmd})
        result = await check.check(context, command_service)
        assert result.blocked is True
        assert "rmdir_project_root" in result.reason

    @pytest.mark.asyncio
    async def test_blocks_git_rm_project_root(
        self, check: DangerousCommandCheck, command_service: CommandExtractionService
    ) -> None:
        """Should block git rm of project root."""
        cmd = r"git rm -r C:\Users\User\Project"
        context = self._make_context("bash", {"command": cmd})
        result = await check.check(context, command_service)
        assert result.blocked is True
        assert "git_rm_project_root" in result.reason

    @pytest.mark.asyncio
    async def test_allows_operations_on_subdirectories(
        self, check: DangerousCommandCheck, command_service: CommandExtractionService
    ) -> None:
        """Should allow operations on subdirectories."""
        cmd = r"mv C:\Users\User\Project\subdir C:\Users\User\Project\subdir2"
        context = self._make_context("bash", {"command": cmd})
        result = await check.check(context, command_service)
        assert result.blocked is False


# =============================================================================
# File Sandboxing Check Tests
# =============================================================================


class TestFileSandboxingCheck:
    """Tests for file sandboxing functionality."""

    @pytest.fixture
    def config(self) -> FileSandboxingConfig:
        return FileSandboxingConfig(
            enabled=True,
            strict_mode=False,
        )

    @pytest.fixture
    def path_validator(self) -> MagicMock:
        validator = MagicMock()
        validator.extract_paths_from_arguments = MagicMock(
            return_value=["/project/file.txt"]
        )
        validator.normalize_path = MagicMock(side_effect=lambda p, _: Path(p))
        validator.is_within_boundary = MagicMock(return_value=True)
        return validator

    @pytest.fixture
    def session_service(self) -> AsyncMock:
        service = AsyncMock()
        session = MagicMock()
        session.state.project_dir = "/project"
        service.get_session.return_value = session
        return service

    @pytest.fixture
    def check(
        self,
        config: FileSandboxingConfig,
        path_validator: MagicMock,
        session_service: AsyncMock,
    ) -> FileSandboxingCheck:
        return FileSandboxingCheck(config, path_validator, session_service)

    @pytest.fixture
    def command_service(self) -> CommandExtractionService:
        return CommandExtractionService()

    def _make_context(self, tool_name: str, arguments: dict | str) -> ToolCallContext:
        return ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name=tool_name,
            tool_arguments=arguments if isinstance(arguments, dict) else {},
            calling_agent=None,
        )

    @pytest.mark.asyncio
    async def test_allows_paths_within_project(
        self,
        check: FileSandboxingCheck,
        command_service: CommandExtractionService,
        path_validator: MagicMock,
    ) -> None:
        """Should allow file operations within project directory."""
        path_validator.is_within_boundary.return_value = True
        context = self._make_context("write_file", {"path": "/project/file.txt"})
        result = await check.check(context, command_service)
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_blocks_paths_outside_project(
        self,
        check: FileSandboxingCheck,
        command_service: CommandExtractionService,
        path_validator: MagicMock,
    ) -> None:
        """Should block file operations outside project directory."""
        path_validator.extract_paths_from_arguments.return_value = ["/etc/passwd"]
        path_validator.is_within_boundary.return_value = False
        context = self._make_context("write_file", {"path": "/etc/passwd"})
        result = await check.check(context, command_service)
        assert result.blocked is True
        assert "outside" in result.reason or "sandbox" in result.reason

    @pytest.mark.asyncio
    async def test_ignores_non_file_tools(
        self,
        check: FileSandboxingCheck,
        command_service: CommandExtractionService,
    ) -> None:
        """Should ignore tools not matching file patterns."""
        context = self._make_context("search_web", {"query": "test"})
        result = await check.check(context, command_service)
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_disabled_check_allows_all(
        self,
        path_validator: MagicMock,
        session_service: AsyncMock,
        command_service: CommandExtractionService,
    ) -> None:
        """Disabled check should allow everything."""
        config = FileSandboxingConfig(enabled=False)
        check = FileSandboxingCheck(config, path_validator, session_service)
        context = self._make_context("write_file", {"path": "/etc/passwd"})
        result = await check.check(context, command_service)
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_blocks_write_via_symlink_escaping_project_root(
        self, command_service: CommandExtractionService, tmp_path: Path
    ) -> None:
        """Resolved path outside project (symlink escape) must be blocked."""
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.txt"
        secret.touch()
        project = tmp_path / "project"
        project.mkdir()
        link = project / "via_link.txt"
        try:
            link.symlink_to(secret)
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks not supported or not permitted on this system")

        config = FileSandboxingConfig(enabled=True, strict_mode=False)
        real_validator = PathValidationService()
        session_service = AsyncMock()
        session = MagicMock()
        session.state.project_dir = str(project)
        session_service.get_session.return_value = session

        check = FileSandboxingCheck(config, real_validator, session_service)
        context = self._make_context("write_file", {"path": "via_link.txt"})
        result = await check.check(context, command_service)
        assert result.blocked is True
        assert result.reason == "path_outside_sandbox"


# =============================================================================
# Unified Security Handler Tests
# =============================================================================


class TestUnifiedToolSecurityHandler:
    """Tests for the unified security handler."""

    @pytest.fixture
    def config(self) -> UnifiedSecurityConfig:
        return UnifiedSecurityConfig(
            enabled=True,
            dangerous_commands=DangerousCommandsConfig(enabled=True),
            file_sandboxing=FileSandboxingConfig(
                enabled=False
            ),  # Only test dangerous commands
        )

    @pytest.fixture
    def handler(self, config: UnifiedSecurityConfig) -> UnifiedToolSecurityHandler:
        return UnifiedToolSecurityHandler(config)

    def _make_context(self, tool_name: str, arguments: dict | str) -> ToolCallContext:
        return ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name=tool_name,
            tool_arguments=arguments if isinstance(arguments, dict) else {},
            calling_agent=None,
        )

    def test_handler_name(self, handler: UnifiedToolSecurityHandler) -> None:
        """Handler should have correct name."""
        assert handler.name == "unified_tool_security_handler"

    def test_handler_priority(self, handler: UnifiedToolSecurityHandler) -> None:
        """Handler should have high priority."""
        assert handler.priority == 100

    @pytest.mark.asyncio
    async def test_can_handle_when_enabled(
        self, handler: UnifiedToolSecurityHandler
    ) -> None:
        """Should be able to handle when enabled."""
        context = self._make_context("bash", {})
        result = await handler.can_handle(context)
        assert result is True

    @pytest.mark.asyncio
    async def test_cannot_handle_when_disabled(self) -> None:
        """Should not handle when disabled."""
        config = UnifiedSecurityConfig(enabled=False)
        handler = UnifiedToolSecurityHandler(config)
        context = self._make_context("bash", {})
        result = await handler.can_handle(context)
        assert result is False

    @pytest.mark.asyncio
    async def test_blocks_dangerous_command(
        self, handler: UnifiedToolSecurityHandler
    ) -> None:
        """Should block dangerous commands."""
        context = self._make_context("bash", {"command": "git reset --hard"})
        result = await handler.handle(context)
        assert result.should_swallow is True
        assert result.replacement_response is not None
        assert "Security Block" in result.replacement_response
        assert result.metadata is not None
        assert result.metadata["handler"] == "unified_tool_security_handler"

    @pytest.mark.asyncio
    async def test_allows_safe_command(
        self, handler: UnifiedToolSecurityHandler
    ) -> None:
        """Should allow safe commands."""
        context = self._make_context("bash", {"command": "git status"})
        result = await handler.handle(context)
        assert result.should_swallow is False

    def test_escalating_messages(self, handler: UnifiedToolSecurityHandler) -> None:
        """Should provide escalating messages for retries."""
        msg1 = handler.get_escalating_message(1)
        msg2 = handler.get_escalating_message(2)
        msg3 = handler.get_escalating_message(3)

        assert "First Warning" in msg1
        assert "SECOND WARNING" in msg2
        assert "FINAL WARNING" in msg3

    def test_terminal_error(self, handler: UnifiedToolSecurityHandler) -> None:
        """Should provide terminal error message."""
        msg = handler.get_terminal_error(4)
        assert "terminated" in msg.lower()
        assert "4" in msg

    def test_is_terminal(self, handler: UnifiedToolSecurityHandler) -> None:
        """Should detect when retry limit exceeded."""
        assert handler.is_terminal(1) is False
        assert handler.is_terminal(3) is False
        assert handler.is_terminal(4) is True


# =============================================================================
# Configuration Tests
# =============================================================================


class TestUnifiedSecurityConfig:
    """Tests for unified security configuration."""

    def test_default_config_has_dangerous_commands_enabled(self) -> None:
        """Default config should have dangerous command detection enabled."""
        config = UnifiedSecurityConfig()
        assert config.enabled is True
        assert config.dangerous_commands.enabled is True
        assert config.file_sandboxing.enabled is False

    def test_is_any_feature_enabled(self) -> None:
        """Should correctly report if any feature is enabled."""
        config = UnifiedSecurityConfig()
        assert config.is_any_feature_enabled() is True

        config2 = UnifiedSecurityConfig(
            dangerous_commands=DangerousCommandsConfig(enabled=False),
            file_sandboxing=FileSandboxingConfig(enabled=False),
        )
        assert config2.is_any_feature_enabled() is False

    def test_custom_rule_validation(self) -> None:
        """Should validate custom rule patterns."""
        # Valid pattern
        rule = DangerousCommandRuleConfig(
            name="test", pattern=r"test\s+pattern", description=""
        )
        assert rule.pattern == r"test\s+pattern"

        # Invalid pattern should raise
        with pytest.raises(ValueError):
            DangerousCommandRuleConfig(name="bad", pattern=r"[invalid(", description="")

    def test_loop_prevention_config(self) -> None:
        """Should configure loop prevention settings."""
        config = UnifiedSecurityConfig(
            loop_prevention=LoopPreventionConfig(
                max_retries=5,
                use_escalating_messages=True,
            )
        )
        assert config.loop_prevention.max_retries == 5
