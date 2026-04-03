# Codebase Structure

**Analysis Date:** 2026-04-04

## Directory Layout

```text
llm-interactive-proxy/
  src/                 # Production application code (core, connectors, transport, domain)
  tests/               # Unit/integration/behavior/regression test suites and fixtures
  docs/                # User and development documentation
  config/              # Runtime configuration templates and prompts
  scripts/             # User-facing operational scripts
  dev/                 # Development/internal tooling scripts
  var/                 # Runtime outputs (logs, captures, artifacts)
  .planning/codebase/  # Generated codebase mapping documents
  pyproject.toml       # Python project metadata, deps, test/lint tool config
  README.md            # Project overview and operational entry docs
```

## Directory Purposes

**`src/core/`:**
- Purpose: Main application engine and architecture backbone.
- Contains: App composition (`app/`), DI (`di/`), config (`config/`), services (`services/`), domain (`domain/`), transport (`transport/`), ports/interfaces.
- Key files: `src/core/cli.py`, `src/core/app/application_builder.py`, `src/core/di/container.py`, `src/core/services/request_processor_service.py`.

**`src/connectors/`:**
- Purpose: Provider/backend adapters.
- Contains: OpenAI, Anthropic, Gemini, OpenRouter, Nvidia, hybrid and codex-family connector implementations.
- Key files: `src/connectors/openai.py`, `src/connectors/anthropic.py`, `src/connectors/gemini.py`, `src/connectors/openrouter.py`.

**`src/core/app/`:**
- Purpose: FastAPI application assembly, staged startup, middleware, route/controller registration.
- Contains: `stages/`, `controllers/`, middleware modules and exception handlers.
- Key files: `src/core/app/stages/application_stages.py`, `src/core/app/stages/processor.py`, `src/core/app/controllers/__init__.py`, `src/core/app/middleware_config.py`.

**`src/core/services/`:**
- Purpose: Orchestration and business workflows.
- Contains: Request pipeline, backend routing/factory, command processing, streaming, health, usage/accounting, security/tool services.
- Key files: `src/core/services/request_processor_service.py`, `src/core/services/backend_routing_service.py`, `src/core/services/backend_validation_service.py`.

**`src/core/domain/`:**
- Purpose: Domain entities and protocol-agnostic models.
- Contains: Chat/session/response models, quality and translation models, streaming/domain helpers.
- Key files: `src/core/domain/chat.py`, `src/core/domain/request_context.py`, `src/core/domain/session.py`.

**`src/core/transport/fastapi/`:**
- Purpose: HTTP transport adapters and framework-level translation.
- Contains: Request/response/exception adapters and FastAPI-specific wrappers.
- Key files: `src/core/transport/fastapi/request_adapters.py`, `src/core/transport/fastapi/exception_adapters.py`.

**`tests/`:**
- Purpose: Verification across unit, integration, behavior, performance, and regression scopes.
- Contains: `tests/unit/`, `tests/integration/`, `tests/behavior/`, `tests/regression/`, test fixtures/helpers.
- Key files: `tests/conftest.py`, `tests/unit/core/app/test_application_builder_validation_lifecycle.py`.

## Key File Locations

**Entry Points:**
- `src/core/cli.py`: Main runtime entry for the proxy.
- `src/anthropic_server.py`: Anthropic-focused server bootstrap and endpoint host.

**Configuration:**
- `pyproject.toml`: Dependency graph plus pytest/ruff/black tool configuration.
- `config/`: Runtime config files/prompts consumed by startup and steering policies.
- `src/core/config/app_config.py`: Central typed runtime config model and loading path.

**Core Logic:**
- `src/core/app/application_builder.py`: Orchestrates staged initialization and app assembly.
- `src/core/app/stages/`: Stage-by-stage service registration modules.
- `src/core/services/`: Orchestration-heavy runtime services (request/backend/session/tool pipelines).

**Testing:**
- `tests/unit/`: Unit-level architecture and service tests.
- `tests/integration/`: End-to-end integration behavior against composed app paths.
- `tests/behavior/`: Behavioral/system-level scenarios.

## Naming Conventions

**Files:**
- Use `snake_case.py` for modules (for example `request_processor_service.py`, `backend_routing_service.py`, `health_check.py`).
- Use suffix-oriented naming for intent clarity (for example `*_service.py`, `*_controller.py`, `*_middleware.py`, `*_adapter.py`, `*_interface.py`).

**Directories:**
- Use `snake_case` directory names by concern (for example `src/core/app/stages/`, `src/core/transport/fastapi/adapters/`, `src/core/services/backend_completion_flow/`).
- Keep architecture-oriented grouping under `src/core/` and provider-specific grouping under `src/connectors/`.

## Where to Add New Code

**New Feature:**
- Primary code: Add orchestration/service logic under `src/core/services/` and any new domain model under `src/core/domain/`.
- Integration wiring: Register service dependencies in stage modules under `src/core/app/stages/` or registrar modules under `src/core/di/registrations/`.
- Tests: Add tests in `tests/unit/` for service logic and `tests/integration/` for endpoint or composed behavior.

**New Component/Module:**
- HTTP/API endpoint: Add controller logic in `src/core/app/controllers/` and route registration in `src/core/app/controllers/__init__.py`.
- Startup component: Implement an `InitializationStage` in `src/core/app/stages/` and include it in `src/core/app/stages/application_stages.py` (or builder default stage list).
- Backend/provider support: Add connector implementation in `src/connectors/` and wire through backend discovery/registration in `src/core/services/backend_discovery.py` and related DI registration.

**Utilities:**
- Shared runtime helpers: Place in `src/core/common/` or focused service helper modules in `src/core/services/`.
- Transport-only adapters: Place in `src/core/transport/fastapi/` (or `src/core/adapters/` for broader adapters).

## Special Directories

**`var/`:**
- Purpose: Runtime operational output (logs, captures, generated artifacts).
- Generated: Yes.
- Committed: Partially; repository includes the directory, generated runtime artifacts vary.

**`dev/`:**
- Purpose: Development-only scripts and internal tooling.
- Generated: No.
- Committed: Yes.

**`scripts/`:**
- Purpose: End-user operational scripts.
- Generated: No.
- Committed: Yes.

**`.planning/codebase/`:**
- Purpose: Generated brownfield mapping docs consumed by GSD planning/execution commands.
- Generated: Yes.
- Committed: Yes (intended as project planning artifacts).

---

*Structure analysis: 2026-04-04*
