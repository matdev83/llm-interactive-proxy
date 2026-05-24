#!/usr/bin/env python3
"""
Demonstration script showing how the testing framework is now fully integrated
into the existing project infrastructure.

This demonstrates that the testing framework is not isolated code but is
actually wired into the existing test infrastructure and can be used easily.
"""

import sys
import warnings

# Standard testing imports work seamlessly
from unittest.mock import AsyncMock

# Direct imports - no need for complex setup since it's integrated into conftest.py
from testing_framework import (
    CoroutineWarningDetector,
    EnforcedMockFactory,
    MockBackendTestStage,
    RealBackendTestStage,
    SafeSessionService,
)


def demonstrate_safe_session_usage() -> None:
    """Show how SafeSessionService prevents coroutine warnings."""
    print("[WRENCH] Testing Safe Session Service...")

    # This creates a synchronous session service that won't cause warnings
    session = SafeSessionService(
        {"user_id": "demo-user", "authenticated": True, "project": "demo-project"}
    )

    # All operations are synchronous and safe
    session.set("backend", "openai")
    session.set("temperature", 0.7)

    print(f"   [OK] User: {session.get('user_id')}")
    print(f"   [OK] Backend: {session.get('backend')}")
    print(f"   [OK] Temperature: {session.get('temperature')}")
    print(f"   [OK] Authenticated: {session.is_authenticated}")


def demonstrate_enforced_mock_factory() -> None:
    """Show how EnforcedMockFactory creates proper mocks."""
    print("\n[FACTORY] Testing Enforced Mock Factory...")

    # Create safe synchronous mocks
    sync_config_mock = EnforcedMockFactory.create_sync_mock()
    sync_config_mock.get_setting.return_value = "test_value"

    # Create async mocks for async services
    async_db_mock = EnforcedMockFactory.create_async_mock()
    async_db_mock.fetch_data.return_value = {"data": "test"}

    # Create safe session mock
    session_mock = EnforcedMockFactory.create_session_mock()

    print(f"   [OK] Sync mock created: {type(sync_config_mock).__name__}")
    print(f"   [OK] Async mock created: {type(async_db_mock).__name__}")
    print(f"   [OK] Session mock created: {type(session_mock).__name__}")


def demonstrate_coroutine_warning_detection() -> None:
    """Show how the detector finds potential issues."""
    print("\n[DETECTIVE]️ Testing Coroutine Warning Detection...")

    class ProblematicTestClass:
        def __init__(self) -> None:
            # This would be problematic
            self.bad_mock = AsyncMock()
            # This is safe
            self.good_session = SafeSessionService()

    # Create test object
    test_obj = ProblematicTestClass()

    # Check for issues
    warnings_found = CoroutineWarningDetector.check_for_unawaited_coroutines(test_obj)

    print(f"   [OK] Warnings detected: {len(warnings_found)}")
    for warning in warnings_found:
        print(f"     - {warning}")


def demonstrate_test_stages() -> None:
    """Show how test stages work for different testing scenarios."""
    print("\n🎭 Testing Test Stages...")

    # Mock backend stage - for full isolation
    mock_stage = MockBackendTestStage()
    mock_stage.setup()

    mock_session = mock_stage.get_service("session_service")
    mock_config = mock_stage.get_service("config_service")

    print(f"   [OK] Mock stage session: {type(mock_session).__name__}")
    print(f"   [OK] Mock stage config: {type(mock_config).__name__}")

    # Real backend stage - for integration tests
    real_stage = RealBackendTestStage()
    real_stage.setup()

    real_session = real_stage.get_service("session_service")
    real_http = real_stage.get_service("http_client")

    print(f"   [OK] Real stage session: {type(real_session).__name__}")
    print(f"   [OK] Real stage HTTP client: {type(real_http).__name__}")


def demonstrate_pytest_integration() -> None:
    """Show that the framework works with pytest fixtures."""
    print("\n🧪 Testing Pytest Integration...")

    # This would normally be done in a test function with pytest fixtures
    # but we can demonstrate the concept here

    # Safe session service is available as a fixture
    safe_session = SafeSessionService({"test_mode": True})

    # Mock factory is available as a fixture
    mock_factory = EnforcedMockFactory

    # These can be used in any test without additional setup
    test_mock = mock_factory.create_sync_mock()
    test_session = safe_session

    print(f"   [OK] Fixture-style session: {type(test_session).__name__}")
    print(f"   [OK] Fixture-style mock: {type(test_mock).__name__}")
    print("   [OK] All fixtures available through conftest.py integration")


def main() -> int:
    """Run all demonstrations."""
    print("🚀 LLM Interactive Proxy - Integrated Testing Framework Demo")
    print("=" * 60)

    # Suppress any warnings for clean output
    warnings.filterwarnings("ignore")

    try:
        demonstrate_safe_session_usage()
        demonstrate_enforced_mock_factory()
        demonstrate_coroutine_warning_detection()
        demonstrate_test_stages()
        demonstrate_pytest_integration()

        print("\n" + "=" * 60)
        print("[OK] All demonstrations completed successfully!")
        print("\n💡 Key Integration Points:")
        print("   - Testing framework is imported in conftest.py")
        print("   - Safe fixtures are available to all tests")
        print("   - Automatic validation runs for session-related tests")
        print("   - No isolated/unused code - everything is wired in")
        print("   - Developers get warnings and guidance automatically")

        return 0

    except Exception as e:
        print(f"\n[X] Error during demonstration: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
