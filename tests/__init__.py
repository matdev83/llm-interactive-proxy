"""Testing package with comprehensive coroutine warning prevention framework."""

from .testing_framework import (
    # Core classes
    SafeSessionService,
    SafeTestSession,
    EnforcedMockFactory,
    
    # Test stage base classes
    ValidatedTestStage,
    MockBackendTestStage, 
    RealBackendTestStage,
    
    # Protocols for type safety
    SyncOnlyService,
    AsyncOnlyService,
    
    # Validation utilities
    CoroutineWarningDetector,
    MockValidationError,
)

__all__ = [
    # Core functionality
    'SafeSessionService',
    'SafeTestSession', 
    'EnforcedMockFactory',
    
    # Test stages
    'ValidatedTestStage',
    'MockBackendTestStage',
    'RealBackendTestStage', 
    
    # Type safety
    'SyncOnlyService',
    'AsyncOnlyService',
    
    # Validation
    'CoroutineWarningDetector',
    'MockValidationError',
]

# This file makes tests a Python package
