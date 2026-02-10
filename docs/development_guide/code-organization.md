# Code Organization

This document describes the directory structure and module organization of the LLM Interactive Proxy codebase.

## Project Structure

```
llm-interactive-proxy/
├── src/                    # Source code
├── tests/                  # Test suite
├── config/                 # Configuration files
├── docs/                   # Documentation
├── scripts/                # Utility scripts
├── var/                    # Runtime data
├── pyproject.toml          # Project metadata and dependencies
├── setup.py                # Package setup
├── README.md               # Project overview
├── dev/AGENTS.md           # Coding standards
├── CONTRIBUTING.md         # Contribution guidelines
├── CHANGELOG.md            # Version history
└── LICENSE                 # License information
```

## Source Code Structure (`src/`)

The source code follows a layered architecture with clear separation of concerns:

### Core Module (`src/core/`)

The core module contains the main business logic and follows hexagonal architecture principles:

```
src/core/
├── app/                    # Application layer (FastAPI app, routes)
├── commands/               # Command definitions and handlers
├── common/                 # Shared utilities and exceptions
├── config/                 # Configuration management
├── constants/              # System constants
├── di/                     # Dependency injection
├── domain/                 # Domain entities and business logic
├── interfaces/             # Abstract interfaces
├── models/                 # Data models and schemas
├── ports/                  # Port interfaces (hexagonal architecture)
├── repositories/           # Data access layer
├── security/               # Security features
├── services/               # Business services
├── simulation/             # Wire capture and simulation engine
├── testing/                # Testing utilities
├── transport/              # HTTP transport layer
├── utils/                  # Utility functions
├── cli.py                  # Command-line interface
├── metadata.py             # Metadata management
└── persistence.py          # Data persistence
```

#### Key Subdirectories

**`app/`** - Application Layer

- FastAPI application setup
- Route definitions
- Request/response handling
- Server lifecycle management

**`commands/`** - Command System

- In-chat command definitions (`!/backend(...)`, `!/model(...)`, etc.)
- Command parsers and handlers
- Command execution logic

**`common/`** - Shared Components

- Custom exception hierarchy
- Shared utilities
- Common types and interfaces

**`config/`** - Configuration Management

- Configuration loading and validation
- Environment variable handling
- YAML configuration parsing
- Configuration precedence logic

**`domain/`** - Domain Layer

- Core business entities
- Domain logic and rules
- Value objects
- Domain events

**`models/`** - Data Models

- Request/response models
- Internal data structures
- Schema definitions
- Type definitions

**`services/`** - Business Services

- [LLM Assessment Service](../user_guide/features/llm-assessment.md)
- [Quality Verifier Service](../user_guide/features/quality-verifier.md)
- [Session Management Service](../user_guide/features/session-management.md)
- [Tool Call Reactor Service](../user_guide/features/tool-access-control.md)
- Performance Tracking Service

**`simulation/`** - Wire Capture & Simulation

- CBOR wire capture
- JSON wire capture
- Capture file reading and writing
- Simulation engine for replay

**`security/`** - Security Features

- Authentication
- Authorization
- API key management
- Brute-force protection
- Rate limiting

**`transport/`** - HTTP Transport

- HTTP client management
- Connection pooling
- Request/response handling
- Streaming support

### Connectors Module (`src/connectors/`)

Backend connector implementations for different LLM providers:

```
src/connectors/
├── base.py                 # Base connector interface
├── openai.py               # [OpenAI](../user_guide/backends/openai.md) connector
├── openai_codex.py         # OpenAI Codex (OAuth) connector
├── openai_responses.py     # OpenAI Responses API connector
├── anthropic.py            # [Anthropic](../user_guide/backends/anthropic.md) connector
├── anthropic_oauth.py      # Anthropic OAuth connector
├── gemini.py               # [Gemini](../user_guide/backends/gemini.md) API key connector
├── gemini_oauth_base.py    # Base for Gemini OAuth connectors
├── gemini_oauth_free.py    # Gemini OAuth free tier
├── gemini_oauth_plan.py    # Gemini OAuth with subscription
├── gemini_cloud_project.py # Gemini GCP project connector
├── openrouter.py           # [OpenRouter](../user_guide/backends/openrouter.md) connector
├── zai.py                  # [ZAI](../user_guide/backends/zai.md) connector
├── zai_coding_plan.py      # ZAI coding plan connector
├── qwen_oauth.py           # [Qwen](../user_guide/backends/qwen.md) OAuth connector
├── minimax.py              # Minimax connector
├── zenmux.py               # ZenMux connector
├── hybrid.py               # [Hybrid](../user_guide/features/hybrid-backend.md) backend (two-phase)
├── cline.py                # Cline connector
├── streaming_utils.py      # Streaming utilities
├── mixins/                 # Connector mixins
└── utils/                  # Connector utilities
```

