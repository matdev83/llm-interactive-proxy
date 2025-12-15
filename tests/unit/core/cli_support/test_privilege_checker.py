"""Unit tests for PrivilegeChecker service.

**Feature: cli-god-object-refactoring, Task 8: PrivilegeChecker (TDD)**

Tests privilege detection and enforcement logic extracted from cli.py.
"""

import pytest

# This will fail initially - we haven't created the module yet
try:
    from src.core.cli_support.privilege_checker import (
        PlatformDetector,
        PrivilegeChecker,
    )
except ImportError:
    PrivilegeChecker = None  # type: ignore
    PlatformDetector = None  # type: ignore

# ============================================================================
# Test Fixtures and Mocks
# ============================================================================


class MockPlatformDetector:
    """Mock platform detector for testing."""

    def __init__(
        self,
        is_windows: bool = False,
        is_root: bool = False,
        has_geteuid: bool = True,
        has_windll: bool = True,
        is_user_admin: bool = False,
    ):
        self.is_windows = is_windows
        self.is_root = is_root
        self.has_geteuid = has_geteuid
        self.has_windll = has_windll
        self.is_user_admin = is_user_admin

    def get_platform_name(self) -> str:
        """Get platform name."""
        return "nt" if self.is_windows else "posix"

    def get_system_platform(self) -> str:
        """Get sys.platform value."""
        return "win32" if self.is_windows else "linux"

    def get_euid(self) -> int:
        """Get effective user ID."""
        if not self.has_geteuid:
            raise AttributeError("geteuid not available")
        return 0 if self.is_root else 1000

    def is_user_an_admin(self) -> bool:
        """Check if user is admin on Windows."""
        if not self.has_windll:
            raise AttributeError("windll not available")
        return self.is_user_admin


# ============================================================================
# Unit Tests - Basic Functionality
# ============================================================================


@pytest.mark.skipif(
    PrivilegeChecker is None, reason="PrivilegeChecker not implemented yet"
)
class TestPrivilegeCheckerBasics:
    """Test basic PrivilegeChecker functionality."""

    def test_checker_instantiation(self):
        """Test that PrivilegeChecker can be instantiated."""
        checker = PrivilegeChecker()
        assert checker is not None

    def test_checker_with_custom_detector(self):
        """Test that PrivilegeChecker accepts custom platform detector."""
        detector = MockPlatformDetector()
        checker = PrivilegeChecker(platform_detector=detector)
        assert checker is not None


# ============================================================================
# Unit Tests - Linux/Unix Privilege Detection
# ============================================================================


@pytest.mark.skipif(
    PrivilegeChecker is None, reason="PrivilegeChecker not implemented yet"
)
class TestLinuxPrivilegeDetection:
    """Test privilege detection on Linux/Unix systems."""

    def test_detects_root_user(self):
        """Test that root user (UID 0) is detected as admin."""
        detector = MockPlatformDetector(is_windows=False, is_root=True)
        checker = PrivilegeChecker(platform_detector=detector)

        assert checker.is_admin() is True

    def test_detects_non_root_user(self):
        """Test that non-root user is not detected as admin."""
        detector = MockPlatformDetector(is_windows=False, is_root=False)
        checker = PrivilegeChecker(platform_detector=detector)

        assert checker.is_admin() is False

    def test_handles_missing_geteuid(self):
        """Test graceful handling when geteuid is not available."""
        detector = MockPlatformDetector(is_windows=False, has_geteuid=False)
        checker = PrivilegeChecker(platform_detector=detector)

        # Should return False when functionality is missing
        assert checker.is_admin() is False


# ============================================================================
# Unit Tests - Windows Privilege Detection
# ============================================================================


@pytest.mark.skipif(
    PrivilegeChecker is None, reason="PrivilegeChecker not implemented yet"
)
class TestWindowsPrivilegeDetection:
    """Test privilege detection on Windows systems."""

    def test_detects_admin_user(self):
        """Test that Windows admin user is detected."""
        detector = MockPlatformDetector(is_windows=True, is_user_admin=True)
        checker = PrivilegeChecker(platform_detector=detector)

        assert checker.is_admin() is True

    def test_detects_non_admin_user(self):
        """Test that Windows non-admin user is not detected."""
        detector = MockPlatformDetector(is_windows=True, is_user_admin=False)
        checker = PrivilegeChecker(platform_detector=detector)

        assert checker.is_admin() is False

    def test_handles_missing_windll(self):
        """Test graceful handling when ctypes.windll is not available."""
        detector = MockPlatformDetector(is_windows=True, has_windll=False)
        checker = PrivilegeChecker(platform_detector=detector)

        # Should return False when functionality is missing
        assert checker.is_admin() is False


# ============================================================================
# Unit Tests - Platform Functionality Detection
# ============================================================================


