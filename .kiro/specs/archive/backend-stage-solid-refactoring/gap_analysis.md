# Gap Analysis: Backend Stage SOLID Refactoring

> Note: `.kiro/specs/backend-stage-solid-refactoring/spec.json` shows `requirements.approved = false`.
> This gap analysis proceeds anyway (it can inform requirement revisions), but design should treat requirements as draft until approved.

## Analysis Summary (3–5 bullets)

- `src/core/app/stages/backend.py` currently combines stage orchestration, backend validation, per-backend initialization shaping, temporary `httpx.AsyncClient` lifecycle, and `static_route` validation; this conflicts with the SRP/OCP targets.
- The repo already has a centralized backend DI registrar (`src/core/di/registrations/backend.py`) and a real `BackendFactory.ensure_backend()` path, but `BackendStage` still has fallback/manual validation that duplicates initialization logic and adds leak-prone resource handling.
- Config/DI lifecycle constraints matter: stage validation runs before stage execution (`ApplicationBuilder.validate_stages()`), which makes “delegate to DI services” non-trivial unless config is injected (or validation avoids allocating resources).
- The largest integration cost is test migration: unit tests heavily assert `BackendStage` implementation details and regression tests pin temporary-client leak behavior.
- Viable approaches exist (extend existing, new components, hybrid), but the design phase must explicitly decide how validation is sequenced/cleaned up to avoid regressions.

## Document Status

- Framework: followed `.kiro/settings/rules/gap-analysis.md`
- Context loaded: `.kiro/specs/backend-stage-solid-refactoring/spec.json`, `.kiro/specs/backend-stage-solid-refactoring/requirements.md`, and all `.kiro/steering/*`
- Investigation method: codebase inspection via `rg`, targeted reads of key modules and tests

## 1) Current State Investigation

### Domain Assets (High-signal)

- **Backend stage (current “god class”)**
  - `src/core/app/stages/backend.py`
    - `execute()` imports connectors, validates `static_route`, calls `src.core.di.registrations.backend.register(...)`, and has a compatibility `BackendService` registration path.
    - `validate()` and `_validate_backend_functionality()` implement backend functional checks and test-environment exceptions.
    - `_manual_backend_validation()` duplicates backend initialization config shaping (Gemini/Anthropic/OpenRouter) and directly instantiates/initializes connectors.
    - `_register_validation_http_client()` and `_cleanup_validation_client()` implement a “temporary validation client” lifecycle and task tracking.
    - `_validate_static_route_backend()` validates that `static_route` backend exists in `backend_registry`.

- **Backend factory (central initialization path, still contains backend-specific branches)**
  - `src/core/services/backend_factory.py`
    - `ensure_backend()` already exists as the single “create + initialize” path used by `BackendStage._validate_backend_functionality()`.
    - Contains backend-specific augmentations for `anthropic`, `openrouter`, and `gemini` (hardcoded `if connector_type == ...` logic).

- **Backend DI registrations (already centralized)**
  - `src/core/di/registrations/backend.py` calls focused registrars under `src/core/di/registrations/_backend/`.
  - There is **no** `src/core/di/registrations/_backend/validation.py` today.

- **Backend discovery/registration**
  - `src/core/services/backend_imports.py` imports `src.connectors` at startup.
  - `src/connectors/__init__.py` auto-imports connector modules via `pkgutil.iter_modules(...)`.
  - `src/core/services/backend_registry.py` holds the registry used by connectors and validation.

- **Config models already depend on the registry**
  - `src/core/config/models/backends.py`:
    - `BackendSettings.__init__()` reads `backend_registry.get_registered_backends()` to populate missing backend config stubs.
    - `static_route` exists on `BackendSettings`, but there is no config-level validation ensuring the backend part is valid.

### Conventions & Architectural Constraints

- Staged initialization: `src/core/app/application_builder.py` calls `validate_stages()` before any stage `execute()`.
- Global DI bootstrapping: `src/core/di/services.py:get_service_collection()` eagerly registers all registrars (including backend) with `app_config=None`, which registers a default `AppConfig()` instance.
- Resource cleanup: `ServiceCollection.dispose()` exists and awaits cleanup tasks, but `ApplicationBuilder.validate_stages()` does not dispose resources on validation failure.

### Tests & Regression Pins (important constraints)

- Unit tests:
  - `tests/unit/core/app/stages/test_backend_startup_validation.py` heavily asserts `BackendStage.validate()` and `_validate_backend_functionality()` behavior.
  - `tests/unit/core/app/stages/test_backend_stage_static_route_validation.py` asserts the exact error messaging of `_validate_static_route_backend()`.
- Regression tests (resource leak prevention):
  - `tests/regression/test_backend_validation_client_leak_regression.py`
  - `tests/regression/test_backend_stage_cleanup_tasks_leak_regression.py`
  - `tests/regression/test_backend_stage_task_tracking_regression.py`

## 2) Requirements Feasibility Analysis

### Requirement-to-Asset Map (with Gaps Tagged)

