# Developer Guide

This guide provides an overview of how to work with the LLM Interactive Proxy codebase. It covers the key architectural concepts, development workflow, and best practices.

## Architecture Overview

The LLM Interactive Proxy follows a clean architecture approach based on SOLID principles:

- **S**ingle Responsibility Principle: Each class has one responsibility
- **O**pen/Closed Principle: Open for extension, closed for modification
- **L**iskov Substitution Principle: Subtypes must be substitutable for their base types
- **I**nterface Segregation Principle: Clients shouldn't depend on methods they don't use
- **D**ependency Inversion Principle: High-level modules depend on abstractions, not concrete implementations

### Key Architectural Layers

1. **Interface Layer** (`src/core/interfaces/`)
   - Contains interfaces (abstract base classes) that define contracts
   - Services interact with each other through these interfaces
   - Enables dependency inversion and clean testing

2. **Domain Layer** (`src/core/domain/`)
   - Contains business entities and value objects
   - Implements domain business logic
   - Free from infrastructure concerns
   - Uses immutable models (frozen Pydantic models) for data integrity

3. **Application Layer** (`src/core/app/`)
   - Orchestrates the flow of the application
   - Connects domain layer to infrastructure
   - Contains controllers and middleware

4. **Service Layer** (`src/core/services/`)
   - Implements the business use cases
   - Orchestrates domain objects to accomplish tasks
   - Depends on interfaces, not concrete implementations

5. **Infrastructure Layer** (`src/core/repositories/`, `src/connectors/`)
   - Implements interfaces defined in core
   - Handles data storage and external services
   - Adapters for third-party libraries and APIs
   
6. **Adapters Layer** (`src/core/adapters/`) - DEPRECATED
   - Previously connected the new architecture to the legacy code
   - This layer is now deprecated and will be removed in a future version
   - All functionality has been migrated to the new architecture

## Development Workflow

### Setting Up Development Environment

1. Clone the repository
2. Create a virtual environment: `python -m venv .venv`
3. Activate the virtual environment:
   - Windows: `.venv\Scripts\activate`
   - Unix: `source .venv/bin/activate`
4. Install dependencies: `pip install -e .[dev]`
5. Create a `.env` file with your API keys (see README.md)

### Running the Application

- Development mode: `python src/core/cli.py --debug`
- With specific configuration: `python src/core/cli.py --config config.yaml`
- With specific backend: `python src/core/cli.py --default-backend openai`

### Running Tests

- Run all tests: `pytest`
- Run with coverage: `pytest --cov=src/`
- Run specific tests: `pytest tests/unit/core/`

### Code Quality Tools

The codebase uses several tools to maintain code quality:

- **Ruff**: Linter for Python code
  - Run: `ruff check --fix src/`
- **Black**: Code formatter
  - Run: `black src/`
- **MyPy**: Static type checker
  - Run: `mypy src/`

You can run all these tools on a specific file after making changes:

```bash
./.venv/Scripts/python.exe -m ruff check --fix <file_path> && \
./.venv/Scripts/python.exe -m black <file_path> && \
./.venv/Scripts/python.exe -m mypy <file_path>
```

## Working with the Code

### Configuration Interfaces

The application uses a comprehensive configuration system based on interfaces and immutable value objects. This provides type safety, validation, and clear contracts between components.

#### Core Configuration Interfaces

**`IConfig`** - General configuration management:
```python
from src.core.interfaces.configuration import IConfig

class MyService:
    def __init__(self, config: IConfig):
        self._config = config
    
    def get_setting(self, key: str) -> Any:
        return self._config.get(key, "default_value")
```

**`IBackendConfig`** - Backend-specific settings:
```python
from src.core.interfaces.configuration import IBackendConfig

class BackendService:
    def __init__(self, backend_config: IBackendConfig):
        self._config = backend_config
    
    def get_api_url(self) -> str:
        return self._config.api_url or "https://api.default.com"
```

**`IReasoningConfig`** - AI reasoning parameters:
```python
from src.core.interfaces.configuration import IReasoningConfig

class ReasoningService:
    def __init__(self, reasoning_config: IReasoningConfig):
        self._config = reasoning_config
    
    def apply_reasoning_settings(self, request: dict) -> dict:
        if self._config.temperature is not None:
            request["temperature"] = self._config.temperature
        return request
```

**`ILoopDetectionConfig`** - Loop detection settings:
```python
from src.core.interfaces.configuration import ILoopDetectionConfig

class LoopDetector:
    def __init__(self, loop_config: ILoopDetectionConfig):
        self._config = loop_config
    
    def is_enabled(self) -> bool:
        return self._config.loop_detection_enabled
```

