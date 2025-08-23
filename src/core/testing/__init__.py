"""
Testing framework for preventing coroutine warnings.

This package provides interfaces and base classes that automatically prevent
common testing issues like unawaited coroutines through structural enforcement.

Usage:
    from src.core.testing import ValidatedTestStage, EnforcedMockFactory

    class MyTestStage(ValidatedTestStage):
        async def _register_services(self, services, config):
            session_service = self.create_safe_session_service_mock()
            self.safe_register_instance(services, ISessionService, session_service)
"""

# Core interfaces and validators
# Base classes for test stages
from .base_stage import (
    BackendServiceTestStage,
    GuardedMockCreationMixin,
    SessionServiceTestStage,
    ValidatedTestStage,
)
from .interfaces import (
    AsyncOnlyService,
    EnforcedMockFactory,
    SafeAsyncMockWrapper,
    SafeTestSession,
    SyncOnlyService,
    TestServiceValidator,
    TestStageValidator,
    enforce_async_sync_separation,
)

# Development and runtime checking tools
from .type_checker import (
    AsyncSyncPatternChecker,
    RuntimePatternChecker,
    create_pre_commit_hook,
)

__all__ = [
    "AsyncOnlyService",
    "AsyncSyncPatternChecker",
    "BackendServiceTestStage",
    "EnforcedMockFactory",
    "GuardedMockCreationMixin",
    "RuntimePatternChecker",
    "SafeAsyncMockWrapper",
    "SafeTestSession",
    "SessionServiceTestStage",
    "SyncOnlyService",
    "TestServiceValidator",
    "TestStageValidator",
    "ValidatedTestStage",
    "create_pre_commit_hook",
    "enforce_async_sync_separation",
]

# Version info
__version__ = "1.0.0"
__author__ = "LLM Interactive Proxy Team"
__description__ = (
    "Testing framework for preventing coroutine warnings through structural enforcement"
)
