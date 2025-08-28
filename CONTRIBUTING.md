# Contributing to LLM Interactive Proxy

We welcome contributions to the LLM Interactive Proxy! This guide provides an overview of the development workflow, architectural guidelines, and best practices for contributing to the project.

## Development Workflow

### Setting Up Development Environment

1. **Clone the repository**:

    ```bash
    git clone https://github.com/matdev83/llm-interactive-proxy.git
    cd llm-interactive-proxy
    ```

2. **Create a virtual environment**:

    ```bash
    python -m venv .venv
    ```

3. **Activate the virtual environment**:
    - Windows: `.\.venv\Scripts\activate`
    - Unix: `source .venv/bin/activate`
4. **Install dependencies**:

    ```bash
    pip install -e .[dev]
    ```

5. **Create a `.env` file**: With your API keys (see `README.md` for details).

### Running the Application

```bash
# Run with default settings
python -m src.core.cli

# Run with custom configuration
python -m src.core.cli --config path/to/config.yaml

# Run with different backends
python -m src.core.cli --default-backend openrouter
python -m src.core.cli --default-backend gemini
python -m src.core.cli --default-backend gemini-cli-oauth-personal
python -m src.core.cli --default-backend anthropic
```

### Running Tests

```bash
# Run all tests
python -m pytest

# Run specific test file
python -m pytest tests/unit/test_backend_service.py

# Run with coverage
python -m pytest --cov=src
```

### Linting and Formatting

```bash
# Run ruff
python -m ruff check src

# Run black
python -m black src

# Run mypy
python -m mypy src
```

### Dependency Injection Container Usage Analysis

The project includes a comprehensive DI container usage scanner that analyzes the codebase for violations of dependency injection principles.

#### Running the DI Scanner

```bash
# Run the full DI violation test suite (shows concise warnings by default)
python -m pytest tests/unit/test_di_container_usage.py -v

# Run just the violation detection (shows concise warning + detailed report)
python -m pytest tests/unit/test_di_container_usage.py::TestDIContainerUsage::test_di_container_violations_are_detected -v -s

# Run with coverage to see scanner effectiveness
python -m pytest tests/unit/test_di_container_usage.py --cov=src --cov-report=term-missing
```

#### What the DI Scanner Detects

The scanner identifies violations where services are manually instantiated instead of using the DI container:

- **Manual Service Instantiation**: Direct instantiation of service classes (e.g., `BackendService()`, `CommandProcessor()`)
- **Controller Violations**: Controllers creating service instances directly
- **Factory Function Issues**: Factory functions that don't use the DI container properly
- **Business Logic Violations**: Business logic manually creating dependencies

#### Understanding Scanner Output

**Concise Summary (Default - Always Visible):**
```
⚠️  DI CONTAINER VIOLATIONS DETECTED: 61 violations in 14 files.
Most affected: core\di\services.py: 15, core\app\controllers\chat_controller.py: 8, core\app\controllers\anthropic_controller.py: 6.
Use -s flag for detailed report | Fix with IServiceProvider.get_required_service()
```

**Detailed Report (With -s Flag):**
```
🎯 DI Container Scanner Results:
   📊 Total violations found: 61
   📁 Files with violations: 14
   📋 Violation types:
      • manual_service_instantiation: 61
   📁 Top affected files:
      • core\di\services.py: 15 violations
      • core\app\controllers\chat_controller.py: 8 violations
```

#### Fixing DI Violations

**❌ Bad (Violation):**
```python
def handle_request(self, request):
    processor = CommandProcessor(self.config)  # VIOLATION!
    return processor.process(request)
```

**✅ Good (Fixed):**
```python
def __init__(self, command_processor: ICommandProcessor):
    self.command_processor = command_processor

def handle_request(self, request):
    return self.command_processor.process(request)  # CORRECT
```

#### Scanner Best Practices

- Run the DI scanner regularly during development
- Address violations as part of code reviews
- Use the scanner output to identify areas needing DI improvements
- Focus on high-impact violations first (controllers, business logic)
- Use `IServiceProvider.get_required_service()` for runtime resolution when needed

## Architecture Overview

The LLM Interactive Proxy follows a clean architecture approach based on SOLID principles:

- **S**ingle Responsibility Principle: Each class has one responsibility.
- **O**pen/Closed Principle: Open for extension, closed for modification.
- **L**iskov Substitution Principle: Subtypes must be substitutable for their base types.
- **I**nterface Segregation Principle: Clients shouldn't depend on methods they don't use.
- **D**ependency Inversion Principle: High-level modules depend on abstractions, not concrete implementations.

### Key Architectural Layers

1. **Interface Layer** (`src/core/interfaces/`): Defines contracts (abstract base classes) for services.
2. **Domain Layer** (`src/core/domain/`): Contains business entities and value objects; implements domain logic using immutable models.
3. **Application Layer** (`src/core/app/`): Orchestrates application flow, connects domain to infrastructure, contains controllers and middleware.
4. **Service Layer** (`src/core/services/`): Implements business use cases, orchestrates domain objects, depends on interfaces.
5. **Infrastructure Layer** (`src/core/repositories/`, `src/connectors/`): Implements interfaces, handles data storage and external services, provides adapters.

## Architecture Patterns and Best Practices

### 1. Interface-Driven Development

Define interfaces before implementations. Services interact through interfaces, enabling dependency inversion and clean testing.

### 2. Dependency Injection

Use a DI container to manage service dependencies, promoting loose coupling and easier testing.

### 3. Domain Models

Use immutable Pydantic models for core business entities to ensure data integrity and prevent accidental modifications. Use `.model_copy()` for modifications.

