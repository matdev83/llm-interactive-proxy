# Testing

This guide covers the testing strategy, test execution, and best practices for the LLM Interactive Proxy.

## Testing Philosophy

The project follows Test-Driven Development (TDD) principles:

1. Write tests first
2. Run tests to confirm they fail
3. Implement minimal code to pass tests
4. Refactor while keeping tests green
5. Repeat

## Test Structure

Tests are organized by type and mirror the source code structure:

```
tests/
├── unit/                   # Unit tests (fast, isolated)
├── integration/            # Integration tests (slower, multiple components)
├── property/               # Property-based tests (Hypothesis)
├── regression/             # Regression tests (bug fixes)
├── simulation/             # Simulation tests (wire capture replay)
├── behavior/               # Behavior tests (end-to-end scenarios)
├── performance/            # Performance tests (benchmarks)
├── fixtures/               # Test fixtures
├── mocks/                  # Mock objects
├── helpers/                # Test helpers
└── conftest.py             # Pytest configuration
```

## Running Tests

### All Tests

```bash
# Run all tests
./.venv/Scripts/python.exe -m pytest

# Run with verbose output
./.venv/Scripts/python.exe -m pytest -v

# Run with coverage
./.venv/Scripts/python.exe -m pytest --cov=src --cov-report=html
```

### Specific Test Types

```bash
# Run only unit tests
./.venv/Scripts/python.exe -m pytest tests/unit/

# Run only integration tests
./.venv/Scripts/python.exe -m pytest tests/integration/

# Run only property-based tests
./.venv/Scripts/python.exe -m pytest tests/property/
```

### Specific Test Files or Functions

```bash
# Run specific test file
./.venv/Scripts/python.exe -m pytest tests/unit/test_file.py

# Run specific test function
./.venv/Scripts/python.exe -m pytest tests/unit/test_file.py::test_function_name

# Run tests matching pattern
./.venv/Scripts/python.exe -m pytest -k "test_pattern"
```

### Test Options

```bash
# Stop on first failure
./.venv/Scripts/python.exe -m pytest -x

# Show local variables on failure
./.venv/Scripts/python.exe -m pytest -l

# Run tests in parallel (requires pytest-xdist)
./.venv/Scripts/python.exe -m pytest -n auto

# Show slowest tests
./.venv/Scripts/python.exe -m pytest --durations=10
```

## Test Types

### Unit Tests

Unit tests verify individual functions, classes, or modules in isolation.

**Characteristics**:

- Fast execution (< 1 second per test)
- No external dependencies
- Use mocks for dependencies
- Test single responsibility

**Example**:

```python
def test_model_name_rewrite():
    """Test that model name rewriting works correctly."""
    rewriter = ModelNameRewriter(rules=[
        {"pattern": "gpt-4", "replacement": "gpt-4-turbo"}
    ])
    
    result = rewriter.rewrite("gpt-4")
    
    assert result == "gpt-4-turbo"
```

**Location**: `tests/unit/`

### Integration Tests

Integration tests verify that multiple components work together correctly.

**Characteristics**:

- Slower execution (1-10 seconds per test)
- May use real dependencies
- Test component interactions
- May require setup/teardown

**Example**:

```python
@pytest.mark.asyncio
async def test_backend_connector_integration():
    """Test that backend connector integrates with HTTP client."""
    connector = OpenAIConnector(api_key="test-key")
    
    async with httpx.AsyncClient() as client:
        response = await connector.chat_completion(
            client=client,
            messages=[{"role": "user", "content": "Hello"}]
        )
    
    assert response.choices[0].message.content
```

**Location**: `tests/integration/`

### Property-Based Tests

Property-based tests use Hypothesis to generate test cases and verify universal properties.

**Characteristics**:

- Generates many test cases automatically
- Finds edge cases you might miss
- Tests properties that should always hold
- Provides minimal failing examples

**Example**:

