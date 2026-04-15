# Technology Stack (Steering)

## Stack Summary (Fact-Based)

- **Language/runtime**: Python 3.10+ (`pyproject.toml`)
- **Application framework**: FastAPI with async handlers
- **ASGI server**: Uvicorn (`uvicorn[standard]`)
- **HTTP I/O**: `httpx[http2]` (async clients and transport helpers)
- **Data modeling/validation**: Pydantic v2 + SQLModel
- **Migrations**: Alembic
- **Wire capture format**: CBOR via `cbor2`
- **Logging**: Python logging with structured patterns (plus `structlog` dependency)

This file captures stable technical patterns; use `pyproject.toml` for exact versions.

## Runtime Composition (Source of Truth)

### Staged initialization

Startup is dependency-ordered and stage-driven:

- Stage registry: `src/core/app/stages/application_stages.py`
- Stage implementations: `src/core/app/stages/`

Default order:
1. `InfrastructureStage`
2. `CoreServicesStage`
3. `SteeringStage`
4. `BackendStage`
5. `HealthCheckStage`
6. `CommandStage`
7. `ProcessorStage`
8. `ControllerStage`

### Dependency injection

- Container + lifetimes: `src/core/di/container.py`
- Registration facade/orchestration: `src/core/di/services.py` and `src/core/di/registrations/`
- Contract seams: `src/core/interfaces/` (`I*` naming for service boundaries and testing seams)

### Core boundary split

The architecture uses a practical boundary split:

- `src/core/interfaces/`: DI/service contracts
- `src/core/ports/`: transport-neutral protocol/streaming contracts
- `src/core/adapters/`: translation helpers between external payloads and domain models
- `src/core/transport/fastapi/`: FastAPI-specific request/response/exception adapters

Guiding rule: keep FastAPI/Starlette details in transport/app layers; keep reusable
translation and orchestration logic transport-neutral.

### Request orchestration pattern

Request handling is organized as a thin orchestrator plus collaborator interfaces:

- Orchestrator: `RequestProcessor` in `src/core/services/request_processor_service.py`
- Internal contracts: `src/core/interfaces/request_processor_internal.py`
- Wiring: `src/core/app/stages/processor.py`

Typical collaborators include session enrichment, command handling, request transforms,
backend preparation, and backend execution.

### Backend orchestration and extensibility

Backend routing and completion flow are centralized in service orchestration:

- Registry: `src/core/services/backend_registry.py`
- Completion flow coordinator: `src/core/services/backend_completion_flow/service.py`
- Backend completion collaborator contracts:
  `src/core/interfaces/backend_completion_collaborators.py`

**Plugin architecture pattern** (stabilized via oauth-connectors-plugin-architecture):

- **In-repo connectors**: Live under `src/connectors/` and are imported directly via `src/core/services/backend_imports.py`
- **External plugins**: Discovered via Python entry points in group `llm_proxy_backends` through `src/core/services/backend_plugin_discovery.py`
- **Public contract**: Intentionally stable and narrow — only import from `src/core/plugin_api.py` (never deep-import `src.core.interfaces.*` or internal modules)
- **Capability-driven classification**: Use `BackendCapabilityDescriptor` (`requires_personal_auth`, `is_oauth_based`, `supports_streaming`, etc.) rather than name-based heuristics (`-oauth-` suffixes, hardcoded lists, or `backend_type` string matching)
- **Execution decoupling**: Core execution logic (e.g. `streaming_executor.py`) must interact with plugins only through explicit protocols such as `ITokenRefresher` (with methods like `refresh_token_if_needed()`). Avoid duck-typing on private attributes (`_oauth_credentials`, `_account_selector`)

**OAuth connector boundary lessons**:
- Core must not depend on specific plugin distribution names (`llm-interactive-proxy-oauth-connectors`) or individual backend names for control flow
- Test isolation is mandatory: core tests must not import optional plugin packages for behavior testing (narrow packaging contract tests are allowed)
- CLI extensibility: Plugins register arguments and config applicators via hooks on `BackendPluginDefinition` (`cli_arguments_hook`, `config_applicator_hook`)

Optional OAuth connector families are provided via extra dependency
`llm-interactive-proxy-oauth-connectors` (`[project.optional-dependencies].oauth`).

Capability declaration pattern:

