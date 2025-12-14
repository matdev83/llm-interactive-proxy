# Project Structure

## Organization Philosophy

**Layered Service Architecture with Domain-Driven Design** - Clear separation of concerns through interface-based boundaries between controllers, services, domain logic, and infrastructure.

## Directory Patterns

### Core Application (`src/core/`)
**Purpose**: Central business logic, domain models, and application services

#### `/src/core/app/`
Application lifecycle, controllers, and middleware
- `controllers/` - FastAPI route handlers (REST endpoints)
- `stages/` - Sequential initialization phases (staged bootstrap)
- `middleware/` - Request/response pipeline components
- `application_builder.py` - App construction orchestration

**Pattern**: Controllers are thin facades that delegate to services via DI

#### `/src/core/services/`
Business logic orchestration and domain services (30+ services)
- Implements interfaces from `src/core/interfaces/`
- Registered via DI container with appropriate lifetimes
- Pure async/await patterns (no blocking I/O)
- Examples: `BackendService`, `TranslationService`, `UsageTrackingService`

**Pattern**: Services are stateless, injected via constructor, single responsibility

#### `/src/core/domain/`
Domain models, DTOs, and business entities
- Pydantic models for validation and serialization
- Value objects and enums
- Translation logic between API formats (OpenAI ↔ Anthropic ↔ Gemini)
- No business logic (pure data structures)

**Pattern**: Models are immutable where possible, use Pydantic validation

#### `/src/core/interfaces/`
Abstract base classes and protocols defining contracts
- `I`-prefix naming convention (e.g., `IBackendService`, `ISessionService`)
- Defines contracts for DI resolution
- Enables testability via mocking
- Protocol-based for structural typing where appropriate

**Pattern**: One interface per service, segregated by responsibility

#### `/src/core/di/`
Dependency injection container and service registration
- `container.py` - Custom DI container implementation
- `services.py` - Service registration helpers
- Lifetimes: Singleton, Scoped (per-request), Transient (per-resolution)
- Factory functions for complex dependency graphs

**Pattern**: Register in stages during initialization, resolve via constructor injection

#### `/src/core/config/`
Configuration models and precedence resolution
- `app_config.py` - Main configuration class (Pydantic)
- `parameter_resolution.py` - Config precedence logic (CLI > ENV > YAML)
- Schema validation via JSON Schema files in `config/schemas/`

**Pattern**: Immutable config objects, validate early at startup

#### `/src/core/common/`
Shared utilities, exceptions, and constants
- `exceptions.py` - Error hierarchy extending `LLMProxyError`
- Logging configuration and utilities
- HTTP status constants
- Common type definitions

**Pattern**: Domain exceptions with embedded HTTP status codes

#### `/src/core/cli_support/`
CLI argument parsing and help text generation
- `argument_parser_builder.py` - Organizes CLI args by domain
- Backward-compatible with legacy CLI interface

**Pattern**: Build parser via builder pattern, delegate to services

### Backend Connectors (`src/connectors/`)
**Purpose**: Adapter implementations for LLM providers

- Extend `LLMBackend` base class (`base.py`)
- Implement interface contract: `initialize()`, `chat_completions()`, `get_available_models()`
- Self-contained in single file per provider
- Auto-registered via import in `src/core/services/backend_imports.py`

**Examples**:
- `openai.py` - OpenAIConnector (GPT-4, GPT-4o, o1)
- `anthropic.py` - AnthropicBackend (Claude 3.5 Sonnet)
- `gemini.py` - GeminiBackend (Gemini models, base class for OAuth variants)
- `hybrid.py` - HybridConnector (two-phase reasoning pattern)
- `qwen_oauth.py` - QwenOAuthBackend (Alibaba Cloud Qwen)

**Pattern**: Adapter pattern, each connector maps provider API to common interface

### Configuration (`config/`)
**Purpose**: YAML configuration files and JSON schemas

- `config.example.yaml` - Example/template configuration
- `schemas/` - JSON schemas for validation
- `backends/` - Backend-specific config examples
- `prompts/` - Prompt templates for features

**Pattern**: Example files with `.example.` suffix, never commit secrets

### Tests (`tests/`)
**Purpose**: Comprehensive test suites mirroring source structure

- `unit/` - Isolated unit tests with mocks (fast)
- `integration/` - Cross-component tests (slower, marked)
- `property/` - Hypothesis property-based tests
- `behavior/` - Behavior-driven scenario tests
- `regression/` - Bug regression prevention
- `conftest.py` - Shared fixtures and test configuration

**Pattern**: Mirror `src/` structure, use markers for test categorization

### Data Directories (`var/`)
Runtime data storage (not in source control)

- `var/wire_captures_cbor/` - CBOR binary wire captures
- `var/wire_captures_json/` - JSON wire captures (debugging)
- `var/logs/` - Application logs (structured JSON)
- `var/db/` - SQLite database (usage tracking, sessions)
- `var/state/` - Transient state files

**Pattern**: Ephemeral data, safe to delete, recreated on startup

### Kiro Specs (`.kiro/`)
Spec-driven development workflow

- `.kiro/specs/{feature-name}/` - Feature specifications
- `.kiro/steering/` - Project memory (this file and others)
- `.kiro/settings/` - Templates and rules for workflow

**Pattern**: Structured phases from requirements to implementation

### Scripts (`scripts/`)
Development utilities and debugging tools

- `inspect_cbor_capture.py` - Analyze wire captures
- `manage_alembic_config.py` - Database migration helper
- `debug_*.py` - Reproduction and debugging scripts
- `demo_*.py` - Feature demonstration scripts

