# Testing Framework: Coroutine Warning Prevention

This testing framework provides interfaces and base classes that automatically prevent the "coroutine was never awaited" warnings that can occur when mocking async/sync services incorrectly.

## Overview

The framework enforces proper async/sync patterns through:

1. **Validated base classes** that automatically check service registrations
2. **Safe mock factories** that create properly configured mocks
3. **Runtime validators** that catch issues before they cause warnings
4. **Static analysis tools** that can be integrated into CI/CD

## Quick Start for Coding Agents

### [OK] DO: Use ValidatedTestStage

```python
from src.core.testing.base_stage import ValidatedTestStage

class MyTestStage(ValidatedTestStage):
    @property
    def name(self) -> str:
        return "my_test_services"
        
    def get_dependencies(self) -> list[str]:
        return ["core_services"]
        
    def get_description(self) -> str:
        return "My test services with automatic validation"
        
    async def _register_services(self, services: ServiceCollection, config: AppConfig) -> None:
        # Use safe factories - these are validated automatically
        session_service = self.create_safe_session_service_mock()
        backend_service = self.create_safe_backend_service_mock()
        
        # Use safe registration - this validates the instances
        from src.core.interfaces.session_service_interface import ISessionService
        from src.core.interfaces.backend_service_interface import IBackendService
        
        self.safe_register_instance(services, ISessionService, session_service)
        self.safe_register_instance(services, IBackendService, backend_service)
```

### [X] DON'T: Use InitializationStage directly

```python
# This can cause coroutine warnings!
class MyTestStage(InitializationStage):
    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        # This creates AsyncMock which can cause warnings
        mock_service = AsyncMock(spec=ISessionService)
        services.add_instance(ISessionService, mock_service)  # [!] Problematic!
```

### [OK] DO: Use EnforcedMockFactory

```python
from src.core.testing.interfaces import EnforcedMockFactory

# These are guaranteed to be properly configured
session_service = EnforcedMockFactory.create_session_service_mock()
backend_service = EnforcedMockFactory.create_backend_service_mock()
```

### [X] DON'T: Create AsyncMock directly for mixed interfaces

```python
# This can cause coroutine warnings!
session_service = AsyncMock(spec=ISessionService)  # [!] Problematic!
# Because get_session() should be sync but returns AsyncMock
```

### [OK] DO: Use SafeAsyncMockWrapper for complex cases

```python
from src.core.testing.interfaces import SafeAsyncMockWrapper

# For services with mixed async/sync methods
wrapper = SafeAsyncMockWrapper(spec=IMyService)
wrapper.mark_method_as_sync('get_something', return_value=real_object)
# async methods will still return proper coroutines
```

## Key Principles

### 1. Session Services Must Return Real Objects

Session services have methods like `get_session()` that are called synchronously. If these return AsyncMock, you get coroutine warnings.

```python
# [OK] GOOD
def get_session_impl(session_id: str) -> Session:
    return SafeTestSession(session_id)  # Real object

mock_service.get_session = get_session_impl

# [X] BAD  
mock_service.get_session = AsyncMock()  # Returns coroutine!
```

### 2. Use Proper Mock Types for Method Signatures

```python
# [OK] GOOD - async methods get AsyncMock
mock_service.update_session = AsyncMock()
mock_service.create_session = AsyncMock()

# [OK] GOOD - sync methods get regular Mock/function
mock_service.get_session = lambda session_id: real_session

# [X] BAD - sync method gets AsyncMock
mock_service.get_session = AsyncMock()  # Will cause warnings!
```

### 3. Validate Early and Often

The framework provides automatic validation, but you can also validate manually:

```python
from src.core.testing.interfaces import TestServiceValidator

# Validate a service before registering
TestServiceValidator.validate_session_service(my_session_service)
```

## Integration Patterns

### For Test Stages

```python
from src.core.testing.base_stage import ValidatedTestStage

class MyMockStage(ValidatedTestStage):
    # Inherit from ValidatedTestStage instead of InitializationStage
    # Use create_safe_*_mock() methods
    # Use safe_register_instance() method
    # Automatic validation happens in execute()
```

### For Test Classes

```python
from src.core.testing.base_stage import GuardedMockCreationMixin

class TestMyService(GuardedMockCreationMixin):
    def test_something(self):
        # Use guarded mock creation
        mock = self.create_mock(spec=MyService)
        async_mock = self.create_async_mock(spec=MyAsyncService)
        # These provide warnings for potential issues
```

