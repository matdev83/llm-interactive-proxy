"""Example usage patterns for test stages and safe mock creation."""

from __future__ import annotations

import logging
from typing import Any

from src.core.app.stages.base import InitializationStage
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.testing.base_stage import ValidatedTestStage


# ❌ DON'T DO THIS - This is the old way that causes coroutine warnings
class ProblematicTestStage(InitializationStage):
    """Example of what NOT to do - this will cause coroutine warnings."""

    @property
    def name(self) -> str:
        return "problematic_stage"

    def get_dependencies(self) -> list[str]:
        return ["core_services"]

    def get_description(self) -> str:
        return "Problematic test stage that causes warnings"

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        from unittest.mock import AsyncMock

        from src.core.interfaces.backend_service_interface import IBackendService
        from src.core.interfaces.session_service_interface import ISessionService

        # ❌ PROBLEM: AsyncMock for session service
        # This will cause "coroutine was never awaited" warnings because
        # get_session() is called synchronously but returns AsyncMock
        session_service = AsyncMock(spec=ISessionService)
        services.add_instance(ISessionService, session_service)

        # ❌ PROBLEM: No validation of service registration
        backend_service = AsyncMock(spec=IBackendService)
        services.add_instance(IBackendService, backend_service)


# ✅ DO THIS - This is the new safe way
class SafeTestStage(ValidatedTestStage):
    """Example of what TO do - this prevents coroutine warnings."""

    @property
    def name(self) -> str:
        return "safe_stage"

    def get_dependencies(self) -> list[str]:
        return ["core_services"]

    def get_description(self) -> str:
        return "Safe test stage with automatic validation"

    async def _register_services(
        self, services: ServiceCollection, config: AppConfig
    ) -> None:
        from src.core.interfaces.backend_service_interface import IBackendService
        from src.core.interfaces.session_service_interface import ISessionService

        # ✅ SOLUTION: Use safe factories
        # These are automatically configured to prevent coroutine warnings
        session_service = self.create_safe_session_service_mock()
        backend_service = self.create_safe_backend_service_mock()

        # ✅ SOLUTION: Use safe registration with automatic validation
        self.safe_register_instance(services, ISessionService, session_service)
        self.safe_register_instance(services, IBackendService, backend_service)


# Example test class showing proper mock usage
class ExampleTestClass:
    """Example test class showing proper patterns."""

    async def test_with_safe_mocks(self) -> None:
        """Example test using safe mock creation."""
        from src.core.testing.interfaces import EnforcedMockFactory

        # ✅ Use safe factories for known problematic services
        session_service = EnforcedMockFactory.create_session_service_mock()

        # These are guaranteed not to cause coroutine warnings
        session = await session_service.get_session("test_id")  # Returns real Session
        assert session.session_id == "test_id"

    def test_with_mixed_async_sync_service(self) -> None:
        """Example of handling services with mixed async/sync methods."""
        from src.core.testing.interfaces import SafeAsyncMockWrapper

        # ✅ For complex services with both async and sync methods
        wrapper = SafeAsyncMockWrapper(spec=SomeComplexService)

        # Mark sync methods explicitly
        wrapper.mark_method_as_sync("get_config", return_value={"key": "value"})
        wrapper.mark_method_as_sync("is_enabled", return_value=True)

        # Async methods automatically return proper coroutines
        # wrapper.async_operation() returns an awaitable AsyncMock

        service = wrapper._mock

        # Sync methods return real values
        config = service.get_config()  # Returns {'key': 'value'}
        assert config == {"key": "value"}

        # Async methods return awaitables
        # result = await service.async_operation()  # Works properly


class SomeComplexService:
    """Example service with mixed async/sync methods."""

    def get_config(self) -> dict:
        """Synchronous method."""
        return {}

    def is_enabled(self) -> bool:
        """Synchronous method."""
        return True

    async def async_operation(self) -> str:
        """Asynchronous method."""
        return "result"


# Example of integrating validation into existing test infrastructure
def create_validated_test_app() -> Any:
    """Example of creating a test app with validation."""
    from src.core.app.test_builder import ApplicationTestBuilder
    from src.core.testing.type_checker import RuntimePatternChecker

    # Build the app with safe stages
    builder = ApplicationTestBuilder()
    builder.add_stage(SafeTestStage())  # Use safe stage instead of problematic one

    # Build the app
    app = builder.build_compat(config=create_test_config())

    # Validate the app before returning
    warnings = RuntimePatternChecker.validate_test_app(app)
    if warnings:
        import logging

        logger = logging.getLogger(__name__)
        for warning in warnings:
            logger.warning(f"Test app validation warning: {warning}")

    return app


def create_test_config() -> AppConfig:
    """Create a basic test configuration."""
    from src.core.config.app_config import (
        AppConfig,
        AuthConfig,
        BackendConfig,
        BackendSettings,
    )

    return AppConfig(
        host="localhost",
        port=9000,
        backends=BackendSettings(
            default_backend="openai", openai=BackendConfig(api_key=["test_key"])
        ),
        auth=AuthConfig(disable_auth=True, api_keys=["test-key"]),
    )


# Example of migration from old to new pattern
def migrate_existing_test_stage() -> Any:
    """Example showing how to migrate an existing problematic stage."""

    # ❌ OLD WAY (causes warnings)
    class OldStage(InitializationStage):
        async def execute(self, services: Any, config: Any) -> None:
            from unittest.mock import AsyncMock

            from src.core.interfaces.session_service_interface import ISessionService

            mock = AsyncMock(spec=ISessionService)  # Problematic!
            services.add_instance(ISessionService, mock)

    # ✅ NEW WAY (safe)
    class NewStage(ValidatedTestStage):
        @property
        def name(self) -> str:
            return "migrated_stage"

        def get_dependencies(self) -> list[str]:
            return ["core_services"]

        def get_description(self) -> str:
            return "Migrated safe stage"

        async def _register_services(self, services: Any, config: Any) -> None:
            from src.core.interfaces.session_service_interface import ISessionService

            # Use safe factory instead of AsyncMock
            mock = self.create_safe_session_service_mock()
            self.safe_register_instance(services, ISessionService, mock)

    return NewStage()


if __name__ == "__main__":
    # Example of running static analysis
    from pathlib import Path

    from src.core.testing.type_checker import AsyncSyncPatternChecker

    # Initialize logger
    logger = logging.getLogger(__name__)

    # Check this file for issues (should find the problematic example)
    checker = AsyncSyncPatternChecker()
    issues = checker.check_file(Path(__file__))

    logger.info("Static analysis results:")
    if issues:
        for issue in issues:
            logger.info(f"  - {issue}")
    else:
        logger.info("  No issues found!")

    # The checker should detect the ProblematicTestStage as an issue
    # but not flag the SafeTestStage
