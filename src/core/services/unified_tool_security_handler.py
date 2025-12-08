"""
Unified Tool Security Handler.

This module provides a single, consolidated handler for all tool call security
features including dangerous command detection and file sandboxing. It uses a
pluggable architecture to run multiple security checks in a single pass.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.core.domain.configuration.unified_security_config import (
    DangerousCommandsConfig,
    FileSandboxingConfig,
    UnifiedSecurityConfig,
)
from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    ToolCallContext,
    ToolCallReactionResult,
)
from src.core.services.command_extraction_service import CommandExtractionService

if TYPE_CHECKING:
    from src.core.interfaces.path_validator_interface import IPathValidator
    from src.core.interfaces.session_service_interface import ISessionService

logger = logging.getLogger(__name__)


# =============================================================================
# Security Check Protocol
# =============================================================================


class SecurityCheckResult:
    """Result from a security check."""

    __slots__ = ("blocked", "reason", "message", "metadata")

    def __init__(
        self,
        blocked: bool = False,
        reason: str = "",
        message: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.blocked = blocked
        self.reason = reason
        self.message = message
        self.metadata = metadata or {}

    @classmethod
    def allow(cls) -> SecurityCheckResult:
        """Create an allow result."""
        return cls(blocked=False)

    @classmethod
    def block(
        cls, reason: str, message: str, metadata: dict[str, Any] | None = None
    ) -> SecurityCheckResult:
        """Create a block result."""
        return cls(blocked=True, reason=reason, message=message, metadata=metadata)


class ISecurityCheck(ABC):
    """Interface for pluggable security checks."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this security check."""
        ...

    @property
    @abstractmethod
    def enabled(self) -> bool:
        """Whether this check is active."""
        ...

    @abstractmethod
    async def check(
        self,
        context: ToolCallContext,
        command_service: CommandExtractionService,
    ) -> SecurityCheckResult:
        """Perform the security check.

        Args:
            context: Tool call context.
            command_service: Shared command extraction service.

        Returns:
            SecurityCheckResult indicating whether to block.
        """
        ...


# =============================================================================
# Dangerous Command Security Check
# =============================================================================


