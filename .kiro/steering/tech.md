# Technology Stack

## Architecture

**Async Service Architecture** with Staged Initialization, Dependency Injection, and Adapter Pattern.

```
┌─────────────────────────────────────────────────────────────┐
│                   FastAPI Controllers                        │
│            (src/core/app/controllers/)                       │
├─────────────────────────────────────────────────────────────┤
│                    Service Layer                             │
│      (src/core/services/ - 30+ orchestration services)       │
├─────────────────────────────────────────────────────────────┤
│         Domain Models & Translation Logic                    │
│              (src/core/domain/)                              │
├─────────────────────────────────────────────────────────────┤
│          Backend Connectors (Adapter Pattern)                │
│              (src/connectors/ - 10+ providers)               │
├─────────────────────────────────────────────────────────────┤
│           DI Container & Interface Contracts                 │
│      (src/core/di/, src/core/interfaces/)                    │
└─────────────────────────────────────────────────────────────┘
```

## Core Technologies

- **Language**: Python 3.10+
- **Framework**: FastAPI (async)
- **Runtime**: uvicorn / hypercorn
- **HTTP Client**: httpx (async)
- **Validation**: Pydantic v2
- **Serialization**: CBOR (cbor2) for wire captures
- **Logging**: structlog (structured JSON)

## Key Libraries

| Library | Purpose | Pattern |
|---------|---------|---------|
| `fastapi` | Web framework | Async request handling, dependency injection |
| `httpx` | HTTP client | Async backend calls, connection pooling |
| `pydantic` | Data validation | Domain models, DTOs, runtime type checking |
| `cbor2` | Binary encoding | Wire capture serialization (byte-precise) |
| `structlog` | Logging | Structured JSON logs with context |
| `pytest` | Testing | TDD, fixtures, parametrization, markers |
| `hypothesis` | Property testing | Invariant verification, edge case generation |

## Development Standards

### Type Safety (Mandatory)
- **Type hints required** on all public APIs
- **mypy strict mode** for type checking
- **Pydantic models** for runtime validation
- **No `Any`** without explicit justification and comment

### Code Quality
- **ruff**: Linting and import sorting
- **black**: Code formatting (line length 100)
- **PEP 8**: Style compliance
- **Docstrings**: Required on public interfaces (Google style)

### Async/Await Patterns
- **All I/O operations must be async**
- **Never block the event loop** (no sync I/O in async context)
- **Use `asyncio.gather()`** for parallel operations
- **Prefer `async with`** for context managers
- **Use `async for`** for async iterators (streaming)

### Testing (TDD Mandatory)
1. **RED**: Write failing test first
2. **GREEN**: Implement minimal code to pass
3. **REFACTOR**: Clean up with confidence
4. **Target**: Meaningful coverage, not percentage games

**Test Organization**:
- `tests/unit/` - Isolated component tests with mocks
- `tests/integration/` - Cross-component interactions
- `tests/property/` - Hypothesis property-based tests
- `tests/behavior/` - Behavior-driven scenarios
- `tests/regression/` - Bug regression prevention

## Development Environment

### Platform
- **Primary**: Windows-based development
- **Python Executable**: `./.venv/Scripts/python.exe` (ALWAYS use this path)
- **Path Style**: Forward slashes `/` (Windows accepts them)

### Required Tools
- Python 3.10+
- Virtual environment: `.venv/`
- Git 2.x+
- pytest 7.x+

### Common Commands

```powershell
# Activate venv (Windows)
.\.venv\Scripts\activate

# Run application
./.venv/Scripts/python.exe -m src.core.cli

# Run tests (fast - skips slow/integration)
./.venv/Scripts/python.exe -m pytest

# Run tests (full suite)
./.venv/Scripts/python.exe -m pytest -m "integration or unit"

# Lint and fix
./.venv/Scripts/python.exe -m ruff check --fix .

# Type check
./.venv/Scripts/python.exe -m mypy src/

# Format code
./.venv/Scripts/python.exe -m black .

# Post-edit QA (MANDATORY after editing Python files)
./.venv/Scripts/python.exe -m ruff check --fix <file> && ./.venv/Scripts/python.exe -m black <file> && ./.venv/Scripts/python.exe -m mypy <file>

# Manage Alembic (database migrations)
./.venv/Scripts/python.exe scripts/manage_alembic_config.py <alembic_args>

# Inspect CBOR wire captures
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py <file> --detect-issues
```

## Key Technical Decisions

