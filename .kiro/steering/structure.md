# Project Structure (Steering)

## Mental Model

The codebase is organized around an async FastAPI proxy core with:
- staged startup (`src/core/app/stages/`)
- DI-managed services (`src/core/di/`, `src/core/services/`, `src/core/interfaces/`)
- backend connectors (`src/connectors/`)
- optional protocol servers/features (e.g., Codebuff WebSocket under `src/codebuff/`)

## High-Signal Map

### Core engine (`src/core/`)
Where most cross-cutting proxy logic lives.

- `src/core/app/`
  - `controllers/`: HTTP route handlers (OpenAI/Anthropic/Gemini-compatible)
  - `middleware/`: FastAPI/Starlette middleware (exception shaping, etc.)
  - `stages/`: staged initialization (startup ordering, registrations)
- `src/core/services/`: orchestration services (routing, safety, usage, captures, processing pipelines)
  - `src/core/services/backend_completion_flow/`: backend-call orchestration (failover/retry/capture/usage as a coordinator + collaborators)
- `src/core/domain/`: domain models/envelopes (Pydantic models, response envelopes, wire-capture models)
- `src/core/interfaces/`: `I*` interfaces used for DI boundaries and test seams
- `src/core/di/`: DI container implementation + registrations
- `src/core/config/`: config models/loaders/validation and precedence logic
- `src/core/auth/`: SSO authentication/authorization flow and supporting services
- `src/core/security/`: security middleware and loop-prevention guardrails
- `src/core/memory/`: session memory capture, summarization, and injection services
- `src/core/transport/fastapi/`: adapters between domain envelopes and FastAPI request/response types
  - `adapters/`: modular layer components for response transformation (SSE, metadata, usage, sanitization, capture, streaming, response builders)
  - `response_adapters.py`: thin facade delegating to adapters/ layer components
- `src/core/commands/`: chat-embedded command pipeline (parsing/execution/steering integration)
- `src/core/simulation/`: replay/inspection utilities for debugging captured traffic
- `src/core/database/`: SQLModel models + Alembic migrations + repositories

### Backends (`src/connectors/`)
Provider-specific adapters that call external LLM APIs.

- Base: `src/connectors/base.py` (`LLMBackend`)
- Discovery: importing `src.connectors` triggers auto-import of connector modules via `src/connectors/__init__.py`
- Registration: connector modules register themselves in `backend_registry` (`src/core/services/backend_registry.py`)
- Import trigger: `src/core/services/backend_imports.py` is imported during CLI startup (`src/core/cli.py`)

Practical implication: adding a new backend typically means:
1. Create a new module under `src/connectors/`
2. Register a factory with `backend_registry.register_backend(...)` at module import time
3. Implement `LLMBackend` and expose a stable `backend_type`

### Codebuff (`src/codebuff/`)
WebSocket server and protocol handling for real-time “agent” communication.

### Top-level feature areas (`src/`)
Not everything is under `src/core/`; some features live at top-level:
- `src/loop_detection/`
- `src/tool_call_loop/`
- `src/services/`: cross-cutting non-core services (steering policies, test-execution reminder)
- `src/resources/`: embedded prompt resources and assets (e.g., Codex prompts)
- plus a few request/response middleware helpers (e.g., `src/request_middleware.py`)

### Configuration and runtime outputs
- `config/`: example configs, backend config snippets, prompt templates, and schemas
  - Schemas: `config/schemas/`
  - Prompts: `config/prompts/`
- `var/`: runtime state and outputs
  - `var/logs/`, `var/wire_captures_cbor/`, `var/wire_captures_json/`, `var/db/`, `var/state/`

### Tests
- `tests/`: suites mirror the project structure
  - `tests/unit/`, `tests/integration/`, `tests/property/`, `tests/behavior/`, `tests/regression/`
  - markers live in `pyproject.toml` under `[tool.pytest.ini_options]`
  - TDD and test detail expectations (tests as executable specifications): see `.kiro/steering/testing.md`

### Tooling & Scripts
- `scripts/`: **End-user tools** only (CLI helpers, inspection tools, admin scripts).
- `dev/scripts/`: **Development tools** (build, test, lint, maintenance).
  - `dev/scripts/artifacts/`: Retired/one-off scripts and reproduction tools.

## Startup Lifecycle (Staged Initialization)

Source of truth: `src/core/app/stages/application_stages.py`.

Default stage order:
1. `InfrastructureStage`
2. `CoreServicesStage`
3. `SteeringStage`
4. `BackendStage`
5. `HealthCheckStage`
6. `CommandStage`
7. `ProcessorStage`
8. `ControllerStage`

## Where to Make Changes (Common Work Types)

- **Add/modify HTTP endpoints**: `src/core/app/controllers/` (then ensure stage wiring in `src/core/app/stages/controller.py`)
- **Add a new backend connector**: `src/connectors/` (+ registration via `backend_registry`)
- **Change routing/failover logic**: services in `src/core/services/` (routing, backends, resilience)
- **Change backend completion orchestration**: `src/core/services/backend_completion_flow/` (flow ordering + collaborators)
- **Change request/response shaping**: `src/core/transport/fastapi/` + middleware/services
- **Change request processing pipeline**: `src/core/services/request_processor_service.py` + internal phase contracts in `src/core/interfaces/request_processor_internal.py` (wiring in `src/core/app/stages/processor.py`)
- **Add a new config option**: `src/core/config/app_config.py` + schema in `config/schemas/` + CLI surface in `src/core/cli_support/`
- **Change error shapes/statuses**: `src/core/common/exceptions.py` + `src/core/app/error_handlers.py`
- **Change capture behavior**: `src/core/services/*wire_capture*` + `var/wire_captures_cbor/`

## Naming and Imports

- Prefer absolute imports from `src` (example: `from src.core.common.exceptions import LLMProxyError`)
- Naming conventions follow standard Python:
  - modules: `snake_case.py`
  - classes: `PascalCase`
  - functions: `snake_case`
  - interfaces: `I*` (e.g., `IBackendService`)

---

_Updated: 2025-12-27_
_Reason: Link structure map to TDD/testing steering_
_Document stable structure and change locations; avoid exhaustive file listings_