| Requirement | Existing Assets | Gap Type | Notes / Constraints |
|---|---|---:|---|
| R1: Initialization strategies | `BackendFactory.ensure_backend()`; connector `initialize(**kwargs)` signatures | **Missing** | Strategy registry + strategy modules do not exist; factory still contains hardcoded backend-specific branches. |
| R2: Validation service | `BackendStage.validate()` and helpers | **Missing** | Needs extraction; must address stage validation running before stage execution/DI config injection. |
| R3: HTTP client manager | `BackendStage._register_validation_http_client()` and `_cleanup_validation_client()`; `ServiceCollection.dispose()` | **Missing** | Manager should own lifecycle; current stage-level cleanup does not run on validation failure, and builder doesn’t dispose on validation errors. |
| R4: Static route validation at config load | `BackendStage._validate_static_route_backend()`; `BackendSettings` model exists | **Missing / Constraint** | Config load already touches `backend_registry`; best insertion point may be config-model validation, but must ensure registry is populated in all entry points. |
| R5: BackendStage simplification | `src/core/di/registrations/backend.py` already centralizes DI registration | **Extend** | Stage still contains validation, temporary HTTP client logic, and static route validation; must be removed/moved. |
| R6: Duplication elimination | `BackendFactory.ensure_backend()` exists | **Constraint** | `_manual_backend_validation()` duplicates init shaping; removing it requires making the “real” factory path always available for validation. |
| R7: Test migration | Existing unit + regression tests above | **Missing** | Significant refactor required: new service tests, stage tests become delegation-only, regression tests repoint to manager. |
| R8: Interfaces + DI registration | `src/core/interfaces/*` pattern; DI registrars under `src/core/di/registrations/_backend/` | **Missing** | New Protocol interfaces and `validation.py` registrar required; backend registrar must call it. |

### Key Feasibility Concerns (Design-Phase Decisions Needed)

- **Validation sequencing vs DI**: `ApplicationBuilder.validate_stages()` runs before any stage `execute()`, but many backend validation paths assume `AppConfig` and `httpx.AsyncClient` are resolvable from DI. Today this is partially masked by global DI registering a default `AppConfig()`, which is not the runtime config.
- **Validation resource cleanup**: if validation allocates an `httpx.AsyncClient` (directly or via DI), there is no guaranteed cleanup path when validation fails (builder doesn’t call `ServiceCollection.dispose()` during validation).
- **Config-model mismatch risk**: `BackendConfig.api_key` is a `str | None` (normalized in `src/core/config/models/backends.py`), but legacy code paths still treat it like `list[str]` (e.g., stage fallback code). Any refactor that removes fallbacks reduces exposure to this mismatch.

## 3) Implementation Approach Options

### Option A: Extend Existing Components (minimal new concepts)

- Extend `src/core/services/backend_factory.py` to support strategy delegation while keeping the public API (`ensure_backend()`) stable.
- Gradually move validation out of `BackendStage` into a service but keep the stage-owned validation client until the end.

Trade-offs:
- ✅ Lower churn in wiring/bootstrapping initially
- ✅ Minimizes new files early
- ❌ Risk of keeping `BackendStage` bloated longer
- ❌ Harder to make unit tests target the “right” abstraction until late

### Option B: Create New Components (clean separation early)

- Add:
  - `src/core/services/backend_validation_service.py` (+ `IBackendValidator`)
  - `src/core/services/validation_http_client_manager.py` (+ `IHttpClientManager`)
  - `src/connectors/strategies/` package (registry + per-backend strategies)
  - `src/core/di/registrations/_backend/validation.py`
- Refactor `BackendStage` quickly to “import connectors + call backend registrar + delegate validate/cleanup”.

Trade-offs:
- ✅ Strong SRP boundaries and testability early
- ✅ Easier to isolate leak-prone lifecycle logic behind a single manager
- ❌ More integration points to get right up-front (DI + stage validation order)
- ❌ Requires earlier test migration (unit + regression)

### Option C: Hybrid (strangler fig with explicit validation-lifecycle plan)

- Build the new components (as in Option B), but introduce them behind compatibility adapters:
  - Keep existing `BackendStage.validate()` behavior initially, but internally delegate most logic to `BackendValidationService` (instantiated directly), then later switch to DI resolution once config injection/ordering is solved.
  - Keep existing regression tests passing by providing a compatibility façade for temporary-client creation/cleanup, then repoint tests after behavior is stable.

Trade-offs:
- ✅ Reduces “big bang” risk and allows incremental verification
- ✅ Keeps rollout flexible if stage-validation ordering needs adjustment
- ❌ Requires disciplined migration plan to avoid “two sources of truth” lingering

## 4) Implementation Complexity & Risk

- **Effort**: **M (3–7 days)** — broad surface area (stage, factory, DI registration, connectors strategies, tests + regressions), but clear extraction boundaries exist.
- **Risk**: **Medium–High** — startup critical path + leak regression sensitivity + validation/DI ordering concerns.

## 5) Research Needed (carry into design phase)

- **Stage validation contract**: confirm whether `validate_stages()` is intended to be “pure/no allocation” or allowed to allocate resources; if allocation is allowed, determine required cleanup hooks.
- **Config injection**: decide how runtime `AppConfig` becomes authoritative in DI *before* validation (builder change vs “service uses passed config”).
- **Strategy discovery/registration**: decide how `src/connectors/strategies/` is imported so new strategies register without touching `BackendStage`/`BackendFactory` (once the system is in place).
- **Environment/API key precedence**: unify how “configured backend” detection works (config vs `*_API_KEY` env vars vs numbered keys) so validation does not drift from runtime behavior.
- **Static route validation placement**: determine whether to implement in config models (`BackendSettings` validator) vs a dedicated config validator invoked by `ApplicationBuilder.build()` pre-stages.

## Next Steps (Design Phase)

- Use this gap analysis to author a design that explicitly answers:
  - validation sequencing + cleanup strategy
  - where strategies live and how they register
  - where static route validation runs (and how it sees registered backends)
- Then run `/prompts:kiro-spec-design backend-stage-solid-refactoring` (or `-y` to auto-approve requirements first).