#### Configuration Value Objects

All configuration classes are immutable Pydantic models that implement the corresponding interfaces:

```python
from src.core.domain.configuration import BackendConfig, ReasoningConfig

# Create configuration
config = BackendConfig(
    backend_type="openai",
    model="gpt-4",
    interactive_mode=True
)

# Modify configuration (creates new instance)
updated_config = config.with_model("gpt-3.5-turbo")

# Chain modifications
final_config = config.with_backend("anthropic").with_model("claude-3")
```

### Dependency Injection

The application uses a dependency injection container to manage service instantiation and dependencies. This approach:

1. Reduces coupling between components
2. Makes testing easier with mocks and stubs
3. Simplifies configuration of complex object graphs

Example:

```python
# Registering a service
services = ServiceCollection()
services.add_singleton(IBackendService, BackendService)

# Resolving a service
provider = services.build_service_provider()
backend_service = provider.get_required_service(IBackendService)
```

### Adding a New Service

1. Define an interface in `src/core/interfaces/`
2. Implement the service in `src/core/services/`
3. Register the service in `src/core/app/application_factory.py`
4. Use the service through dependency injection

Example:

```python
# 1. Define interface (src/core/interfaces/my_service.py)
from abc import ABC, abstractmethod

class IMyService(ABC):
    @abstractmethod
    async def do_something(self, data: str) -> str:
        pass

# 2. Implement service (src/core/services/my_service.py)
from src.core.interfaces.my_service import IMyService

class MyService(IMyService):
    async def do_something(self, data: str) -> str:
        return f"Processed: {data}"

# 3. Register in application_factory.py
services.add_singleton(IMyService, MyService)

# 4. Use the service
class SomeConsumer:
    def __init__(self, my_service: IMyService):
        self._my_service = my_service
        
    async def process(self, data: str) -> str:
        return await self._my_service.do_something(data)
```

### Working with Immutable Domain Models

The domain models in `src/core/domain/` are immutable (frozen Pydantic models) to ensure data integrity and prevent accidental modifications. When you need to modify a domain object:

```python
# ❌ This will raise a ValidationError (frozen instance)
request.model = "new-model"

# ✅ Use model_copy() with updates instead
updated_request = request.model_copy(update={"model": "new-model"})

# ✅ For nested updates (like extra_body)
new_extra_body = request.extra_body.copy()
new_extra_body["backend_type"] = BackendType.OPENAI
updated_request = request.model_copy(update={"extra_body": new_extra_body})
```

### Adding a New Backend

1. Create a new backend connector in `src/connectors/`
2. Implement the `LLMBackend` abstract class
3. Update the `BackendFactory` to support the new backend
4. Add configuration options for the new backend

#### Backend Integration

For integrating with LLM backends:

1. Create a new backend implementation that inherits from `LLMBackend`
2. Register it with the `BackendFactory`
3. The factory will create the appropriate backend instance based on the request

Example:

```python
# Creating a new backend implementation
class MyCustomBackend(LLMBackend):
    def __init__(self, client: httpx.AsyncClient, api_key: str):
        self._client = client
        self._api_key = api_key
        
    async def chat_completions(self, request: dict, stream: bool) -> dict | AsyncIterator[dict]:
        # Implementation details...

# Registering with the backend factory
backend_factory = BackendFactory(client)
backend_factory.register_backend("my_custom", lambda: MyCustomBackend(client, api_key))
```

Note: The legacy adapter pattern is deprecated and will be removed in a future version.

### Adding a New Command

1. Create a command handler in `src/commands/`
2. Register the command in the command registry
3. Implement the command's execution logic

### Configuration Management

The application uses a layered configuration approach with immutable configuration objects:

1. Default values in code
2. Environment variables (from `.env` file or system)
3. Configuration files (YAML or JSON)
4. Runtime commands (e.g., `!/set(key=value)`)

#### Configuration Architecture

The new configuration system is built around immutable value objects that implement specific interfaces:

- **`IConfig`**: General configuration management interface
- **`IBackendConfig`**: Backend-specific configuration (backend type, model, API URL, etc.)
- **`IReasoningConfig`**: Reasoning parameters (effort, thinking budget, temperature)
- **`ILoopDetectionConfig`**: Loop detection settings (enabled flags, pattern lengths)

#### Configuration Classes

**Domain Models** (`src/core/domain/configuration.py`):
- `BackendConfig`: Immutable backend configuration
- `ReasoningConfig`: Immutable reasoning parameters
- `LoopDetectionConfig`: Immutable loop detection settings

