# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an LLM Interactive Proxy - a Swiss-army knife for language model development and agentic workflows. It's a gateway that sits between LLM clients and backends (OpenAI, Anthropic, Gemini, etc.), providing protocol conversion, loop detection, API key rotation, failover routing, and in-chat command capabilities.

## Build and Development Commands

### Testing
```bash
# Run all tests
pytest

# Run with specific markers
pytest -m "integration"          # Integration tests only
pytest -m "unit"                # Unit tests only  
pytest -m "not network"         # Exclude network tests
pytest -m "loop_detection"      # Loop detection tests
pytest -m "di"                 # Dependency injection tests

# Run specific test file
pytest tests/unit/test_proxy_logic.py

# Run with verbose output and coverage
pytest --cov=src --cov-report=html
```

### Code Quality
```bash
# Format code (Black)
black src/ tests/

# Lint with Ruff
ruff check src/ tests/

# Lint with Ruff (auto-fix)
ruff check src/ tests/ --fix

# Type checking
mypy src/ tests/

# Find dead code
vulture src/ --min-confidence 70
```

### Running the Application
```bash
# Start the proxy server
python src/core/cli.py

# With specific backend
python src/core/cli.py --default-backend openrouter

# With custom host/port
python src/core/cli.py --host 0.0.0.0 --port 8080

# With logging
python src/core/cli.py --log proxy.log
```

## Architecture Overview

### Core Design Patterns
- **SOLID Principles**: Clean architecture with dependency injection
- **Dependency Injection**: Services registered in `src/core/di/services.py`
- **Repository Pattern**: Data access through interfaces in `src/core/interfaces/`
- **Command Pattern**: In-chat commands in `src/core/domain/commands/`
- **Factory Pattern**: Backend creation via `BackendFactory`

### Application Structure
```
src/
├── core/                    # Application core (SOLID architecture)
│   ├── app/               # Application layer and FastAPI setup
│   ├── domain/            # Business logic and domain models
│   ├── services/          # Service implementations
│   ├── interfaces/        # Interface definitions
│   ├── di/                # Dependency injection container
│   └── config/            # Configuration management
├── connectors/             # Backend connectors (OpenAI, Anthropic, etc.)
├── loop_detection/        # Loop detection algorithms
└── cli.py                 # Main CLI entry point
```

### Key Components

#### Dependency Injection System
Services are registered in `src/core/di/services.py` using the `ServiceCollection`:
- Singleton services: `add_singleton()`
- Factory services: `add_singleton_factory()`
- Instance services: `add_instance()`

#### Backend Service Architecture
- `IBackendService`: Main interface for backend operations
- `BackendFactory`: Creates backend instances with API key rotation
- `FailoverService`: Handles backend failover logic
- Rate limiting via `RateLimiter` service

#### Loop Detection
- Content-based: Hash-based pattern matching in streaming responses
- Tool call: Detects repetitive tool calls with TTL-based pruning
- Configurable per session via `!/set(loop-detection=true/false)`

#### Command System
- Prefix-based (default `!`) for in-chat commands
- Extensible via `BaseCommand` class in `src/core/domain/commands/`
- Dependency injection through `IServiceProvider`

### Configuration Management
- Immutable configuration objects in `src/core/domain/configuration/`
- Environment-based with `.env` file support
- Runtime configuration via commands
- Backend-specific configurations with failover routing

### Testing Architecture
- Unit tests in `tests/unit/`
- Integration tests in `tests/integration/` 
- Mock service provider in `tests/conftest.py`
- Test markers for selective test execution

## Key Development Guidelines

### Adding New Backend
1. Create connector in `src/connectors/`
2. Register backend in `src/core/services/backend_imports.py`
3. Add to `BackendRegistry`
4. Implement `IBackendService` interface

### Adding New Command
1. Extend `BaseCommand` class
2. Register in `src/core/services/command_registration.py`
3. Add dependency injection validation
4. Add unit tests with proper mocking

### Service Registration Pattern
```python
# For stateless commands
def _register_stateless_command(services: ServiceCollection, registry: CommandRegistry, command_type: type[BaseCommand]) -> None:
    services.add_singleton_factory(ICommand, command_type)

# For stateful commands  
def _register_stateful_command_with_di(services: ServiceCollection, registry: CommandRegistry, command_type: type[BaseCommand]) -> None:
    services.add_singleton_factory(ICommand, lambda provider: command_type(provider))
```

### Testing Commands
- Use `setup_test_command_registry()` from `tests/conftest.py`
- Provide mock dependencies via service provider
- Validate DI usage with `self._validate_di_usage()` in commands

## Backend Configuration

### API Key Rotation
Support numbered keys for rotation: `OPENAI_API_KEY_1`, `OPENAI_API_KEY_2`, etc.

### Failover Routes
Create failover routes with policies (k, m, km, mk):
```bash
!/create-failover-route(name=myroute, policy=m)
!/route-append(name=myroute, element=openrouter:gpt-4)
!/route-append(name=myroute, element=openrouter:claude-3)
!/set(model=myroute)
```

### Protocol Conversion
- OpenAI client ↔ Any backend (automatic)
- Anthropic client ↔ Gemini, OpenRouter, etc.
- Gemini client ↔ OpenAI-compatible APIs

## Environment Variables

### Core Configuration
- `LLM_BACKEND`: Default backend
- `LOOP_DETECTION_ENABLED`: Global loop detection toggle
- `TOOL_LOOP_DETECTION_ENABLED`: Tool loop detection toggle
- `LLM_INTERACTIVE_PROXY_API_KEY`: Client API key

### Backend Keys
- `OPENAI_API_KEY`, `OPENAI_API_KEY_1`, `OPENAI_API_KEY_2`
- `GEMINI_API_KEY`, `GEMINI_API_KEY_1`, `GEMINI_API_KEY_2`
- `OPENROUTER_API_KEY`, `OPENROUTER_API_KEY_1`, `OPENROUTER_API_KEY_2`
- `ZAI_API_KEY`, `ZAI_API_KEY_1`, `ZAI_API_KEY_2`
- `ANTHROPIC_API_KEY`, `ANTHROPIC_API_KEY_1`, `ANTHROPIC_API_KEY_2`

### Testing
- `PYTEST_CURRENT_TEST`: Automatically detected during pytest execution
- Test mocks are automatically set up in `tests/conftest.py`