### Staged Initialization
- **Sequential bootstrap** in `src/core/app/stages/`
- **Initialization order**: Infrastructure → Core Services → Backends → Controllers
- **Stage pattern**: Each stage declares dependencies and validates before proceeding
- **Benefits**: Clear startup sequence, easy debugging, deterministic failure modes

Stages:
1. `infrastructure.py` - Logging, monitoring, base infrastructure
2. `core_services.py` - Core business services (session, translation)
3. `backend.py` - Backend connector registration and initialization
4. `controller.py` - FastAPI route controllers
5. `processor.py` - Request/response processors
6. `health_check.py` - Health monitoring and probes

### Dependency Injection
- **Custom DI container** in `src/core/di/container.py`
- **Service lifetimes**: Singleton, Scoped, Transient
- **Factory functions** for complex dependencies
- **Interface segregation**: `I`-prefix naming (e.g., `IBackendService`)
- **Resolution strategy**: Constructor injection with type hints

**Benefits**: Testability (mock via interfaces), loose coupling, explicit dependencies

### Error Handling Hierarchy
- **Base class**: `LLMProxyError` (all custom exceptions extend this)
- **HTTP status codes** embedded in exceptions (`status_code` attribute)
- **Structured errors** via `to_dict()` method
- **Domain-specific exceptions**: `BackendError`, `AuthenticationError`, `RateLimitExceededError`
- **Never catch bare `Exception`** - use specific exception types

### Configuration Precedence (Highest to Lowest)
1. **CLI arguments** - `python -m src.core.cli --arg value`
2. **Environment variables** - `export VAR=value`
3. **YAML config file** - `config/config.yaml`
4. **Defaults** - Hard-coded fallbacks

**Config Flow**: `src/core/cli.py` → `src/core/config/app_config.py` → `src/core/config/parameter_resolution.py`

### Adapter Pattern for Backends
- **Base class**: `LLMBackend` (`src/connectors/base.py`)
- **Interface contract**:
  - `async def initialize()` - Setup and health check
  - `async def chat_completions()` - Primary chat endpoint
  - `async def get_available_models()` - Model discovery
- **Self-contained**: Each connector in its own file
- **Auto-discovery**: Backends register themselves via imports

**Example Backends**:
- `openai.py` - OpenAIConnector
- `anthropic.py` - AnthropicBackend
- `gemini.py` - GeminiBackend
- `hybrid.py` - HybridConnector (two-phase reasoning)

### CBOR Wire Captures
- **Purpose**: Byte-precise traffic recording for debugging and replay
- **Format**: CBOR (Concise Binary Object Representation)
- **Storage**: `var/wire_captures_cbor/`
- **Inspection**: `scripts/inspect_cbor_capture.py`
- **Use Cases**: Bug reproduction, traffic analysis, regression testing

## Development Workflow Patterns

### TDD Cycle (Mandatory)
```
1. Write test (RED)
2. Run test - it fails
3. Write minimal implementation (GREEN)
4. Run test - it passes
5. Refactor code (REFACTOR)
6. Run test - still passes
7. Commit
```

### Debugging Workflow
1. **Create repro script** - Don't use inline `python -c "..."` (breaks Windows terminals)
2. **Capture wire traffic** - Enable CBOR capture in config
3. **Inspect captures** - Use `inspect_cbor_capture.py`
4. **Replay traffic** - Use simulation tools in `src/core/simulation/`
5. **Check logs** - Review `var/logs/` with session IDs

### Git Workflow
- **Branches**: Feature branches from `main` or `dev`
- **Commits**: Conventional commits (feat:, fix:, docs:, test:, refactor:)
- **Pre-commit hooks**: Secret scanning, architectural checks
- **CI/CD**: GitHub Actions (`.github/workflows/`)

## Performance Considerations

- **Async everywhere**: Never block the event loop
- **Connection pooling**: httpx client reuse across requests
- **Lazy initialization**: Defer expensive operations until needed
- **Stream processing**: Use async generators for streaming responses
- **Memory efficiency**: Avoid loading entire responses into memory

## Security Standards

- **No secrets in code**: Use environment variables or config files
- **Input validation**: Pydantic models for all external inputs
- **Path traversal protection**: Sandbox file operations
- **Command injection protection**: Dangerous command detection and blocking
- **Rate limiting**: Built-in rate limit handling for backends
- **CORS**: Configurable cross-origin policies

---

_Generated: 2025-01-XX_
_Document standards and patterns, not every dependency_