**Key Features**:
- **Immutability**: All configuration objects are frozen Pydantic models
- **Type Safety**: Full type hints and validation
- **Builder Pattern**: Use `with_*` methods to create modified copies
- **Interface Compliance**: All classes implement their respective interfaces

#### Working with Configuration

```python
# Creating a new backend configuration
backend_config = BackendConfig(
    backend_type="openai",
    model="gpt-4",
    api_url="https://api.openai.com/v1"
)

# Modifying configuration (creates a new instance)
updated_config = backend_config.with_model("gpt-3.5-turbo")

# Configuration is immutable
# backend_config.model = "new-model"  # This would raise an error

# Use with_* methods instead
new_config = backend_config.with_backend("anthropic").with_model("claude-3")
```

#### Adding New Configuration Options

1. **Define the interface** in `src/core/interfaces/configuration.py`:
   ```python
   class IMyConfig(ABC):
       @property
       @abstractmethod
       def my_setting(self) -> str:
           pass
       
       @abstractmethod
       def with_my_setting(self, value: str) -> IMyConfig:
           pass
   ```

2. **Implement the domain model** in `src/core/domain/configuration.py`:
   ```python
   class MyConfig(ValueObject, IMyConfig):
       my_setting: str = "default_value"
       
       def with_my_setting(self, value: str) -> IMyConfig:
           return self.model_copy(update={"my_setting": value})
   ```

3. **Register with DI container** in the application factory
4. **Add environment variable handling** in the config loader
5. **Update documentation**

#### Configuration Adapters

For backward compatibility with legacy code, configuration adapters bridge the old and new systems:

- **`LegacyConfigAdapter`**: Wraps legacy config dictionaries to implement `IConfig`
- **Integration Bridge**: Manages coexistence during migration

#### Best Practices

1. **Always use interfaces** when depending on configuration
2. **Prefer immutable objects** over mutable dictionaries
3. **Use builder pattern** (`with_*` methods) for modifications
4. **Validate configuration** at startup, not at runtime
5. **Document configuration options** with clear descriptions and examples

## Testing

### Unit Tests

- Test individual components in isolation
- Use dependency injection to mock dependencies
- Focus on testing business logic, not implementation details

Example:

```python
def test_backend_service_call_completion():
    # Arrange
    mock_factory = Mock(spec=BackendFactory)
    mock_rate_limiter = Mock(spec=IRateLimiter)
    mock_backend = Mock(spec=LLMBackend)
    mock_factory.create_backend.return_value = mock_backend
    
    service = BackendService(mock_factory, mock_rate_limiter, {}, {})
    
    # Act
    result = await service.call_completion(test_request)
    
    # Assert
    mock_factory.create_backend.assert_called_once()
    mock_backend.chat_completions.assert_called_once()
    assert result is not None
```

### Integration Tests

- Test how components work together
- Use test fixtures from `conftest.py`
- Test request-to-response flow

Example:

```python
def test_chat_completions_endpoint(test_client):
    # Arrange
    request_data = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "Hello"}]
    }
    
    # Act
    response = test_client.post("/v1/chat/completions", json=request_data)
    
    # Assert
    assert response.status_code == 200
    assert "choices" in response.json()
```

## Best Practices

1. **Follow SOLID principles**
   - Keep classes focused on a single responsibility
   - Depend on abstractions, not concrete implementations
   - Use dependency injection

2. **Write tests first**
   - Use Test-Driven Development when possible
   - Ensure all code paths are covered
   - Write both unit and integration tests

3. **Document your code**
   - Use docstrings for classes and methods
   - Add type hints to improve readability and catch errors
   - Keep the README and documentation up to date

4. **Use consistent coding style**
   - Follow Black's formatting guidelines
   - Fix all linting warnings from Ruff
   - Address type checking issues from MyPy

5. **Error handling**
   - Use custom exceptions from `src/core/common/exceptions.py`
   - Provide meaningful error messages
   - Log errors with appropriate context

## Troubleshooting Common Issues

### Dependency Injection Issues

If you see `ServiceNotFound` exceptions:
- Check that the service is registered in the container
- Verify the correct interface is being requested
- Ensure the registration is in the right scope (singleton/transient)

### Configuration Problems

If configuration values aren't being applied:
- Check the precedence order (defaults → env vars → config file → runtime)
- Verify environment variables are correctly named
- Check configuration file format and location

### Backend Integration Issues

If backends aren't working:
- Verify API keys are properly configured
- Check network connectivity to the backend service
- Enable debug logging to see detailed request/response information

## Getting Help

- Check the GitHub issues for similar problems
- Review the test cases for examples of correct usage
- Consult the architecture documentation in `docs/`

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for information on how to contribute to the project.