#### Connector Responsibilities

Each connector implements:

- **Authentication**: API keys, OAuth tokens, service accounts
- **Request Translation**: Convert internal format to provider API
- **Response Parsing**: Parse provider responses to internal format
- **Streaming**: Handle streaming responses
- **Error Handling**: Provider-specific error handling
- **Retry Logic**: Implement retry strategies

### Loop Detection Module (`src/loop_detection/`)

Subsystem for detecting repetitive patterns in conversations:

```
src/loop_detection/
├── analyzer.py             # Pattern analysis
├── buffer.py               # Circular buffer for history
├── config.py               # Loop detection configuration
├── detector.py             # Main detection logic
├── event.py                # Loop detection events
├── hasher.py               # Content hashing
├── hybrid_detector.py      # Hybrid detection strategy
├── streaming.py            # Streaming loop detection
├── token_window_loop_detector.py  # Token-based detection
└── types.py                # Type definitions
```

### Tool Call Loop Module (`src/tool_call_loop/`)

Manages tool call lifecycle and tracking:

```
src/tool_call_loop/
├── config.py               # Tool call configuration
├── lifecycle_registry.py   # Tool call lifecycle management
└── tracker.py              # Tool call tracking
```

### Services Module (`src/services/`)

Top-level service implementations (being migrated to `src/core/services/`).

### Legacy Modules (Root of `src/`)

These modules are being gradually migrated to the core structure:

- `agents.py` - Agent definitions
- `anthropic_converters.py` - Anthropic protocol converters
- `anthropic_models.py` - Anthropic data models
- `anthropic_server.py` - Anthropic server implementation
- `gemini_converters.py` - Gemini protocol converters
- `gemini_models.py` - Gemini data models
- `command_prefix.py` - Command prefix handling
- `command_utils.py` - Command utilities
- `constants.py` - System constants
- `llm_accounting_utils.py` - Token accounting
- `performance_tracker.py` - Performance tracking
- `rate_limit.py` - Rate limiting
- `request_middleware.py` - Request middleware
- `response_middleware.py` - Response middleware
- `security.py` - Security utilities

## Test Structure (`tests/`)

The test suite is organized by test type and mirrors the source structure:

```
tests/
├── unit/                   # Unit tests
│   ├── core/              # Core module tests
│   ├── connectors/        # Connector tests
│   ├── loop_detection/    # Loop detection tests
│   └── ...
├── integration/            # Integration tests
├── property/               # Property-based tests
├── regression/             # Regression tests
├── simulation/             # Simulation tests
├── behavior/               # Behavior tests
├── performance/            # Performance tests
├── fixtures/               # Test fixtures
├── mocks/                  # Mock objects
├── helpers/                # Test helpers
└── conftest.py             # Pytest configuration
```

## Configuration Structure (`config/`)

Configuration files and templates:

```
config/
├── backends/               # Backend-specific configurations
├── prompts/                # Prompt templates
│   └── quality_verifier_prompts/     # Quality Verifier prompts
├── replacements/           # Text replacement rules
├── schemas/                # JSON schemas
├── config.example.yaml     # Example configuration
├── edit_precision_model_temperatures.yaml  # Edit precision config
├── edit_precision_patterns.yaml            # Edit precision patterns
├── reasoning_aliases.yaml.example          # Reasoning aliases
├── tool_access_control_examples.yaml       # Tool access examples
├── tool_call_reactor_config.yaml           # Tool call reactor config (validates against schemas/tool_call_reactor_config.schema.yaml)
└── sample.env              # Sample environment variables
```