@pytest.mark.skipif(
    PrivilegeChecker is None, reason="PrivilegeChecker not implemented yet"
)
class TestPlatformFunctionalityDetection:
    """Test platform functionality detection."""

    def test_has_functionality_on_linux(self):
        """Test that Linux systems report privilege functionality."""
        detector = MockPlatformDetector(is_windows=False, has_geteuid=True)
        checker = PrivilegeChecker(platform_detector=detector)

        assert checker.has_privilege_functionality() is True

    def test_no_functionality_on_linux_without_geteuid(self):
        """Test that Linux without geteuid reports no functionality."""
        detector = MockPlatformDetector(is_windows=False, has_geteuid=False)
        checker = PrivilegeChecker(platform_detector=detector)

        assert checker.has_privilege_functionality() is False

    def test_has_functionality_on_windows(self):
        """Test that Windows systems report privilege functionality."""
        detector = MockPlatformDetector(is_windows=True, has_windll=True)
        checker = PrivilegeChecker(platform_detector=detector)

        assert checker.has_privilege_functionality() is True

    def test_no_functionality_on_windows_without_windll(self):
        """Test that Windows without windll reports no functionality."""
        detector = MockPlatformDetector(is_windows=True, has_windll=False)
        checker = PrivilegeChecker(platform_detector=detector)

        assert checker.has_privilege_functionality() is False


# ============================================================================
# Unit Tests - Privilege Enforcement (Requirement 3.2)
# ============================================================================


@pytest.mark.skipif(
    PrivilegeChecker is None, reason="PrivilegeChecker not implemented yet"
)
class TestPrivilegeEnforcement:
    """Test privilege enforcement logic.

    **Validates: Requirement 3.2**
    WHEN running as admin without --allow-admin
    THEN PrivilegeChecker SHALL raise SystemExit with appropriate message
    """

    def test_raises_system_exit_for_root_on_linux(self):
        """Test that root user without allow_admin raises SystemExit."""
        detector = MockPlatformDetector(is_windows=False, is_root=True)
        checker = PrivilegeChecker(platform_detector=detector)

        with pytest.raises(SystemExit) as exc_info:
            checker.check_privileges(allow_admin=False)

        assert "root" in str(exc_info.value).lower()

    def test_raises_system_exit_for_admin_on_windows(self):
        """Test that Windows admin without allow_admin raises SystemExit."""
        detector = MockPlatformDetector(is_windows=True, is_user_admin=True)
        checker = PrivilegeChecker(platform_detector=detector)

        with pytest.raises(SystemExit) as exc_info:
            checker.check_privileges(allow_admin=False)

        assert "admin" in str(exc_info.value).lower()

    def test_allows_admin_when_flag_set(self):
        """Test that admin is allowed when allow_admin=True."""
        detector = MockPlatformDetector(is_windows=False, is_root=True)
        checker = PrivilegeChecker(platform_detector=detector)

        # Should not raise
        checker.check_privileges(allow_admin=True)

    def test_allows_non_admin_without_flag(self):
        """Test that non-admin users are allowed without flag."""
        detector = MockPlatformDetector(is_windows=False, is_root=False)
        checker = PrivilegeChecker(platform_detector=detector)

        # Should not raise
        checker.check_privileges(allow_admin=False)

    def test_allows_non_admin_with_flag(self):
        """Test that non-admin users are allowed with flag."""
        detector = MockPlatformDetector(is_windows=False, is_root=False)
        checker = PrivilegeChecker(platform_detector=detector)

        # Should not raise
        checker.check_privileges(allow_admin=True)


# ============================================================================
# Unit Tests - Error Message Content (Requirement 3.2)
# ============================================================================


@pytest.mark.skipif(
    PrivilegeChecker is None, reason="PrivilegeChecker not implemented yet"
)
class TestErrorMessageContent:
    """Test that error messages match original implementation.

    **Validates: Requirement 3.2**
    Error messages must match the original implementation exactly.
    """

    def test_linux_error_message(self):
        """Test that Linux error message matches original."""
        detector = MockPlatformDetector(is_windows=False, is_root=True)
        checker = PrivilegeChecker(platform_detector=detector)

        with pytest.raises(SystemExit) as exc_info:
            checker.check_privileges(allow_admin=False)

        # Original message: "Refusing to run as root user"
        assert str(exc_info.value) == "Refusing to run as root user"

    def test_windows_error_message(self):
        """Test that Windows error message matches original."""
        detector = MockPlatformDetector(is_windows=True, is_user_admin=True)
        checker = PrivilegeChecker(platform_detector=detector)

        with pytest.raises(SystemExit) as exc_info:
            checker.check_privileges(allow_admin=False)

        # Original message: "Refusing to run with administrative privileges"
        assert str(exc_info.value) == "Refusing to run with administrative privileges"


# ============================================================================
# Unit Tests - Real Platform Detection (Integration-like)
# ============================================================================


@pytest.mark.skipif(
    PrivilegeChecker is None, reason="PrivilegeChecker not implemented yet"
)
class TestRealPlatformDetection:
    """Test with default (real) platform detector."""

    def test_real_detector_initialization(self):
        """Test that checker works with default real platform detector."""
        checker = PrivilegeChecker()

        # Should not raise
        is_admin = checker.is_admin()
        assert isinstance(is_admin, bool)

    def test_real_functionality_check(self):
        """Test functionality check with real platform detector."""
        checker = PrivilegeChecker()

        has_func = checker.has_privilege_functionality()
        assert isinstance(has_func, bool)

    def test_enforcement_with_real_detector(self):
        """Test enforcement with real platform detector (non-admin assumed)."""
        checker = PrivilegeChecker()

        # Assuming tests don't run as root/admin
        # This should not raise
        checker.check_privileges(allow_admin=False)
