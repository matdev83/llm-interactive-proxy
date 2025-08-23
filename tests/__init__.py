"""Testing package with comprehensive coroutine warning prevention framework."""

from .testing_framework import (
    # Protocols for type safety
    AsyncOnlyService,
    # Validation utilities
    CoroutineWarningDetector,
    # Core classes
    EnforcedMockFactory,
    # Test stage base classes
    MockBackendTestStage,
    MockValidationError,
    RealBackendTestStage,
    SafeSessionService,
    SafeTestSession,
    SyncOnlyService,
    ValidatedTestStage,
)

__all__ = [
    # Core functionality
    'AsyncOnlyService',
    'CoroutineWarningDetector',
    'EnforcedMockFactory',
    'MockBackendTestStage',
    'MockValidationError',
    'RealBackendTestStage',
    'SafeSessionService',
    'SafeTestSession',
    'SyncOnlyService',
    'ValidatedTestStage',
]

# This file makes tests a Python package