## Runtime Data Structure (`var/`)

Runtime data and logs:

```
var/
├── logs/                   # Log files (with PID in filename)
├── wire_captures_json/     # JSON wire captures
├── wire_captures_cbor/     # CBOR wire captures
└── capture_analysis.json   # Capture analysis results
```

## Scripts (`scripts/`)

Utility scripts for development and operations:

```
scripts/
├── architectural_linter.py         # Architecture validation
├── inspect_cbor_capture.py         # CBOR capture inspection
├── fetch_actual_models.py          # Fetch available models
├── install-hooks.py                # Install git hooks
├── pre-commit-hook.py              # Pre-commit hook
├── pre_commit_api_key_check.py     # API key leak detection
├── verify_deployment.py            # Deployment verification
└── ...                             # Other utility scripts
```

## Key Component Responsibilities

### Front-End Layer

- **OpenAI Server** (`src/core/app/`): Handles OpenAI-compatible requests
- **Anthropic Server** (`src/anthropic_server.py`): Handles Anthropic-compatible requests (integrated into main proxy process)
- **Gemini Server** (`src/core/app/`): Handles Gemini-compatible requests

### Core Processing

- **Request Middleware** (`src/request_middleware.py`): Pre-processes requests
- **Response Middleware** (`src/response_middleware.py`): Post-processes responses
- **Command System** (`src/core/commands/`): Handles in-chat commands
- **Model Resolution** (`src/core/services/`): Resolves model names and applies rewrites

### Safety & Security

- **Authentication** (`src/core/security/`): API key validation
- **Tool Access Control** (`src/core/services/`): [Policy-based tool filtering](../user_guide/features/tool-access-control.md)
- **Dangerous Command Protection** (`src/core/services/`): [Blocks harmful commands](../user_guide/features/dangerous-command-protection.md)
- **File Sandboxing** (`src/core/services/`): [Restricts file access](../user_guide/features/file-access-sandboxing.md)
- **Loop Detection** (`src/loop_detection/`): Detects repetitive patterns

### Quality Assurance

- **LLM Assessment** (`src/core/services/`): Monitors conversation quality
- **Quality Verifier** (`src/core/services/`): Verifies individual responses
- **Tool Call Validation** (`src/tool_call_loop/`): Validates and repairs tool calls

### Observability

- **Wire Capture** (`src/core/simulation/`): Records requests/responses
- **Performance Tracking** (`src/performance_tracker.py`): Tracks metrics
- **Logging** (throughout): Structured logging

## Module Dependencies

### Dependency Flow

```
Front-End APIs
    ↓
Core Services
    ↓
Backend Connectors
    ↓
LLM Providers
```

### Key Interfaces

- **`BaseConnector`**: All backend connectors implement this interface
- **`CommandHandler`**: All command handlers implement this interface
- **`Middleware`**: Request/response middleware interface
- **`Service`**: Business service interface

## Naming Conventions

The codebase follows these naming conventions (see [AGENTS.md](../../dev/AGENTS.md) for complete standards):

- **Files**: `snake_case.py`
- **Classes**: `PascalCase`
- **Functions/Methods**: `snake_case`
- **Constants**: `UPPER_SNAKE_CASE`
- **Private Members**: `_leading_underscore`
- **Test Files**: `test_*.py`
- **Test Functions**: `test_*`

## Import Organization

Imports are organized in three groups (separated by blank lines):

1. Standard library imports
2. Third-party imports
3. Local imports

Example:

```python
import os
from typing import Dict, List

import httpx
from fastapi import FastAPI

from src.core.common.exceptions import BackendError
from src.connectors.base import BaseConnector
```

## Related Documentation

- **Architecture**: See [architecture.md](architecture.md) for system architecture
- **Building**: See [building.md](building.md) for build instructions
- **Testing**: See [testing.md](testing.md) for testing guidelines
- **Contributing**: See [contributing.md](contributing.md) for contribution workflow
- **Coding Standards**: See [AGENTS.md](../../dev/AGENTS.md) for detailed coding standards