```python
from hypothesis import given, strategies as st

@given(st.text())
def test_api_key_redaction_property(api_key: str):
    """Test that API key redaction works for any string."""
    redacted = redact_api_key(api_key)
    
    # Property: redacted string should not contain original key
    assert api_key not in redacted or len(api_key) < 8
```

**Location**: `tests/property/`

### Regression Tests

Regression tests verify that previously fixed bugs don't reoccur.

**Characteristics**:

- Test specific bug scenarios
- Include issue/PR references
- Prevent regressions
- Document historical issues

**Example**:

```python
def test_issue_123_model_override_bug():
    """
    Regression test for issue #123.
    
    Bug: Model override was not applied when using force-model flag.
    Fixed in PR #124.
    """
    config = Config(force_model="gpt-4")
    request = ChatRequest(model="gpt-3.5-turbo")
    
    resolved_model = resolve_model(request, config)
    
    assert resolved_model == "gpt-4"
```

**Location**: `tests/regression/`

### Simulation Tests

Simulation tests replay captured wire traffic to verify behavior.

**Characteristics**:

- Use real captured traffic
- Test end-to-end flows
- Verify protocol compatibility
- Useful for debugging

**Example**:

```python
def test_replay_openai_request():
    """Test replaying captured OpenAI request."""
    capture = load_capture("var/wire_captures_cbor/openai_chat.cbor")
    
    response = replay_request(capture.entries[0])
    
    assert response.status_code == 200
```

**Location**: `tests/simulation/`

## Test Fixtures

Fixtures provide reusable test data and setup:

```python
# conftest.py
import pytest

@pytest.fixture
def sample_chat_request():
    """Provide a sample chat request for tests."""
    return {
        "model": "gpt-4",
        "messages": [
            {"role": "user", "content": "Hello"}
        ]
    }

@pytest.fixture
async def http_client():
    """Provide an HTTP client for tests."""
    async with httpx.AsyncClient() as client:
        yield client
```

**Usage**:

```python
def test_with_fixture(sample_chat_request):
    """Test using fixture."""
    assert sample_chat_request["model"] == "gpt-4"
```

## Mocking

Use mocks to isolate components and control dependencies:

```python
from unittest.mock import Mock, patch

def test_with_mock():
    """Test using mock."""
    mock_client = Mock()
    mock_client.post.return_value = Mock(status_code=200)
    
    connector = OpenAIConnector(api_key="test")
    response = connector.send_request(mock_client, data={})
    
    assert response.status_code == 200
    mock_client.post.assert_called_once()
```

**Patching**:

```python
@patch('src.connectors.openai.httpx.AsyncClient')
async def test_with_patch(mock_client_class):
    """Test using patch."""
    mock_client = Mock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    
    connector = OpenAIConnector(api_key="test")
    await connector.chat_completion(messages=[])
    
    mock_client.post.assert_called()
```

## Test Coverage

### Measuring Coverage

```bash
# Run tests with coverage
./.venv/Scripts/python.exe -m pytest --cov=src

# Generate HTML coverage report
./.venv/Scripts/python.exe -m pytest --cov=src --cov-report=html

# View coverage report
# Open htmlcov/index.html in browser
```

### Coverage Goals

- **Overall**: Aim for 80%+ coverage
- **Core Logic**: Aim for 90%+ coverage
- **Critical Paths**: Aim for 100% coverage
- **UI/CLI**: 60%+ coverage acceptable

### Coverage Exclusions

Some code is excluded from coverage requirements:

- Debug code
- Type checking blocks (`if TYPE_CHECKING:`)
- Abstract methods
- Platform-specific code

## Test Best Practices

### Writing Good Tests

1. **One Assertion Per Test**: Each test should verify one thing
2. **Descriptive Names**: Test names should describe what they test
3. **Arrange-Act-Assert**: Structure tests clearly
4. **Independent Tests**: Tests should not depend on each other
5. **Fast Tests**: Keep unit tests fast (< 1 second)

