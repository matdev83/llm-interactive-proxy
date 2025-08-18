# WARP.md

## Repository Overview

The LLM Interactive Proxy is a sophisticated middleware service that sits between clients and various LLM backends (OpenAI, Anthropic, Gemini, etc.), providing enhanced features like command processing, rate limiting, failover, and unified API access. It follows a clean, SOLID architecture with dependency injection.

## Key Development Commands

### Environment Setup
```bash
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Unix

# Install dependencies (always use pyproject.toml)
pip install -e .[dev]
```

### Running the Server
```bash
# Development mode with debug logging
.\.venv\Scripts\python.exe src/core/cli.py --log-level DEBUG

# With specific backend
.\.venv\Scripts\python.exe src/core/cli.py --default-backend openai

# With configuration file
.\.venv\Scripts\python.exe src/core/cli.py --config config.yaml
```

### Testing Commands
```bash
# Run all tests (excludes integration tests by default)
.\.venv\Scripts\python.exe -m pytest

# Run tests with coverage
.\.venv\Scripts\python.exe -m pytest --cov=src/

# Run specific test module
.\.venv\Scripts\python.exe -m pytest tests/unit/core/test_backend_service.py

# Run integration tests
.\.venv\Scripts\python.exe -m pytest -m integration

# Run tests for a specific file after modifications
.\.venv\Scripts\python.exe -m pytest tests/unit/core/test_backend_service_enhanced.py -v
```

### Code Quality (MANDATORY after Python file edits)
After editing any Python file, you MUST run these quality assurance commands:

```bash
.\.venv\Scripts\python.exe -m ruff check --fix <modified_filename> && .\.venv\Scripts\python.exe -m black <modified_filename> && .\.venv\Scripts\python.exe -m mypy <modified_filename>
```

Example:
```bash
.\.venv\Scripts\python.exe -m ruff check --fix src/core/services/backend_service.py && .\.venv\Scripts\python.exe -m black src/core/services/backend_service.py && .\.venv\Scripts\python.exe -m mypy src/core/services/backend_service.py
```

### Development Tools
```bash
# Restart service (if running as daemon)
.\.venv\Scripts\python.exe -m dev.tools.restart_service

# Test API requests
.\.venv\Scripts\python.exe -m dev.tools.test_request

# Analyze logs
.\.venv\Scripts\python.exe -m dev.tools.analyze_logs
```

## Architecture Overview

The application follows a layered SOLID architecture with dependency injection:

### Core Layers
- **Interface Layer** (`src/core/interfaces/`): Abstract contracts for all services
- **Domain Layer** (`src/core/domain/`): Business models and value objects (immutable Pydantic models)
- **Application Layer** (`src/core/app/`): API controllers, middleware, and application orchestration
- **Service Layer** (`src/core/services/`): Business logic implementations
- **Infrastructure Layer** (`src/core/repositories/`, `src/connectors/`): Data access and external systems

### Key Components

#### Configuration System
- **Type-safe, immutable configuration** using Pydantic models
- **Interface-based design**: Services depend on `IBackendConfig`, `IReasoningConfig`, `ILoopDetectionConfig`
- **Builder pattern**: Use `with_*` methods to create modified configuration copies
- **Layered precedence**: Environment variables → Config files → Runtime commands

#### Dependency Injection
- **ServiceCollection**: Registers services with their interfaces
- **ServiceProvider**: Resolves service dependencies at runtime
- **Container**: Manages service lifecycles (singleton, transient, scoped)

#### Backend System
- **Multi-protocol support**: OpenAI, Anthropic, Gemini, OpenRouter, ZAI, Qwen OAuth
- **Protocol conversion**: Any client can connect to any backend
- **Failover routing**: Automatic fallback between models/backends
- **Rate limiting**: Built-in rate limit handling and key rotation

#### Command System
- **In-chat commands**: Control proxy behavior via `!/command` syntax
- **Command handlers**: Modular command processing with standardized interfaces
- **Session management**: Per-session configuration and state

#### Loop Detection
- **Content loop detection**: Hash-based streaming loop detection
- **Tool call loop detection**: Prevents repetitive tool calls with identical parameters
- **Configurable**: TTL-based pruning, multiple intervention modes

## Working with the Code

### Adding New Services
1. Define interface in `src/core/interfaces/`
2. Implement service in `src/core/services/`
3. Register in `src/core/app/application_factory.py`
4. Use through dependency injection

### Adding New Backends
1. Create connector in `src/connectors/` inheriting from `LLMBackend`
2. Register with `BackendFactory`
3. Add configuration options
4. Update CLI arguments and environment handling

### Adding New Commands
1. Create handler in `src/core/commands/handlers/`
2. Implement `ICommandHandler` interface
3. Register in `HandlerFactory`
4. Add tests in `tests/unit/core/commands/`

