"""Privilege checking service for CLI.

This module provides cross-platform privilege detection and enforcement,
extracted from src/core/cli.py as part of the CLI God Object refactoring.

**Feature: cli-god-object-refactoring, Task 8: PrivilegeChecker**
**Validates: Requirements 3.1, 3.2, 3.3, 3.4**
"""

import os
import sys
from collections.abc import Callable
from typing import Protocol, cast


class PlatformDetector(Protocol):
    """Protocol for platform-specific operations.

    This protocol enables dependency injection for testing by providing
    a consistent interface for platform detection operations.

    **Validates: Requirement 3.4** - Injectable platform detection for mocking.
    """

    def get_platform_name(self) -> str:
        """Get the platform name (e.g., 'nt', 'posix')."""
        ...

    def get_system_platform(self) -> str:
        """Get sys.platform value (e.g., 'win32', 'linux')."""
        ...

    def get_euid(self) -> int:
        """Get effective user ID (Unix/Linux).

        Raises:
            AttributeError: If geteuid is not available on this platform.
        """
        ...

    def is_user_an_admin(self) -> bool:
        """Check if user has admin privileges (Windows).

        Raises:
            AttributeError: If Windows admin check is not available.
        """
        ...


class DefaultPlatformDetector:
    """Default platform detector using real system calls.

    This is the production implementation that directly queries the OS.
    """

    def get_platform_name(self) -> str:
        """Get the platform name from os.name."""
        return os.name

    def get_system_platform(self) -> str:
        """Get sys.platform value."""
        return sys.platform

    def get_euid(self) -> int:
        """Get effective user ID using os.geteuid().

        Raises:
            AttributeError: If os.geteuid is not available.
        """
        geteuid = getattr(os, "geteuid", None)
        if geteuid is None:
            raise AttributeError("geteuid not available")
        return cast(Callable[[], int], geteuid)()

    def is_user_an_admin(self) -> bool:
        """Check if user is admin on Windows using ctypes.

        Raises:
            AttributeError: If ctypes.windll is not available.
        """
        import ctypes

        if not (hasattr(ctypes, "windll") and hasattr(ctypes.windll, "shell32")):
            raise AttributeError("windll not available")
        return cast(int, ctypes.windll.shell32.IsUserAnAdmin()) != 0


class PrivilegeChecker:
    """Service for checking and enforcing privilege restrictions.

    This service provides cross-platform admin/root detection and enforces
    the policy that the server should not run with elevated privileges
    unless explicitly allowed.

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4**

    Examples:
        >>> checker = PrivilegeChecker()
        >>> if checker.is_admin():
        ...     print("Running with elevated privileges")

        >>> checker.check_and_enforce(allow_admin=False)  # Raises if admin
    """

    def __init__(self, platform_detector: PlatformDetector | None = None):
        """Initialize the privilege checker.

        Args:
            platform_detector: Optional platform detector for testing.
                              Defaults to real system detector.

        **Validates: Requirement 3.4, 8.1** - Constructor injection.
        """
        self._detector = platform_detector or DefaultPlatformDetector()

    def is_admin(self) -> bool:
        """Check if running with admin/root privileges.

        Detects admin/root status on Windows, Linux, and macOS.
        Returns False (safe default) if platform doesn't support privilege checking.

        Returns:
            True if running as admin/root, False otherwise.

        **Validates: Requirements 3.1, 3.3**
        """
        try:
            if self._detector.get_system_platform() != "win32":
                # Unix/Linux/macOS systems
                return self._is_admin_unix()
            else:
                # Windows systems
                return self._is_admin_windows()
        except Exception:
            # Safe default when detection fails
            # **Validates: Requirement 3.3**
            return False

    def _is_admin_unix(self) -> bool:
        """Check for admin privileges on Unix/Linux/macOS.

        Returns:
            True if running as root (UID 0), False otherwise.
        """
        try:
            return self._detector.get_euid() == 0
        except (AttributeError, OSError):
            # Fallback when geteuid is not available
            return False

    def _is_admin_windows(self) -> bool:
        """Check for admin privileges on Windows.

        Returns:
            True if running with admin privileges, False otherwise.
        """
        try:
            return self._detector.is_user_an_admin()
        except (AttributeError, Exception):
            # Fallback when Windows admin check is not available
            return False

    def has_privilege_functionality(self) -> bool:
        """Check if the platform supports privilege checking.

        Returns:
            True if privilege checking is supported, False otherwise.

        **Validates: Requirement 3.3**
        """
        try:
            if self._detector.get_platform_name() != "nt":
                # Unix/Linux systems should support geteuid()
                try:
                    self._detector.get_euid()
                    return True
                except AttributeError:
                    return False
            else:
                # Windows systems should support ctypes.windll
                try:
                    self._detector.is_user_an_admin()
                    return True
                except AttributeError:
                    return False
        except Exception:
            return False

    def check_privileges(self, *, allow_admin: bool = False) -> None:
        """Check privileges and enforce restrictions.

        Raises SystemExit if running as admin/root without allow_admin flag.

        Args:
            allow_admin: If True, allow running with admin privileges.
                        If False, raise SystemExit if admin.

        Raises:
            SystemExit: If running as admin and allow_admin is False.

        **Validates: Requirement 3.2** - Raise SystemExit with same messages
        as original implementation.
        """
        if not allow_admin and self.is_admin():
            # Match original error messages exactly
            if self._detector.get_platform_name() != "nt":
                raise SystemExit("Refusing to run as root user")
            else:
                raise SystemExit("Refusing to run with administrative privileges")
