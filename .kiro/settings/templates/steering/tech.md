# Technology Stack

## Architecture

**Layered Async Service Architecture** with Staged Initialization and Dependency Injection.

```
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI Controllers                      │
│              (src/core/app/controllers/)                     │
├─────────────────────────────────────────────────────────────┤
│                    Service Layer                             │
│                 (src/core/services/)                         │
├─────────────────────────────────────────────────────────────┤
│                   Domain Models                              │
│                  (src/core/domain/)                          │
├─────────────────────────────────────────────────────────────┤
│              Backend Connectors (Adapters)                   │
│                  (src/connectors/)                           │
├─────────────────────────────────────────────────────────────┤
│              DI Container & Interfaces                       │
│       (src/core/di/, src/core/interfaces/)                   │
└─────────────────────────────────────────────────────────────┘
```

## Core Technologies

- **Language**: Python 3.10+
- **Framework**: FastAPI (async)
- **Runtime**: uvicorn / hypercorn
- **HTTP Client**: httpx (async)
- **Serialization**: Pydantic v2, CBOR (wire captures)

## Key Libraries

| Library | Purpose | Pattern |
|---------|---------|---------|
| `fastapi` | Web framework | Async request handling |
| `httpx` | HTTP client | Async backend calls |
| `pydantic` | Validation | Domain models, DTOs |
| `cbor2` | Binary encoding | Wire capture serialization |
| `structlog` | Logging | Structured JSON logging |
| `pytest` | Testing | TDD, fixtures, mocks |
| `hypothesis` | Property testing | Invariant verification |

## Development Standards

### Type Safety
- Type hints required on all public APIs
- `mypy` strict mode for type checking
- Pydantic models for runtime validation
- No `Any` without explicit justification

### Code Quality
- `ruff` for linting and formatting
- `black` for code formatting
- PEP 8 compliance
- Docstrings on public interfaces

### Async/Await
- All I/O operations must be async
- Never block the event loop
- Use `asyncio.gather()` for parallel operations
- Prefer `async with` for context managers

### Testing (TDD)
- Write test first (Red phase)
- Implement to pass (Green phase)
- Refactor with confidence
- Target: meaningful coverage, not percentage

## Development Environment

### Required Tools
- Python 3.10+
- Virtual environment: `.venv/`
- Git 2.x+
- pytest 7.x+

### Common Commands
```bash
# Activate venv (Windows)
.\.venv\Scripts\activate

# Run application
./.venv/Scripts/python.exe -m src.core.cli

# Run tests (fast)
./.venv/Scripts/python.exe -m pytest -m "not slow"

# Run tests (full)
./.venv/Scripts/python.exe -m pytest

# Lint and fix
./.venv/Scripts/python.exe -m ruff check . --fix

# Type check
./.venv/Scripts/python.exe -m mypy src/

# Format
./.venv/Scripts/python.exe -m black .
```

## Key Technical Decisions

### Dependency Injection
- Custom DI container in `src/core/di/container.py`
- Service lifetimes: Singleton, Scoped, Transient
- Factory functions for complex dependencies
- Interface segregation with `I`-prefix naming

### Staged Initialization
- Sequential bootstrap in `src/core/app/stages/`
- Order: Infrastructure -> Core Services -> Backends -> Controllers
- Each stage declares dependencies
- Validation before proceeding

### Error Handling
- Hierarchy extends `LLMProxyError`
- HTTP status codes embedded in exceptions
- Structured error responses via `to_dict()`
- Never catch bare `Exception`

### Configuration Precedence
- CLI arguments (highest priority)
- Environment variables
- YAML config file
- Defaults (lowest priority)

---
_Document standards and patterns, not every dependency_
