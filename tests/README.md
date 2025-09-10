# Comprehensive Testing Framework for Preventing Coroutine Warnings

This testing framework provides enhanced infrastructure that automatically prevents common coroutine warning issues by enforcing proper async/sync usage patterns through typing protocols, validated mock factories, and runtime validation.

## Key Features

### 1. Enforced Interfaces and Protocols

- **SyncOnlyService**: Protocol for services that should only have synchronous methods
- **AsyncOnlyService**: Protocol for services that should only have asynchronous methods
- **Type Safety**: Static type checkers and linters can detect incorrect implementations

### 2. Validated Mock Factory Methods

The `EnforcedMockFactory` provides factory methods to create properly configured mocks:

```python
from tests.testing_framework import EnforcedMockFactory

# Create synchronous mocks for sync services
sync_mock = EnforcedMockFactory.create_sync_mock(spec=MyService)

# Create async mocks for async services  
async_mock = EnforcedMockFactory.create_async_mock(spec=MyAsyncService)

# Create safe session service mocks (prevents coroutine warnings)
session_mock = EnforcedMockFactory.create_session_mock()

# Automatically determine the right mock type
auto_mock = EnforcedMockFactory.auto_mock(SomeServiceClass)
```

### 3. Base Classes for Test Stages with Automatic Validation

Use `ValidatedTestStage` base classes for test initialization that automatically validates services:

```python
from tests.testing_framework import MockBackendTestStage, RealBackendTestStage

# For full mock environments
class TestWithMocks(MockBackendTestStage):
    def setup(self):
        super().setup()  # Sets up validated mocks automatically
        # Add additional test-specific setup
        
# For tests requiring real HTTP calls
class TestWithRealBackend(RealBackendTestStage):
    def setup(self):
        super().setup()  # Sets up safe real services
        # Add additional test-specific setup
```

### 4. Runtime and Development-Time Validation Utilities

The `CoroutineWarningDetector` helps catch common warning patterns:

```python
from tests.testing_framework import CoroutineWarningDetector

# Check for unawaited coroutines in test objects
warnings = CoroutineWarningDetector.check_for_unawaited_coroutines(test_object)
if warnings:
    print("⚠️  Potential coroutine warnings found:")
    for warning in warnings:
        print(f"  - {warning}")

# Validate mock setup
is_valid = CoroutineWarningDetector.validate_mock_setup(mock_obj, ExpectedType)
```

### 5. Safe Session and Backend Mock Classes

The framework provides `SafeSessionService` to replace volatile mocks:

```python
from tests.testing_framework import SafeSessionService

# Use instead of AsyncMock for session services
session = SafeSessionService({
    'user_id': 'test-user',
    'authenticated': True
})

# All methods are synchronous and won't cause coroutine warnings
session.set('key', 'value')
value = session.get('key')
session.clear()
```

## Usage Examples

### Basic Usage

```python
import pytest
from tests.testing_framework import (
    SafeTestSession, 
    EnforcedMockFactory,
    MockBackendTestStage
)

class TestMyFeature(MockBackendTestStage):
    def setup(self):
        super().setup()  # Auto-validated mocks
        
        # Additional custom mocks
        self.register_service('custom_service', 
                            EnforcedMockFactory.create_sync_mock(spec=CustomService))
    
    def test_feature(self):
        # Get safely configured services
        session = self.get_service('session_service')
        config = self.get_service('config_service')
        
        # Test your feature without coroutine warnings
        result = my_feature(session, config)
        assert result.success
```

### Advanced Usage with Custom Validation

```python
from tests.testing_framework import ValidatedTestStage, EnforcedMockFactory

class CustomTestStage(ValidatedTestStage):
    def setup(self):
        # Register services with custom validation
        self.register_service('database', 
                            EnforcedMockFactory.create_async_mock(), 
                            force_sync=False)
        
        self.register_service('cache', 
                            EnforcedMockFactory.create_sync_mock(),
                            force_sync=True)
    
    def test_with_custom_setup(self):
        db = self.get_service('database')
        cache = self.get_service('cache')
        
        # Validated services prevent async/sync mismatches
        cache.set('key', 'value')  # Synchronous
        await db.query('SELECT * FROM table')  # Asynchronous
```

## Benefits

1. **Early Detection**: Type system and base classes catch mistakes during development
2. **Automated Guidance**: Validation utilities provide clear feedback and auto-fixes
3. **Robust Tests**: Test suites become more maintainable and free of subtle coroutine warnings
4. **Developer Confidence**: Clear patterns and automatic validation reduce guesswork
5. **Agent-Friendly**: Coding agents can rely on base classes and factory methods that guarantee correct behavior

## Integration with CI/CD

The framework can be integrated into CI pipelines:

```python
# In your test configuration
from tests.testing_framework import CoroutineWarningDetector

def pytest_runtest_setup(item):
    """Run coroutine validation before each test."""
    # Automatically validate test setup
    warnings = CoroutineWarningDetector.check_for_unawaited_coroutines(item.instance)
    if warnings:
        pytest.fail(f"Coroutine warnings detected: {warnings}")
```

## Migration Guide

To migrate existing tests to use this framework:

1. **Replace AsyncMock session services** with `SafeSessionService`
2. **Use EnforcedMockFactory** instead of direct Mock/AsyncMock creation
3. **Inherit from ValidatedTestStage** classes for automatic validation
4. **Run CoroutineWarningDetector** on existing test objects to identify issues

This framework ensures that async/sync boundaries are respected, preventing the subtle coroutine warnings that can plague test suites and making the codebase more maintainable for both human developers and AI coding agents.