### For Test Applications

```python
from src.core.testing.type_checker import RuntimePatternChecker

def test_my_app():
    app = build_test_app()
    
    # Validate the app before using it
    warnings = RuntimePatternChecker.validate_test_app(app)
    if warnings:
        for warning in warnings:
            print(f"Warning: {warning}")
```

## Development Tools

### Static Analysis

Run the static analyzer on your test files:

```bash
python -m src.core.testing.type_checker tests/
```

This will catch common patterns that lead to coroutine warnings.

### Pre-commit Hook

Install the pre-commit hook to catch issues before they're committed:

```bash
# Add to .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: async-sync-checker
        name: Check async/sync patterns
        entry: python -m src.core.testing.type_checker
        language: python
        files: "test.*\\.py$"
```

### Runtime Validation

Add runtime validation to your test fixtures:

```python
@pytest.fixture
def validated_app():
    app = build_test_app()
    
    # Automatic validation
    warnings = RuntimePatternChecker.validate_test_app(app)
    for warning in warnings:
        pytest.warns(UserWarning, match=warning)
        
    return app
```

## Common Patterns and Solutions

### Problem: Session Service Returns AsyncMock

```python
# [X] PROBLEM
mock_session_service = AsyncMock(spec=ISessionService)
# When test calls session_service.get_session(), it gets an AsyncMock
# which causes "coroutine was never awaited" warning

# [OK] SOLUTION
mock_session_service = EnforcedMockFactory.create_session_service_mock()
# This ensures get_session() returns real Session objects
```

### Problem: Mixed Async/Sync Interface

```python
# [X] PROBLEM
mock_service = AsyncMock(spec=IMixedService)
# All methods return coroutines, even sync ones

# [OK] SOLUTION
wrapper = SafeAsyncMockWrapper(spec=IMixedService)
wrapper.mark_method_as_sync('sync_method', return_value=real_value)
# Now sync_method returns real_value, async methods return coroutines
```

### Problem: Controller Returns AsyncMock

```python
# [X] PROBLEM - Controller stage registers AsyncMock controllers
services.add_instance(ChatController, AsyncMock(spec=ChatController))

# [OK] SOLUTION - Use ValidatedTestStage with proper factories
class MyControllerStage(ValidatedTestStage):
    async def _register_services(self, services, config):
        # Create real controller with mocked dependencies
        request_processor = self.create_safe_backend_service_mock()
        controller = ChatController(request_processor)
        self.safe_register_instance(services, ChatController, controller)
```

## Error Messages and Hints

The framework provides helpful error messages:

```
Session service validation failed for MockSessionService: 
Session service MockSessionService returns AsyncMock from get_session(), 
which will cause coroutine warnings. Use a real Session object or properly 
configured mock instead.

HINT: Use EnforcedMockFactory.create_session_service_mock() instead of 
creating AsyncMock directly.
```

## Migration Guide

### Migrating Existing Test Stages

1. Change base class:
   ```python
   # Before
   class MyStage(InitializationStage):
   
   # After  
   class MyStage(ValidatedTestStage):
   ```

2. Move service registration to `_register_services()`:
   ```python
   # Before
   async def execute(self, services, config):
       mock = AsyncMock(spec=IService)
       services.add_instance(IService, mock)
   
   # After
   async def _register_services(self, services, config):
       mock = self.create_safe_session_service_mock()
       self.safe_register_instance(services, IService, mock)
   ```

3. Use safe factories instead of direct AsyncMock creation

### Migrating Existing Tests

1. Add the mixin to test classes:
   ```python
   class TestMyService(GuardedMockCreationMixin):
   ```

2. Replace direct mock creation:
   ```python
   # Before
   mock = AsyncMock(spec=IService)
   
   # After
   mock = self.create_async_mock(spec=IService)
   ```

## Summary

This framework prevents coroutine warnings by:

1. **Enforcing proper async/sync separation** through base classes
2. **Providing safe factories** for common problematic services  
3. **Validating at registration time** to catch issues early
4. **Giving helpful error messages** to guide toward correct solutions
5. **Providing development tools** to catch issues before they cause problems

The key insight is that **session services and similar interfaces have synchronous methods that must return real objects, not coroutines**. By using this framework, coding agents automatically get protection against these subtle but common issues.