- Backends declare protocol- and tool-related capabilities through typed configuration
  (`BackendCapabilityDescriptor`) rather than implicit connector attributes or naming conventions.
  - Model: `src/core/domain/backend_capability_descriptor.py`
  - Config wiring: `src/core/config/models/backends.py`
  - Extension pattern: Add new capability flags only when they represent cross-cutting concerns (not backend-specific quirks)

Stability expectations:

- Backend and plugin discovery must be idempotent and safe to run more than once (duplicate/invalid plugins are skipped with warnings)
- Plugin API surface (`plugin_api.py`) must remain stable — breaking changes require coordinated major version bumps
- Core should "fail open" on plugin issues where possible to protect core proxy functionality

## Error Model

- Base hierarchy: `LLMProxyError` (`src/core/common/exceptions.py`)
- Domain/service layers raise typed proxy exceptions
- Transport layer maps them to HTTP responses:
  `src/core/transport/fastapi/exception_adapters.py`

## Configuration Model

- Primary config artifacts: `config/*.yaml` + schema assets in `config/schemas/`
- Resolution order: **CLI > ENV > YAML > defaults**
- Main loader/model path:
  `src/core/config/app_config.py`, `src/core/config/config_loader.py`,
  `src/core/config/parameter_resolution.py`

## Observability and Diagnostics

- Logs: `var/logs/`
- Captures: `var/wire_captures_cbor/` (primary), `var/wire_captures_json/` (debug)
- Inspection tooling: `scripts/inspect_cbor_capture.py`
- Runtime diagnostics endpoints are part of the controller surface

## Development Toolchain Standards

### Lint/format

- Ruff (`ruff check --fix`) for linting and import organization
- Black for formatting (line length 88)

### Type checking

Mypy is enabled with a practical non-strict baseline:

- `strict = false`
- `warn_return_any = true`
- `warn_unused_configs = true`
- targeted overrides for third-party packages as needed

Pyright is also present (`pyrightconfig*.json`) and validated by the test suite in
practice; keep both mypy and pyright checks green when changing typed boundaries.

### Tests

- Pytest is the runner with async support (`pytest-asyncio`)
- Default run is parallelized (`pytest-xdist`, `-n 4 --dist=loadfile`)
- Timeout and marker conventions are centralized in `pyproject.toml`

### TDD posture

The expected workflow remains Red -> Green -> Refactor, with tests treated as
executable behavior contracts (see `.kiro/steering/testing.md`).

## Canonical Commands (Windows-first)

Use the in-repo venv interpreter:

```powershell
# Run the proxy
./.venv/Scripts/python.exe -m src.core.cli

# Run default tests
./.venv/Scripts/python.exe -m pytest

# Run selected suites
./.venv/Scripts/python.exe -m pytest -m unit
./.venv/Scripts/python.exe -m pytest -m integration

# Lint / format / types
./.venv/Scripts/python.exe -m ruff check --fix .
./.venv/Scripts/python.exe -m black .
./.venv/Scripts/python.exe -m mypy src/
```

## Near-Term Technical Priorities

- Keep compatibility contracts explicit and test-pinned on core protocol surfaces (`ITokenRefresher`, `BackendCapabilityDescriptor`, plugin API)
- Eliminate remaining name-based heuristics and duck-typing in core OAuth paths (follow-up from oauth-connectors-plugin-architecture work)
- Reduce coupling between core proxy path and optional/non-core features
- Improve resilience and diagnostics without widening architectural fragility
- Maintain plugin compatibility boundaries so external connector changes fail open
- Ensure CLI/plugin discovery lifecycle is correctly ordered (plugin hooks must be available during argument parsing)

## Further Reading

- `docs/development_guide/architecture.md`
- `docs/development_guide/code-organization.md`
- `docs/development_guide/plugin-api.md`
- oauth-connectors-plugin-architecture spec (for detailed plugin boundary and capability patterns)

---

_Updated: 2025-12-27_
_Reason: Add explicit TDD + tests-as-specification guidance_

_Updated: 2026-01-01_
_Reason: Document ports/adapters split added during refactors_

_Updated: 2026-04-06_
_Reason: Sync with current stage order, plugin discovery contract, and actual tooling posture from `pyproject.toml`_

_Updated: 2026-04-15_
_Reason: Incorporate lessons from oauth-connectors-plugin-architecture work — capability-driven classification, ITokenRefresher protocol usage, CLI/plugin discovery lifecycle, test isolation rules, and avoidance of name-based heuristics_