**Pattern**: Prefix debugging/temp scripts with `tmp_rovodev_`, clean up after use

## Naming Conventions

### Files & Directories
- **Files**: `snake_case.py`
- **Directories**: `snake_case/`
- **Test files**: `test_feature_name.py`
- **Config files**: `kebab-case.yaml` or `snake_case.yaml`

### Code Elements
- **Classes**: `PascalCase` (e.g., `BackendService`, `OpenAIConnector`)
- **Functions/Methods**: `snake_case` (e.g., `chat_completions`, `get_available_models`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `DEFAULT_TIMEOUT`, `MAX_RETRIES`)
- **Interfaces**: `I` prefix + `PascalCase` (e.g., `IBackendService`, `ISessionService`)
- **Private members**: `_leading_underscore` (e.g., `_internal_state`, `_helper_method`)
- **Temporary files**: `tmp_rovodev_` prefix (e.g., `tmp_rovodev_debug.py`)

### Backend Naming
- **Backend IDs**: `lowercase:model-name` (e.g., `openai:gpt-4o`, `anthropic:claude-3-5-sonnet`)
- **Backend Classes**: `{Provider}Backend` or `{Provider}Connector`

## Import Organization

```python
# 1. Future imports
from __future__ import annotations

# 2. Standard library (alphabetical)
import asyncio
import logging
from typing import Any

# 3. Third-party (alphabetical)
from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

# 4. Local - interfaces first (alphabetical)
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.session_service_interface import ISessionService

# 5. Local - implementations (alphabetical)
from src.core.common.exceptions import LLMProxyError
from src.core.services.backend_service import BackendService
```

**Path Aliases**: Not used - always use absolute imports from `src/`

## Code Organization Principles

### SOLID Principles
- **Single Responsibility**: Each class has one reason to change (e.g., `TranslationService` only translates)
- **Open/Closed**: Extend via inheritance/composition, not modification (backend adapters)
- **Liskov Substitution**: Derived classes are substitutable (all backends implement `LLMBackend`)
- **Interface Segregation**: Small, focused interfaces (separate read/write interfaces)
- **Dependency Inversion**: Depend on abstractions (inject `IBackendService`, not `BackendService`)

### Dependency Direction
```
Controllers → Services → Domain Models
                ↓
           Connectors (Adapters)
                ↓
           External APIs
```

**Rule**: Higher layers depend on lower layers via interfaces, never vice versa

### DRY (Don't Repeat Yourself)
- Extract common patterns into base classes (e.g., `LLMBackend`)
- Use mixins for shared behavior (e.g., `UsageCalculationMixin`)
- Share test fixtures via `conftest.py`
- Use utility functions for repeated logic

### Test-Driven Development (TDD)
- Tests mirror source structure in `tests/`
- Write test BEFORE implementation
- Mock dependencies via DI container or manual mocks
- Use `pytest` markers for test categorization: `@pytest.mark.unit`, `@pytest.mark.integration`

**Test Naming**: `test_{feature}_{scenario}.py` or `test_{class_name}.py`

## Common Patterns

### Service Registration Pattern
```python
# In src/core/app/stages/core_services.py
container.add_singleton(IBackendService, BackendService)
container.add_scoped(ISessionService, SessionService)
container.add_transient(IRequestProcessor, RequestProcessor)
```

### Backend Adapter Pattern
```python
# In src/connectors/custom_backend.py
class CustomBackend(LLMBackend):
    async def initialize(self) -> None:
        # Setup logic
        pass
    
    async def chat_completions(self, request: dict) -> dict | AsyncGenerator:
        # Translate request, call provider, translate response
        pass
    
    async def get_available_models(self) -> list[str]:
        # Return available models
        pass
```

### Error Handling Pattern
```python
from src.core.common.exceptions import BackendError

try:
    result = await backend.chat_completions(request)
except httpx.HTTPStatusError as e:
    raise BackendError(
        message=f"Backend request failed: {e.response.status_code}",
        backend_name=backend_name,
        details={"status_code": e.response.status_code},
        status_code=502  # Map to Bad Gateway
    ) from e
```

### Async Streaming Pattern
```python
async def stream_response(backend_response: AsyncGenerator) -> AsyncGenerator:
    try:
        async for chunk in backend_response:
            # Transform chunk
            yield transformed_chunk
    finally:
        # Cleanup
        await backend_response.aclose()
```

## File Organization Within Modules

### Service File Structure
```python
# 1. Imports
from __future__ import annotations

# 2. Module-level constants
DEFAULT_TIMEOUT = 30

# 3. Private helpers (if small)
def _internal_helper() -> str:
    pass

# 4. Main service class
class ServiceName(IServiceInterface):
    """Service docstring."""
    
    def __init__(self, dependency: IDependency) -> None:
        self._dependency = dependency
    
    async def public_method(self) -> Result:
        """Method docstring."""
        pass
```

### Test File Structure
```python
# 1. Imports
import pytest
from src.module import ClassUnderTest

# 2. Fixtures (if file-specific)
@pytest.fixture
def subject():
    return ClassUnderTest()

# 3. Test classes (group related tests)
class TestFeatureName:
    def test_scenario_one(self, subject):
        assert subject.method() == expected
    
    def test_scenario_two(self, subject):
        assert subject.method() == expected

# 4. Standalone tests (if not grouped)
def test_edge_case():
    assert condition
```

---

_Generated: 2025-01-XX_
_Document patterns, not file trees. New files following patterns shouldn't require updates_