### Configuration Management
Configuration objects are immutable. To modify:

```python
# ❌ This will raise an error (frozen instance)
config.model = "new-model"

# ✅ Use builder methods instead
updated_config = config.with_model("new-model")

# ✅ Chain modifications
final_config = config.with_backend("anthropic").with_model("claude-3")
```

### Testing Strategy
1. **Unit tests** for individual components (`tests/unit/`)
2. **Integration tests** for component interaction (`tests/integration/`)
3. **Regression tests** for bug fixes
4. **Mock services** using dependency injection
5. **Test fixtures** in `conftest.py` for common setup

### Domain Models
All domain models are **immutable** (frozen Pydantic models):
- Use `model_copy(update={...})` for modifications
- Implement specific interfaces for type safety
- Follow value object patterns for data integrity

## Common Development Patterns

### Service Implementation
```python
class MyService(IMyService):
    def __init__(self, dependency: IDependency):
        self._dependency = dependency
    
    async def process(self, data: str) -> str:
        # Implementation
        return await self._dependency.transform(data)
```

### Configuration Usage
```python
def my_function(config: IBackendConfig):
    backend_type = config.backend_type
    model = config.model
    # Use configuration values
```

### Error Handling
- Use custom exceptions from `src/core/common/exceptions.py`
- Provide meaningful error messages
- Log errors with appropriate context using structured logging

## Testing Requirements

### Test Execution Order
1. **Run tests for modified files first** - Fix until green
2. **Run related test groups** - Fix until green  
3. **Run full test suite for milestones** - Fix related issues until green

### Quality Assurance
- All Python files must pass ruff, black, and mypy checks
- Tests must have proper coverage
- Integration tests verify end-to-end functionality

## Key Files and Directories

- `src/core/cli.py` - Main application entry point
- `src/core/app/application_factory.py` - FastAPI app creation and DI setup
- `src/core/services/` - Core business logic implementations
- `src/connectors/` - Backend integrations (OpenAI, Anthropic, etc.)
- `src/core/domain/` - Immutable business models
- `tests/conftest.py` - Global test fixtures and configuration
- `pyproject.toml` - Project dependencies and tool configuration

## Backend Support

### Supported Backends
- **OpenAI**: Standard OpenAI API
- **OpenRouter**: Model aggregation service  
- **Anthropic**: Claude models via Messages API
- **Gemini**: Google's Generative AI models
- **ZAI**: Zhipu AI integration
- **Qwen OAuth**: Alibaba's Qwen models with OAuth authentication

### Protocol Conversion
The proxy normalizes requests internally, enabling any frontend to work with any backend:
- OpenAI client → Gemini backend
- Anthropic SDK → OpenRouter models
- Gemini client → OpenAI models

## Configuration Examples

### Environment Variables
```bash
# Backend configuration
OPENAI_API_KEY="your_key"
ANTHROPIC_API_KEY="your_key"
GEMINI_API_KEY_1="first_key"
GEMINI_API_KEY_2="second_key"  # Key rotation support

# Loop detection
LOOP_DETECTION_ENABLED=true
TOOL_LOOP_DETECTION_ENABLED=true
TOOL_LOOP_MAX_REPEATS=4

# Server settings
LLM_INTERACTIVE_PROXY_API_KEY="proxy_auth_key"
LLM_BACKEND="openai"
```

### YAML Configuration
```yaml
backends:
  default_backend: "openai"
  openai:
    api_key: "your_key"
    
session:
  default_interactive_mode: true
  
loop_detection:
  loop_detection_enabled: true
  tool_loop_detection_enabled: true
```

## Development Best Practices

1. **Follow SOLID principles** - Single responsibility, dependency inversion
2. **Use interfaces** - Depend on abstractions, not implementations  
3. **Write tests first** - TDD approach for better design
4. **Immutable data** - Use frozen Pydantic models for domain objects
5. **Dependency injection** - Register and resolve services through DI container
6. **Quality checks** - Always run ruff, black, and mypy after code changes
7. **Configuration via interfaces** - Use `IBackendConfig`, `IReasoningConfig` etc.
8. **Structured logging** - Use `src.core.common.logging` utilities

## Debugging and Troubleshooting

### Common Issues
- **ServiceNotFound**: Check service registration in DI container
- **Configuration problems**: Verify environment variables and config file format
- **Backend issues**: Check API keys and network connectivity
- **Test failures**: Ensure proper test isolation and fixture usage

### Debug Mode
```bash
.\.venv\Scripts\python.exe src/core/cli.py --log-level DEBUG
```

This will provide detailed logging for request/response processing, backend communication, and internal service operations.