### 4. Command Pattern

Use command handlers for processing interactive commands.

### 5. Middleware Pipeline

Use middleware for cross-cutting concerns like response processing.

### 6. Repository Pattern

Use repositories for data access operations.

### 7. Factory Pattern

Use factories for creating complex objects, such as backend instances.

## Testing Guidelines

### 1. Unit Testing

Test individual components in isolation, using mock dependencies where necessary.

### 2. Integration Testing

Test how components work together, focusing on request-to-response flows.

### 3. End-to-End Testing

Test complete request flows to ensure overall system functionality.

### Testing with Dependency Injection Architecture

- **Integration Tests**: Use `setup_test_command_registry()` from `tests/conftest.py` to set up the DI command registry with mock dependencies.
- **Unit Tests**: Create mock dependencies and instantiate commands directly. For `CommandParser` tests, use mock commands from `tests/unit/mock_commands.py`.
- **Stateful Commands**: Create mock dependencies for `ISecureStateAccess` and `ISecureStateModification` and pass them to the command constructor.
- **Skipped Tests**: Update previously skipped tests to use the new DI-based commands.

### Testing OAuth Backends

OAuth backends like `gemini-cli-oauth-personal` have specific testing considerations:

- **Credential Mocking**: Use `pathlib.Path.home` patches to mock `~/.gemini/oauth_creds.json` location
- **Token Refresh**: Mock `_refresh_token_if_needed()` to test refresh behavior
- **Health Checks**: Test both successful and failed health check scenarios
- **File Operations**: Mock file I/O operations for credential loading/saving
- **Error Scenarios**: Test authentication errors, connectivity issues, and token expiration

Example OAuth backend test pattern:

```python
@patch('pathlib.Path.home')
@patch.object(OAuthConnector, '_refresh_token_if_needed', new_callable=AsyncMock)
async def test_oauth_backend_health_check(self, mock_refresh, mock_home):
    # Setup mock credentials file
    mock_home.return_value = Path("/tmp")
    # ... test implementation
```

## Code Quality

- **Code Style**: Follow PEP 8 with type hints, use Ruff for linting, and Black for formatting.

## Security and Redaction Guidelines

- **Never log secrets**: Do not print raw API keys, tokens, or credentials. Rely on the global logging redaction filter which sanitizes messages automatically.
- **Request redaction is mandatory**: Outbound prompts/messages are sanitized by the request redaction middleware. Do not re-introduce connector-specific redaction; keep redaction centralized and backend-agnostic.
- **Configuration**:
  - Prompt redaction is controlled by `auth.redact_api_keys_in_prompts` (default: true). CLI flag `--disable-redact-api-keys-in-prompts` disables it.
  - API keys are discovered from config (`auth.api_keys`, `backends.<name>.api_key`) and environment variables.
- **When modifying the request pipeline**: If you change `RequestProcessor`, `BackendRequestManager`, or middleware wiring, ensure the redaction step remains in the active path and add/update tests.
- **Tests**:
  - Unit tests exist for the middleware and processor redaction behavior.
  - Integration tests verify redaction for both streaming and non-streaming flows.
  - Run the full test suite after changes to avoid regressions.
- **SOLID Principles**: Adhere to SRP, OCP, LSP, ISP, and DIP.
- **DRY**: Avoid code duplication.
- **Test-Driven Development (TDD)**: Write tests first.
- **Error Handling**: Use specific exceptions and meaningful error messages.

## Contribution Process

1. **Create a feature branch**: `git checkout -b feature/your-feature`
2. **Write tests** for new functionality.
3. **Ensure all tests pass**: `pytest`
4. **Update documentation** as needed.
5. **Submit a Pull Request** with a clear description following the Conventional Commits format (`type(scope): subject`).
6. **Address review comments**.
7. **Merge after approval**.

## Additional Resources

- [CHANGELOG.md](CHANGELOG.md): Project Changelog.
- `docs/API_REFERENCE.md`: Detailed API documentation.
- `docs/ARCHITECTURE_GUIDE.md`: Comprehensive architecture guide.
- `docs/CONFIGURATION.md`: Configuration options.
- `docs/FAILOVER_ROUTES.md`: Failover routing information.
- `docs/TOOL_CALL_LOOP_DETECTION.md`: Tool call loop detection details.
### JSON Repair, Strict Gating, and Helpers

- JSON repair is applied both in streaming (processor) and non-streaming (middleware) paths.
- Strict mode (non-streaming) is enforced when:
  - `session.json_repair_strict_mode` is true, or
  - Content-Type is `application/json`, or
  - `expected_json=True` is present in middleware context/metadata, or
  - A `session.json_repair_schema` is configured.
- Convenience helpers (available for controllers/adapters):
  - `src/core/utils/json_intent.py#set_expected_json(metadata, True)`
  - `src/core/utils/json_intent.py#set_json_response_metadata(metadata, content_type='application/json; charset=utf-8')`
  - `#infer_expected_json(metadata, content)`
  - The ResponseProcessor auto-inferrs `expected_json` if not provided; you can override it via the helper.

### Processing Order (Streaming)

The streaming pipeline runs processors in this order by default:

1. JSON repair
2. Text loop detection
3. Tool-call repair
4. Middleware
5. Accumulation

This ordering ensures loop detection operates on human-visible text, tool-call repair uses normalized content, and downstream middleware sees consistent data.

### Metrics

- In-memory metrics in `src/core/services/metrics_service.py` record JSON repair outcomes for both streaming and non-streaming.
- Use `metrics.snapshot()` for ad-hoc debugging in tests.
