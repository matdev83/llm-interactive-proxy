# Technology Stack (Steering)

## Stack Summary (Fact-Based)

- **Language**: Python 3.10+ (`pyproject.toml`)
- **Web framework**: FastAPI (async)
- **ASGI server**: uvicorn (`uvicorn[standard]`)
- **HTTP client**: httpx (async)
- **Validation/models**: Pydantic v2
- **Structured logging**: structlog
- **Wire capture encoding**: CBOR via `cbor2`
- **Database layer**: SQLModel + Alembic (see `src/core/database/` and `alembic.ini`)

This is intentionally not a dependency catalog; use `pyproject.toml` for the full list.

## Architecture (Where the “Truth” Lives)

### Staged initialization (startup)
The application starts via a staged bootstrap. Source of truth:
- Stage registry: `src/core/app/stages/application_stages.py`
- Stage implementations: `src/core/app/stages/`

Default stage order:
1. Infrastructure (`src/core/app/stages/infrastructure.py`)
2. Core services (`src/core/app/stages/core_services.py`)
3. Steering/safety wiring (`src/core/app/stages/steering.py`)
4. Backends (`src/core/app/stages/backend.py`)
5. Health checks (`src/core/app/stages/health_check.py`)
6. Command pipeline (`src/core/app/stages/command.py`)
7. Processing pipeline (`src/core/app/stages/processor.py`)
8. Controllers/routes (`src/core/app/stages/controller.py`)

### Dependency injection (DI)
- Container: `ServiceCollection` in `src/core/di/container.py`
- Bulk registrations: `src/core/di/services.py`
- Interfaces: `src/core/interfaces/` (`I*` naming, used for DI/test seams)
- Factory style: some registrations use an `IServiceProvider` factory for complex wiring

### Request processing (ProcessorStage)
The HTTP request path is orchestrated by a small “orchestrator” plus a set of internal phase components. Source of truth:
- Orchestrator: `RequestProcessor` in `src/core/services/request_processor_service.py` (stable alias: `src/core/services/request_processor.py`)
- Phase contracts: `src/core/interfaces/request_processor_internal.py`
- Wiring: `src/core/app/stages/processor.py`

Key pattern: keep `RequestProcessor` thin and delegate to phase components with clear boundaries:
- `ISessionEnricher`: session/client context enrichment
- `IRequestSideEffects`: best-effort side effects (fail-open)
- `ICommandHandler`: command processing and command-only fast-path
- `IBackendPreparer`: request preparation + validation (fail-fast on structured validation)
- `IRequestTransformPipeline`: outbound transforms in a fixed order
- `IBackendExecutor`: backend execution + persistence side effects

### Backend discovery/registration
- Import trigger: `src/core/services/backend_imports.py` is imported by `src/core/cli.py`
- Auto-discovery: `src/connectors/__init__.py` imports connector modules at import time
- Registry: `backend_registry` in `src/core/services/backend_registry.py`

### Backend completion flow (BackendService orchestration)
Backend calls are orchestrated via a dedicated coordinator that centralizes failover/retry/capture/usage behavior:
- Flow orchestrator: `BackendCompletionFlow` in `src/core/services/backend_completion_flow/service.py`
- Collaborator contracts: `src/core/interfaces/backend_completion_collaborators.py`
- Wiring: `src/core/di/services.py` and backend stage wiring in `src/core/app/stages/backend.py`

## Error Model

- Base exception: `LLMProxyError` in `src/core/common/exceptions.py`
- Pattern: domain/service code raises `LLMProxyError` subclasses; FastAPI layer maps to JSON responses.
- Adapters/handlers: see `src/core/app/error_handlers.py` and `src/core/transport/fastapi/exception_adapters.py`

## Configuration & Schemas

- Primary config surface: YAML files under `config/` (example: `config/config.example.yaml`)
- Schemas: `config/schemas/` (used for validation/documentation)
- Precedence is designed to be **CLI > ENV > YAML > defaults**:
  - Entry point: `src/core/cli.py`
  - Models/loader: `src/core/config/app_config.py`, `src/core/config/config_loader.py`
  - Resolution logic: `src/core/config/parameter_resolution.py`

## Observability & Captures

- Logs: `var/logs/`
- Wire captures:
  - CBOR: `var/wire_captures_cbor/`
  - JSON (debug): `var/wire_captures_json/`
- Inspection tool: `scripts/inspect_cbor_capture.py`
- Related docs: `docs/user_guide/debugging/cbor-capture.md`

## Development Tooling (What CI/Contributors Rely On)

### Formatting and linting
- Ruff is used for linting/import sorting (`[tool.ruff]` in `pyproject.toml`)
- Black is used for formatting (line length 88 by default; see `[tool.ruff] line-length = 88`)
- Ruff’s formatter is not used; Black is the formatter of record (see canonical commands below)

### Type checking
- Mypy is enabled (`[tool.mypy]` in `pyproject.toml`)
- Current posture is **not strict**, but typed defs are required:
  - `strict = false`
  - `disallow_untyped_defs = true`

### Tests
- Pytest is the test runner; markers are defined in `pyproject.toml` under `[tool.pytest.ini_options]`
- Default addopts are optimized for local runs (testmon + xdist); see `pyproject.toml` `[tool.pytest.ini_options] addopts`
- Slow/integration/codex suites are selected explicitly via `-m ...` (marker list is in `pyproject.toml`)

## Canonical Commands (Windows-first)

Use the in-repo venv interpreter:

```powershell
# Run the proxy (CLI entry point)
./.venv/Scripts/python.exe -m src.core.cli

# Default tests (respects addopts/markers in pyproject.toml)
./.venv/Scripts/python.exe -m pytest

# Explicit suites
./.venv/Scripts/python.exe -m pytest -m unit
./.venv/Scripts/python.exe -m pytest -m integration

# Lint / format / types
./.venv/Scripts/python.exe -m ruff check --fix .
./.venv/Scripts/python.exe -m black .
./.venv/Scripts/python.exe -m mypy src/
```

## Further Reading (Codebase-local)

- Architecture overview: `docs/development_guide/architecture.md`
- Code organization notes: `docs/development_guide/code-organization.md`

---

_Updated: 2025-12-17_
_Keep this file factual: describe stable patterns and point to sources of truth_