class DangerousCommandCheck(ISecurityCheck):
    """Security check for dangerous/destructive commands."""

    # Built-in dangerous command patterns
    _BUILTIN_PATTERNS: tuple[tuple[str, str, str], ...] = (
        # Git destructive commands
        (
            "git_reset_hard",
            r"git\s+reset\s+--hard(?:\s|$)",
            "Hard reset discards all uncommitted changes",
        ),
        (
            "git_clean_force",
            r"git\s+clean\s+-[a-z]*f[a-z]*(?:\s|$)",
            "Force clean removes untracked files permanently",
        ),
        (
            "git_push_force",
            r"git\s+push\s+.*(?:--force|-f)(?:\s|$)",
            "Force push can overwrite remote history",
        ),
        (
            "git_checkout_force",
            r"git\s+checkout\s+.*(?:--force|-f)(?:\s|$)",
            "Force checkout can overwrite local changes",
        ),
        (
            "git_branch_delete_force",
            r"git\s+branch\s+-[a-z]*D[a-z]*(?:\s|$)",
            "Force delete branch ignores unmerged changes",
        ),
        (
            "git_stash_drop",
            r"git\s+stash\s+(?:drop|clear)(?:\s|$)",
            "Drops stashed changes permanently",
        ),
        # Unix destructive commands
        (
            "rm_recursive_force",
            r"rm\s+-[a-z]*r[a-z]*f[a-z]*\s",
            "Recursive force delete can remove entire directories",
        ),
        (
            "rm_force_recursive",
            r"rm\s+-[a-z]*f[a-z]*r[a-z]*\s",
            "Force recursive delete can remove entire directories",
        ),
        # Windows destructive commands
        (
            "windows_rmdir_recursive",
            r"(?:rmdir|rd)\s+/s\s+/q\s",
            "Windows recursive delete with quiet mode",
        ),
        (
            "windows_del_recursive",
            r"del\s+/s\s+/q\s",
            "Windows recursive delete with quiet mode",
        ),
        (
            "powershell_remove_recurse",
            r"Remove-Item\s+.*-Recurse.*-Force",
            "PowerShell recursive force delete",
        ),
    )

    def __init__(self, config: DangerousCommandsConfig) -> None:
        """Initialize the dangerous command check.

        Args:
            config: Configuration for dangerous command detection.
        """
        self._config = config
        self._enabled = config.enabled
        self._tool_names: set[str] = {n.lower() for n in config.tool_names}

        # Compile all patterns
        self._compiled_patterns: list[tuple[str, re.Pattern[str], str]] = []

        # Add built-in patterns
        if config.use_builtin_rules:
            for name, pattern, desc in self._BUILTIN_PATTERNS:
                try:
                    compiled = re.compile(pattern, re.IGNORECASE)
                    self._compiled_patterns.append((name, compiled, desc))
                except re.error:
                    logger.warning(f"Failed to compile built-in pattern: {name}")

        # Add custom rules
        for rule in config.rules:
            if rule.enabled:
                try:
                    compiled = re.compile(rule.pattern, re.IGNORECASE)
                    self._compiled_patterns.append(
                        (rule.name, compiled, rule.description)
                    )
                except re.error:
                    logger.warning(f"Failed to compile custom pattern: {rule.name}")

    @property
    def name(self) -> str:
        return "dangerous_command_check"

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def check(
        self,
        context: ToolCallContext,
        command_service: CommandExtractionService,
    ) -> SecurityCheckResult:
        """Check if tool call contains a dangerous command."""
        if not self._enabled:
            return SecurityCheckResult.allow()

        tool_name = context.tool_name or ""
        if tool_name.lower() not in self._tool_names:
            return SecurityCheckResult.allow()

        # Extract command string
        command = command_service.extract_command_string(context.tool_arguments)
        if not command:
            return SecurityCheckResult.allow()

        # Normalize for matching
        normalized = command_service.normalize_command(command)

        # Check against patterns
        for rule_name, pattern, description in self._compiled_patterns:
            if pattern.search(normalized):
                logger.warning(
                    "Dangerous command detected: rule=%s, command='%s'",
                    rule_name,
                    command[:200],
                )
                return SecurityCheckResult.block(
                    reason=f"dangerous_command:{rule_name}",
                    message=self._build_block_message(rule_name, command, description),
                    metadata={
                        "check": self.name,
                        "rule": rule_name,
                        "command": command[:500],
                        "description": description,
                    },
                )

        return SecurityCheckResult.allow()

    def _build_block_message(
        self, rule_name: str, command: str, description: str
    ) -> str:
        """Build the block message for a dangerous command."""
        return (
            f"[Security Block: Dangerous Command]\n\n"
            f"The command '{command[:100]}...' was blocked because it matches "
            f"the '{rule_name}' security rule.\n\n"
            f"Reason: {description}\n\n"
            f"If this command is necessary, please inform the user that they "
            f"must execute it manually. Explain the potential risks before they proceed."
        )


# =============================================================================
# File Sandboxing Security Check
# =============================================================================


