"""Protocols and base types for CLI support services.

This module defines the core protocols and type aliases used throughout the
cli_support package. It establishes the contracts that all domain applicators
and services must follow.

Requirements satisfied:
- 6.1: DomainApplicator protocol for domain-specific configuration application
- 8.1: Services receive dependencies through constructor injection
- 8.2: Services receive AppConfig or relevant subsections through injection
"""

from __future__ import annotations

import argparse
from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Protocol, TypeAlias

if TYPE_CHECKING:
    from src.core.config.app_config import AppConfig
    from src.core.config.parameter_resolution import ParameterResolution


# =============================================================================
# Type Aliases
# =============================================================================

#: CLI argument namespace type alias for clarity
CliArgs: TypeAlias = argparse.Namespace

#: Dictionary of CLI overrides to be applied to configuration
CliOverrides: TypeAlias = dict[str, Any]

#: Path in the configuration tree (e.g., "backends.openai.api_key")
ConfigPath: TypeAlias = str

#: CLI flag name (e.g., "--default-backend")
CliFlag: TypeAlias = str


# =============================================================================
# Domain Applicator Protocol
# =============================================================================


class DomainApplicator(Protocol):
    """Protocol for domain-specific configuration applicators.

    Each domain applicator is responsible for extracting relevant CLI arguments
    and applying them to a specific section of the application configuration.

    Domain applicators MUST:
    - Only modify configuration values within their designated domain
    - Record parameter sources via ParameterResolution for traceability
    - Handle environment variable fallbacks within their scope
    - Be stateless (no instance state between calls)

    Domain applicators SHOULD:
    - Accept dependencies through constructor injection
    - Be testable in isolation with mock AppConfig

    Example implementation:
        class ServerApplicator:
            def apply(
                self,
                args: CliArgs,
                overrides: CliOverrides,
                resolution: ParameterResolution,
            ) -> None:
                if args.host is not None:
                    overrides["host"] = args.host
                    resolution.record("host", args.host, ParameterSource.CLI, "--host")

    Requirements satisfied:
    - 6.1: ConfigurationApplicator delegates to domain-specific applicators
    - 6.2: Each applicator only modifies its relevant configuration section
    - 6.3: Environment variables are handled within applicator's scope
    - 6.5: Each applicator is testable in isolation with mock AppConfig
    """

    @abstractmethod
    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply domain-specific CLI arguments to configuration overrides.

        Args:
            args: Parsed command-line arguments namespace
            overrides: Dictionary to collect configuration overrides
            resolution: Parameter resolution tracker for recording sources

        Note:
            Implementations should modify `overrides` in-place and call
            `resolution.record()` for any CLI-originated values.
        """
        ...


# =============================================================================
# Configuration Applicator Protocol
# =============================================================================


class ConfigurationApplicatorProtocol(Protocol):
    """Protocol for the main configuration applicator.

    The ConfigurationApplicator coordinates domain applicators to transform
    CLI arguments into a complete AppConfig instance.

    Requirements satisfied:
    - 1.2: CLI module delegates to ConfigurationApplicator for applying arguments
    - 1.3: ConfigurationApplicator records parameter sources via ParameterResolution
    - 6.1: Coordinates domain-specific applicators
    """

    @abstractmethod
    def apply(
        self,
        args: CliArgs,
        *,
        return_resolution: bool = False,
        resolution: ParameterResolution | None = None,
    ) -> AppConfig | tuple[AppConfig, ParameterResolution]:
        """Apply CLI arguments to create configuration.

        Args:
            args: Parsed command-line arguments namespace
            return_resolution: If True, return (config, resolution) tuple
            resolution: Optional pre-existing resolution tracker

        Returns:
            AppConfig or tuple (AppConfig, ParameterResolution) if return_resolution=True
        """
        ...


# =============================================================================
# Error Handler Protocol
# =============================================================================


class ErrorHandlerProtocol(Protocol):
    """Protocol for user-friendly error message formatting.

    Requirements satisfied:
    - 5.1: Format user-friendly messages with actionable guidance
    - 5.2: Provide specific re-authentication instructions for OAuth errors
    - 5.3: List required environment variables for API key errors
    - 5.4: Provide generic troubleshooting guidance for unknown errors
    - 5.5: Write to stderr with consistent formatting
    """

    @abstractmethod
    def handle_build_error(self, error_msg: str) -> None:
        """Handle application build errors with user-friendly messages.

        Args:
            error_msg: The error message from the application build failure
        """
        ...

    @abstractmethod
    def handle_exception(self, exc: BaseException) -> None:
        """Handle an unexpected exception with user-friendly messaging."""
        ...


# =============================================================================
# Privilege Checker Protocol
# =============================================================================


class PrivilegeCheckerProtocol(Protocol):
    """Protocol for cross-platform privilege/admin detection.

    Requirements satisfied:
    - 3.1: Detect admin/root status on Windows, Linux, and macOS
    - 3.2: Raise SystemExit when running as admin without --allow-admin
    - 3.3: Return safe default when platform lacks privilege functionality
    - 3.4: Accept injectable platform detection for testing
    """

    @abstractmethod
    def is_admin(self) -> bool:
        """Check if current process has administrative privileges.

        Returns:
            True if running with admin/root privileges, False otherwise
        """
        ...

    @abstractmethod
    def has_privilege_functionality(self) -> bool:
        """Check if the platform supports privilege checking.

        Returns:
            True if privilege checking is supported, False otherwise
        """
        ...

    @abstractmethod
    def check_privileges(self, *, allow_admin: bool = False) -> None:
        """Verify privilege requirements are met.

        Args:
            allow_admin: If True, allow running with elevated privileges

        Raises:
            SystemExit: If running as admin without allow_admin=True
        """
        ...


# =============================================================================
# Logging Configurator Protocol
# =============================================================================


class LoggingConfiguratorProtocol(Protocol):
    """Protocol for logging configuration.

    Requirements satisfied:
    - 4.1: Apply log level, file path, and color settings from AppConfig
    - 4.2: Apply timestamp suffixes to log/capture file paths consistently
    - 4.3: Provide clear error messages on configuration failure
    - 4.4: Accept injectable logging handlers for testing
    """

    @abstractmethod
    def configure(self, config: AppConfig) -> None:
        """Configure logging based on application configuration.

        Args:
            config: Application configuration containing logging settings
        """
        ...

    @abstractmethod
    def apply_timestamp_suffix(self, path: str | None) -> str | None:
        """Append a timestamp suffix to a file path.

        Args:
            path: File path or None

        Returns:
            Path with timestamp suffix or None if path was None
        """
        ...

    @abstractmethod
    def apply_pid_suffixes(self, config: AppConfig) -> AppConfig:
        """Return a copy of config with timestamp-suffixed log and capture files.

        Args:
            config: Original configuration

        Returns:
            New configuration with timestamp suffixes applied
        """
        ...


# =============================================================================
# Server Lifecycle Manager Protocol
# =============================================================================


class ServerLifecycleManagerProtocol(Protocol):
    """Protocol for server lifecycle management.

    Requirements satisfied:
    - 2.1: Coordinate port availability checks, privilege verification, daemon mode, uvicorn startup
    - 2.2: Handle platform-specific daemonization (Unix fork, Windows subprocess)
    - 2.3: Delegate to ErrorHandler for user-friendly startup error messages
    - 2.4: Coordinate concurrent execution of multiple servers (main + Anthropic)
    - 2.5: Ensure graceful cleanup of all resources on shutdown
    """

    @abstractmethod
    def is_port_in_use(self, host: str, port: int) -> bool:
        """Check if a port is already in use.

        Args:
            host: Host address to check
            port: Port number to check

        Returns:
            True if port is in use, False otherwise
        """
        ...

    @abstractmethod
    def handle_daemon_mode(
        self,
        args: CliArgs,
        config: AppConfig,
    ) -> bool:
        """Handle daemon mode if requested.

        Args:
            args: Parsed CLI arguments
            config: Application configuration

        Returns:
            True if we should exit (daemon was spawned), False otherwise
        """
        ...

    @abstractmethod
    def check_ports(self, config: AppConfig) -> None:
        """Exit if configured ports are in use."""
        ...

    @abstractmethod
    async def start_servers(
        self,
        app: Any,
        config: AppConfig,
    ) -> None:
        """Start the server(s) with the given configuration.

        Args:
            config: Application configuration
        """
        ...


# =============================================================================
# Platform Detector Protocol (for PrivilegeChecker testability)
# =============================================================================


class PlatformDetectorProtocol(Protocol):
    """Protocol for platform detection (used by PrivilegeChecker)."""

    @abstractmethod
    def get_platform_name(self) -> str: ...

    @abstractmethod
    def get_system_platform(self) -> str: ...

    @abstractmethod
    def get_euid(self) -> int: ...

    @abstractmethod
    def is_user_an_admin(self) -> bool: ...


# =============================================================================
# Argument Parser Builder Protocol
# =============================================================================


class ArgumentParserBuilderProtocol(Protocol):
    """Protocol for CLI argument parser construction.

    Requirements satisfied:
    - 1.1: ArgumentParser is constructed by a dedicated ArgumentParserBuilder class
    - 1.5: Adding new CLI arguments only requires modifying ArgumentParserBuilder
    """

    @abstractmethod
    def build(self) -> argparse.ArgumentParser:
        """Build the complete CLI argument parser.

        Returns:
            Configured ArgumentParser instance
        """
        ...


# =============================================================================
# CLI Args Validator Protocol
# =============================================================================


class CliArgsValidatorProtocol(Protocol):
    """Protocol for non-argparse CLI validation.

    Requirements satisfied:
    - 1.4: Structured, testable errors from validation service
    """

    @abstractmethod
    def validate(self, args: CliArgs) -> None:
        """Validate parsed CLI arguments.

        Args:
            args: Parsed CLI arguments namespace

        Raises:
            ValueError: If validation fails, with detailed error message
        """
        ...
