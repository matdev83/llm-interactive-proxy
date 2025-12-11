# Project Structure

## Organization Philosophy

**Layered Architecture with Domain-Driven Design** - Separation of concerns through clear boundaries between controllers, services, domain, and infrastructure.

## Directory Patterns

### Core Application (`src/core/`)
**Purpose**: Central business logic, domain models, and application services

#### `/src/core/app/`
Controllers, middleware, and application lifecycle management
- `controllers/` - FastAPI route handlers
- `stages/` - Sequential initialization phases
- `middleware/` - Request/response pipeline components

#### `/src/core/services/`
Business logic and orchestration services
- Implements interfaces from `src/core/interfaces/`
- Registered via DI container
- Pure async/await patterns

#### `/src/core/domain/`
Domain models, DTOs, and business entities
- Pydantic models for validation
- Value objects and enums
- Translation logic between API formats

#### `/src/core/interfaces/`
Abstract base classes and protocols
- I-prefix naming convention (e.g., `IServiceName`)
- Defines contracts for DI resolution
- Enables testability and mocking

#### `/src/core/di/`
Dependency injection container and service registration
- `container.py` - DI container implementation
- `services.py` - Service registration helpers
- Lifetimes: Singleton, Scoped, Transient

#### `/src/core/config/`
Configuration models and schemas
- `app_config.py` - Main configuration class
- Precedence: CLI > ENV > YAML

#### `/src/core/common/`
Shared utilities and exceptions
- `exceptions.py` - Error hierarchy extending `LLMProxyError`
- Logging utilities
- Constants

### Connectors (`src/connectors/`)
**Purpose**: Backend adapters for LLM providers
- Extend `LLMBackend` base class
- Implement `initialize()`, `chat_completions()`, `get_available_models()`
- Each connector is self-contained in its own file

### Configuration (`config/`)
**Purpose**: YAML configuration files and schemas
- `config.example.yaml` - Example configuration
- `schemas/` - JSON schemas for validation

### Tests (`tests/`)
**Purpose**: Test suites mirroring source structure
- `unit/` - Isolated unit tests
- `integration/` - Cross-component tests
- `property/` - Hypothesis property tests
- `behavior/` - Behavior-driven tests
- `conftest.py` - Shared fixtures

### Data Directories
- `var/wire_captures_cbor/` - CBOR wire captures
- `var/logs/` - Application logs
- `data/` - Runtime data files

## Naming Conventions

- **Files**: `snake_case.py`
- **Classes**: `PascalCase`
- **Functions/Methods**: `snake_case`
- **Constants**: `UPPER_SNAKE_CASE`
- **Interfaces**: `I` prefix (e.g., `IServiceName`)
- **Private members**: `_leading_underscore`

## Import Organization

```python
# Standard library
from __future__ import annotations
import logging
from typing import Any

# Third-party
from fastapi import FastAPI
from pydantic import BaseModel

# Local - interfaces first
from src.core.interfaces.service_interface import IServiceName

# Local - implementations
from src.core.services.service_impl import ServiceImpl
from src.core.common.exceptions import LLMProxyError
```

**Path Aliases**: Not used - use absolute imports from `src/`

## Code Organization Principles

### SOLID Principles
- **Single Responsibility**: Each class has one reason to change
- **Open/Closed**: Extend via inheritance, not modification
- **Liskov Substitution**: Derived classes are substitutable
- **Interface Segregation**: Small, focused interfaces
- **Dependency Inversion**: Depend on abstractions (interfaces)

### Dependency Direction
```
Controllers -> Services -> Domain
                ↓
           Connectors (Adapters)
                ↓
           External APIs
```

### DRY (Don't Repeat Yourself)
- Extract common patterns into base classes
- Use factory functions for repeated DI registrations
- Share test fixtures via `conftest.py`

### Test-Driven Development
- Tests mirror source structure in `tests/`
- Write test first, then implementation
- Mock dependencies via DI container

---
_Document patterns, not file trees. New files following patterns shouldn't require updates_