### Test Naming

```python
# Good test names
def test_model_rewrite_applies_first_matching_rule():
    pass

def test_api_key_validation_rejects_empty_string():
    pass

def test_streaming_response_yields_chunks_in_order():
    pass

# Bad test names
def test_model():
    pass

def test_api_key():
    pass

def test_streaming():
    pass
```

### Arrange-Act-Assert Pattern

```python
def test_example():
    # Arrange: Set up test data and dependencies
    config = Config(force_model="gpt-4")
    request = ChatRequest(model="gpt-3.5-turbo")
    
    # Act: Execute the code being tested
    result = resolve_model(request, config)
    
    # Assert: Verify the result
    assert result == "gpt-4"
```

### Async Tests

Use `pytest.mark.asyncio` for async tests:

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    """Test async function."""
    result = await some_async_function()
    assert result == expected_value
```

## Debugging Tests

### Running Tests in Debug Mode

```bash
# Run with Python debugger
./.venv/Scripts/python.exe -m pytest --pdb

# Drop into debugger on failure
./.venv/Scripts/python.exe -m pytest --pdb --pdbcls=IPython.terminal.debugger:Pdb
```

### Print Debugging

```python
def test_with_debug_output():
    """Test with debug output."""
    result = some_function()
    print(f"Debug: result = {result}")  # Will show in pytest output with -s
    assert result == expected
```

```bash
# Show print statements
./.venv/Scripts/python.exe -m pytest -s
```

### Logging in Tests

```python
import logging

def test_with_logging(caplog):
    """Test with logging."""
    with caplog.at_level(logging.DEBUG):
        some_function_that_logs()
    
    assert "Expected log message" in caplog.text
```

## Continuous Integration

Tests run automatically on every push via GitHub Actions:

- **Unit Tests**: Run on every commit
- **Integration Tests**: Run on every commit
- **Coverage**: Tracked with Codecov
- **Linting**: Ruff checks on every commit
- **Type Checking**: Mypy checks on every commit

See `.github/workflows/ci.yml` for CI configuration.

## Test Development Workflow

1. **Write Failing Test**:

   ```bash
   # Create test file
   # tests/unit/test_new_feature.py
   
   def test_new_feature():
       result = new_feature()
       assert result == expected
   ```

2. **Run Test (Should Fail)**:

   ```bash
   ./.venv/Scripts/python.exe -m pytest tests/unit/test_new_feature.py::test_new_feature
   ```

3. **Implement Feature**:

   ```python
   # src/module.py
   
   def new_feature():
       return expected
   ```

4. **Run Test (Should Pass)**:

   ```bash
   ./.venv/Scripts/python.exe -m pytest tests/unit/test_new_feature.py::test_new_feature
   ```

5. **Run All Tests**:

   ```bash
   ./.venv/Scripts/python.exe -m pytest
   ```

6. **Check Coverage**:

   ```bash
   ./.venv/Scripts/python.exe -m pytest --cov=src
   ```

## Troubleshooting

### Tests Failing Locally But Passing in CI

- Check Python version matches CI
- Check dependency versions
- Check for platform-specific code
- Check for timing issues

### Tests Passing Locally But Failing in CI

- Check for test interdependencies
- Check for file system assumptions
- Check for network dependencies
- Check for race conditions

### Slow Tests

- Profile tests with `--durations=10`
- Move slow tests to integration suite
- Use mocks to avoid real I/O
- Run tests in parallel with `-n auto`

### Flaky Tests

- Identify with `pytest --count=100`
- Check for race conditions
- Check for timing assumptions
- Add retries for network tests

## Related Documentation

- **Building**: See [building.md](building.md) for build instructions
- **Contributing**: See [contributing.md](contributing.md) for contribution workflow
- **Code Organization**: See [code-organization.md](code-organization.md) for project structure
- **Coding Standards**: See [AGENTS.md](../../AGENTS.md) for coding standards and testing guidelines