class FileSandboxingCheck(ISecurityCheck):
    """Security check for file access sandboxing."""

    def __init__(
        self,
        config: FileSandboxingConfig,
        path_validator: IPathValidator,
        session_service: ISessionService,
    ) -> None:
        """Initialize the file sandboxing check.

        Args:
            config: Configuration for file sandboxing.
            path_validator: Service for validating paths.
            session_service: Service for accessing session state.
        """
        self._config = config
        self._enabled = config.enabled
        self._validator = path_validator
        self._session_service = session_service

        # Compile tool patterns
        all_patterns = list(config.default_tool_patterns) + list(
            config.custom_tool_patterns
        )
        self._tool_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in all_patterns
        ]

        # Compile exclusion patterns
        self._excluded_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in config.excluded_tools
        ]

        # Metrics
        self._blocked_count = 0
        self._allowed_count = 0

    @property
    def name(self) -> str:
        return "file_sandboxing_check"

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def check(
        self,
        context: ToolCallContext,
        command_service: CommandExtractionService,
    ) -> SecurityCheckResult:
        """Check if tool call accesses files outside project boundary."""
        if not self._enabled:
            return SecurityCheckResult.allow()

        # Check if this is a file-changing tool
        if not self._is_file_changing_tool(context.tool_name):
            return SecurityCheckResult.allow()

        # Get project directory from session
        try:
            session = await self._session_service.get_session(context.session_id)
            project_dir = session.state.project_dir
        except Exception as e:
            logger.debug(f"Could not get session for sandboxing: {e}")
            return SecurityCheckResult.allow()

        if not project_dir:
            # No project directory set, allow
            return SecurityCheckResult.allow()

        project_root = Path(project_dir).resolve()

        # Extract paths from arguments
        try:
            paths = self._validator.extract_paths_from_arguments(
                context.tool_arguments, self._config.path_parameter_names
            )
        except ValueError as e:
            if self._config.strict_mode:
                self._blocked_count += 1
                return SecurityCheckResult.block(
                    reason="path_extraction_failed",
                    message=f"File operation blocked: Failed to extract paths. Error: {e}",
                    metadata={"check": self.name, "error": str(e)},
                )
            return SecurityCheckResult.allow()

        # If no paths from arguments, try extracting from command strings
        if not paths and command_service.is_shell_tool(context.tool_name):
            commands = command_service.extract_command_strings(context.tool_arguments)
            for cmd in commands:
                paths.extend(command_service.extract_paths_from_command(cmd, project_root))

        if not paths:
            if self._config.strict_mode:
                self._blocked_count += 1
                return SecurityCheckResult.block(
                    reason="no_paths_found",
                    message=f"File operation blocked: No file paths found. Allowed: {project_root}",
                    metadata={"check": self.name, "project_root": str(project_root)},
                )
            return SecurityCheckResult.allow()

        # Validate paths
        violating_paths: list[str] = []
        for path_str in paths:
            try:
                normalized_path = self._validator.normalize_path(
                    path_str, str(project_root)
                )
                if not self._validator.is_within_boundary(
                    normalized_path,
                    project_root,
                    allow_parent=self._config.allow_parent_access,
                ):
                    violating_paths.append(path_str)
            except ValueError:
                violating_paths.append(path_str)

        if violating_paths:
            self._blocked_count += 1
            return SecurityCheckResult.block(
                reason="path_outside_sandbox",
                message=(
                    f"File operation blocked: Paths outside project root: "
                    f"{', '.join(violating_paths[:3])}. Allowed: {project_root}"
                ),
                metadata={
                    "check": self.name,
                    "violating_paths": violating_paths,
                    "project_root": str(project_root),
                },
            )

        self._allowed_count += 1
        return SecurityCheckResult.allow()

    def _is_file_changing_tool(self, tool_name: str) -> bool:
        """Check if tool matches file-changing patterns."""
        # Check exclusions first
        for pattern in self._excluded_patterns:
            if pattern.search(tool_name):
                return False

        return any(pattern.search(tool_name) for pattern in self._tool_patterns)

    def get_metrics(self) -> dict[str, int]:
        """Get metrics for monitoring."""
        return {
            "blocked_count": self._blocked_count,
            "allowed_count": self._allowed_count,
        }


# =============================================================================
# Unified Security Handler
# =============================================================================


