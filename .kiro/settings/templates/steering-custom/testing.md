# Testing Standards

[Purpose: guide what to test, where tests live, and how to structure them]

## Philosophy
- **Test behavior, not implementation** - Focus on outcomes, not internal mechanics
- **TDD (Test-Driven Development)** - Write test first (Red), implement (Green), refactor
- **Fast, reliable tests** - Minimize brittle mocks, prefer dependency injection
- **Cover critical paths deeply** - Breadth over 100% pursuit

## Organization

**Location**: Tests mirror source structure
- Source: `src/core/services/backend_service.py`
- Tests: `tests/unit/core/services/test_backend_service.py`

**Naming**:
- Files: `test_*.py` (pytest convention)
- Test classes: `Test[ComponentName]` (optional grouping)
- Test functions: `test_[behavior]_[condition]`

## Test Types

### Unit Tests (`tests/unit/`)
**Purpose**: Test individual units in isolation
- **What**: Single class/function with mocked dependencies
- **How**: Mock via DI container or `unittest.mock`
- **Speed**: Very fast (< 1ms per test)
- **Example**:
  ```python
  def test_backend_service_routes_to_healthy_backend(mock_backend_factory):
      service = BackendService(mock_backend_factory)
      result = await service.route_request(request)
      assert result.backend_name == "healthy_backend"
  ```

### Integration Tests (`tests/integration/`)
**Purpose**: Test multiple components together
- **What**: Service wiring via DI, controller flows, middleware chains
- **How**: Real DI container, mock only external APIs
- **Speed**: Fast (< 100ms per test)
- **Example**:
  ```python
  def test_chat_controller_with_backend_failover(test_client):
      response = test_client.post("/v1/chat/completions", json=payload)
      assert response.status_code == 200
  ```

### Property Tests (`tests/property/`)
**Purpose**: Verify invariants under random inputs
- **What**: State machines, serialization, transformations
- **How**: Hypothesis library
- **Speed**: Medium (runs many examples)
- **Example**:
  ```python
  @given(st.text())
  def test_serialization_roundtrip(input_text):
      serialized = serialize(input_text)
      assert deserialize(serialized) == input_text
  ```

### Behavior Tests (`tests/behavior/`)
**Purpose**: Test user scenarios and workflows
- **What**: End-to-end flows, multi-step interactions
- **How**: Full application stack, real configurations
- **Speed**: Slow (seconds per test)

## Structure (AAA Pattern)

```python
async def test_backend_service_fails_over_on_rate_limit():
    # Arrange
    primary = MockBackend(rate_limited=True)
    fallback = MockBackend(rate_limited=False)
    service = BackendService([primary, fallback])
    
    # Act
    result = await service.route_request(request)
    
    # Assert
    assert result.backend_name == fallback.name
    assert result.status_code == 200
```

## Mocking & Data

### Mocking Strategy
- **External APIs**: Always mock (HTTP clients, LLM providers)
- **Internal services**: Use real implementations via DI when possible
- **Databases/Files**: Mock or use temporary test fixtures
- **Never mock the system under test**

### Test Fixtures
- Shared fixtures in `tests/conftest.py`
- Use factories for test data generation
- Reset state between tests (`pytest` does this automatically)

### Test Data
- Keep minimal and intention-revealing
- Use realistic but simplified examples
- No production data in tests

## Coverage

### Targets
- **Overall**: Meaningful coverage of critical paths, not arbitrary percentages
- **Critical domains**: Backend routing, error handling, authentication
- **Enforcement**: CI fails on regressions, not absolute thresholds

### What to Cover
- Happy path (expected behavior)
- Error cases (exception handling)
- Edge cases (boundary conditions)
- Integration points (DI wiring, middleware)

### What to Skip
- Third-party library internals
- Simple getters/setters
- Generated code

## Test Commands

```bash
# Fast suite (unit tests only)
./.venv/Scripts/python.exe -m pytest tests/unit/ -v

# Full suite
./.venv/Scripts/python.exe -m pytest

# With coverage
./.venv/Scripts/python.exe -m pytest --cov=src --cov-report=term-missing

# Specific test
./.venv/Scripts/python.exe -m pytest tests/unit/core/services/test_backend_service.py::test_failover -v

# Watch mode (requires pytest-watch)
./.venv/Scripts/python.exe -m pytest-watch
```

## CI/CD Integration

- Run fast tests on every commit
- Run full suite on PR
- Block merge on test failures
- Track coverage trends (not absolute thresholds)

---
_Focus on patterns and decisions. Tool-specific config lives in pyproject.toml_