class UnifiedToolSecurityHandler(IToolCallHandler):
    """Unified handler for all tool call security features.

    This handler consolidates dangerous command detection and file sandboxing
    into a single handler with pluggable security checks. Benefits:
    - Single handler runs all security checks in one pass
    - Shared command extraction service (no duplicate parsing)
    - Unified loop prevention mechanism
    - Configurable feature toggles
    """

    # Default escalating steering messages
    _DEFAULT_ESCALATING_MESSAGES: tuple[str, ...] = (
        # First warning
        (
            "[Security Notice - First Warning]\n"
            "Your tool call was blocked by the proxy security system. "
            "This is a permanent security policy.\n\n"
            "You cannot retry or rephrase to bypass this protection. "
            "Your only option is to inform the user that they must execute "
            "this operation manually, explaining any risks involved."
        ),
        # Second warning
        (
            "[Security Notice - SECOND WARNING]\n"
            "STOP: You have now attempted a blocked operation TWICE. "
            "Both attempts were blocked and will continue to be blocked.\n\n"
            "This is your FINAL opportunity to proceed correctly:\n"
            "1. Tell the user what command needs to be run manually\n"
            "2. Explain the risks involved\n"
            "3. Wait for the user to confirm execution\n\n"
            "Further attempts will terminate this session."
        ),
        # Final warning
        (
            "[Security Notice - FINAL WARNING]\n"
            "CRITICAL: This is your THIRD blocked attempt. "
            "If you attempt another blocked operation, this session will be "
            "immediately terminated.\n\n"
            "YOU MUST NOW acknowledge that you cannot perform this operation "
            "and provide the user with manual execution instructions."
        ),
    )

    _TERMINAL_ERROR_TEMPLATE = (
        "[Security - Session Terminated]\n\n"
        "This session has been terminated due to repeated attempts to perform "
        "blocked operations ({count} attempts) despite multiple warnings.\n\n"
        "Please start a new session to continue with your task."
    )

    def __init__(
        self,
        config: UnifiedSecurityConfig,
        path_validator: IPathValidator | None = None,
        session_service: ISessionService | None = None,
    ) -> None:
        """Initialize the unified security handler.

        Args:
            config: Unified security configuration.
            path_validator: Path validation service (required for file sandboxing).
            session_service: Session service (required for file sandboxing).
        """
        self._config = config
        self._priority = config.priority

        # Create shared command extraction service
        self._command_service = CommandExtractionService(
            max_command_length=config.dangerous_commands.max_command_length
        )

        # Initialize security checks
        self._checks: list[ISecurityCheck] = []

        # Add dangerous command check
        if config.dangerous_commands.enabled:
            self._checks.append(DangerousCommandCheck(config.dangerous_commands))
            logger.info("Dangerous command security check enabled")

        # Add file sandboxing check (if dependencies provided)
        if config.file_sandboxing.enabled:
            if path_validator is not None and session_service is not None:
                self._checks.append(
                    FileSandboxingCheck(
                        config.file_sandboxing, path_validator, session_service
                    )
                )
                logger.info("File sandboxing security check enabled")
            else:
                logger.warning(
                    "File sandboxing enabled but path_validator or session_service not provided"
                )

        # Loop prevention settings
        self._max_retries = config.loop_prevention.max_retries
        self._escalating_messages = (
            tuple(config.loop_prevention.custom_messages)
            if config.loop_prevention.custom_messages
            else self._DEFAULT_ESCALATING_MESSAGES
        )

        logger.info(
            f"UnifiedToolSecurityHandler initialized with {len(self._checks)} active checks"
        )

    @property
    def name(self) -> str:
        return "unified_tool_security_handler"

    @property
    def priority(self) -> int:
        return self._priority

    async def can_handle(self, context: ToolCallContext) -> bool:
        """Check if any security check can handle this tool call."""
        if not self._config.enabled:
            return False

        # Quick check: any enabled check?
        return any(check.enabled for check in self._checks)

    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        """Run all security checks and return result if any block."""
        if not self._config.enabled:
            return ToolCallReactionResult(should_swallow=False)

        # Run checks in order until one blocks
        for check in self._checks:
            if not check.enabled:
                continue

            try:
                result = await check.check(context, self._command_service)
                if result.blocked:
                    logger.info(
                        f"Security check '{check.name}' blocked tool call: {result.reason}"
                    )
                    return self._create_block_result(context, check.name, result)
            except Exception as e:
                logger.warning(
                    f"Security check '{check.name}' failed: {e}", exc_info=True
                )
                # Fail open on errors
                continue

        # All checks passed
        return ToolCallReactionResult(should_swallow=False)

    def _create_block_result(
        self,
        context: ToolCallContext,
        check_name: str,
        result: SecurityCheckResult,
    ) -> ToolCallReactionResult:
        """Create a blocking result with metadata."""
        return ToolCallReactionResult(
            should_swallow=True,
            replacement_response=result.message,
            metadata={
                "handler": self.name,
                "check": check_name,
                "reason": result.reason,
                "tool_name": context.tool_name,
                "session_id": context.session_id,
                "source": "unified_security",
                **result.metadata,
            },
        )

    def get_escalating_message(self, retry_count: int) -> str:
        """Get the appropriate escalating message for the retry count."""
        index = min(retry_count - 1, len(self._escalating_messages) - 1)
        return self._escalating_messages[index]

    def get_terminal_error(self, retry_count: int) -> str:
        """Get the terminal error message."""
        return self._TERMINAL_ERROR_TEMPLATE.format(count=retry_count)

    def is_terminal(self, retry_count: int) -> bool:
        """Check if retry count has exceeded the limit."""
        return retry_count > self._max_retries

    # =========================================================================
    # Legacy Compatibility
    # =========================================================================

    @classmethod
    def from_legacy(
        cls,
        dangerous_command_config: Any | None = None,
        sandboxing_config: Any | None = None,
        path_validator: IPathValidator | None = None,
        session_service: ISessionService | None = None,
    ) -> UnifiedToolSecurityHandler:
        """Create handler from legacy separate configurations.

        This provides backward compatibility during migration.
        """
        unified_config = UnifiedSecurityConfig.from_legacy_configs(
            dangerous_command_config, sandboxing_config
        )
        return cls(unified_config, path_validator, session_service)
