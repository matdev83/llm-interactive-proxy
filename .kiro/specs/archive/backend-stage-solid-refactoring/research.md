# Research & Design Decisions

---
**Purpose**: Capture discovery findings, architectural investigations, and rationale that inform the technical design for this refactor.

**Project Context**: Universal LLM Proxy - FastAPI async, DI containers, staged initialization, adapter pattern.
---

## Summary
- **Feature**: `backend-stage-solid-refactoring`
- **Discovery Scope**: Extension (Complex integration / startup-critical refactor)
- **Key Findings**:
  - `ApplicationBuilder.validate_stages()` executes before any stage `execute()`, so backend validation must not rely on stage-executed registrations and must be leak-safe.
  - Global DI bootstrapping (`src/core/di/services.py:get_service_collection()`) pre-registers services with a default `AppConfig()`; without explicitly registering the runtime `AppConfig` before validation, DI-resolved services may observe the wrong config.
  - The current `BackendStage` contains fallback/manual validation and validation-time `httpx.AsyncClient` lifecycle logic; this duplicates `BackendFactory.ensure_backend()` shaping and is pinned by regression tests.

## Research Log

### Existing Codebase Analysis
- **Components Reviewed**:
  - `src/core/app/stages/backend.py` - current BackendStage responsibilities, fallbacks, and leak-prone validation client lifecycle
  - `src/core/services/backend_factory.py` - canonical initialization entry point (`ensure_backend`) with backend-specific conditional augmentation
  - `src/core/di/registrations/backend.py` and `src/core/di/registrations/_backend/*` - existing DI registrar patterns and idempotent helpers
  - `src/core/app/application_builder.py` - validation-before-execution staging behavior
  - `src/core/config/semantic_validation.py` - existing semantic config validation layer suitable for static route validation
  - Tests:
    - `tests/unit/core/app/stages/test_backend_startup_validation.py`
    - `tests/unit/core/app/stages/test_backend_stage_static_route_validation.py`
    - `tests/regression/test_backend_validation_client_leak_regression.py`
    - `tests/regression/test_backend_stage_cleanup_tasks_leak_regression.py`
    - `tests/regression/test_backend_stage_task_tracking_regression.py`
- **Patterns Identified**:
  - DI registration is orchestrated via focused registrars and `register_singleton_if_absent(...)` helpers.
  - The project maintains a legacy/global DI provider accessor via `src/core/di/provider_lifecycle.py` and `src/core/di/services.py`.
  - Connector discovery is import-time side effects: `import src.connectors` triggers module auto-import and backend registration.
  - `BackendConfig.api_key` is normalized to a string (`str | None`) by config models; legacy call sites still sometimes treat it like `list[str]`.
- **Implications**:
  - Validation must run without BackendStage fallbacks and without building ad-hoc dependencies; the application builder needs to supply/prepare the correct DI context for validation.
  - Strategy-based augmentation is the best fit for removing `BackendFactory` hardcoded branches while keeping connector-specific logic close to connectors.

### Validation Order & Resource Lifecycle
- **Context**: Requirements mandate SOLID-only validation (no BackendStage fallbacks) and leak-safety.
- **Sources Consulted**:
  - `src/core/app/application_builder.py` (validation and stage execution order)
  - `src/core/di/container.py` (ServiceCollection vs ServiceProvider lifecycles)
  - `src/core/di/provider_lifecycle.py` (global provider compatibility state)
- **Findings**:
  - Stage validation occurs before stage execution, so validation must not depend on stage `execute()` side effects.
  - Creating a `ServiceProvider` during validation can instantiate `httpx.AsyncClient` singletons; these must be disposed even when validation succeeds to prevent leaks in repeated build/test contexts.
  - `ServiceCollection.dispose()` exists and awaits cleanup tasks created during instance replacement, but `ApplicationBuilder.validate_stages()` currently does not dispose on validation failure.
- **Implications**:
  - The design uses a **validation-only service provider** built and disposed inside `validate_stages()` (not inside stages) to satisfy leak-safety and keep stages thin.
  - The runtime `AppConfig` must be registered into the `ServiceCollection` before validation so DI-resolved services use the correct configuration.

### Static Route Validation Placement
- **Context**: Current static route validation lives in `BackendStage._validate_static_route_backend`, but requirements move it to config validation.
- **Sources Consulted**:
  - `src/core/config/semantic_validation.py`
  - `src/core/config/models/backends.py` (presence of `static_route` field, registry-driven config population)
  - `src/connectors/__init__.py` / `src/core/services/backend_imports.py` (connector import side effects)
- **Findings**:
  - A semantic validation layer already exists and is the appropriate home for fail-fast config checks.
  - Static route validation requires backend registration to be present. Some entry points already import connectors early (CLI), but `ApplicationBuilder.build()` must ensure it in all contexts.
- **Implications**:
  - The design introduces a config-level validator for `static_route` and ensures connector auto-discovery runs before validating it.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Extend Existing (minimal new files) | Refactor in place inside BackendStage/BackendFactory | Lower initial churn | Prolongs god-class and makes test migration harder | Not preferred |
| New Components (clean split) | Introduce validator service, http client manager, strategy registry | Strong SRP boundaries, testable | Requires careful ordering/DI lifecycle design | Preferred building blocks |
| Hybrid / Strangler | Build new components and migrate usage incrementally | Low risk migration, regression-friendly | Temporary complexity if not aggressively completed | Selected approach |

## Design Decisions

### Decision: Validation Provider Lifecycle (Leak-Safe Stage Validation)
- **Context**: Validation runs before stage execution; repeated builds/tests must not leak `httpx.AsyncClient` instances created during validation.
- **Alternatives Considered**:
  1. Build providers inside `BackendStage.validate()` (rejected: violates SOLID goal and centralizes lifecycle risk in stage code).
  2. Skip backend functional validation during stage validation (rejected: breaks requirements).
  3. Build and dispose a validation-only provider in `ApplicationBuilder.validate_stages()` (selected).
- **Selected Approach**:
  - `ApplicationBuilder.validate_stages()` builds a service provider once for validation and disposes it on completion (success or failure).
  - Stages must not build providers; BackendStage delegates to DI-resolved services.
- **Trade-offs**:
  - Adds overhead of creating a provider during validation; mitigated by keeping validation provider short-lived and only instantiating what validation touches.

### Decision: Initialization Strategy Registry Location
- **Context**: OCP compliance requires adding backends without modifying BackendFactory/BackendStage.
- **Alternatives Considered**:
  1. Registry in `src/core/services/` (central, but drifts away from connectors).
  2. Registry in `src/connectors/strategies/` with import-time auto-registration (selected).
- **Selected Approach**:
  - Registry lives under `src/connectors/strategies/` and is imported as part of connector auto-discovery.

### Decision: Static Route Validation Placement
- **Context**: Must be config-level (fail-fast) and not stage-level.
- **Alternatives Considered**:
  1. Pydantic validators in config models (works, but requires careful import ordering).
  2. Semantic validation module (`src/core/config/semantic_validation.py`) (selected).
- **Selected Approach**:
  - Add static route validation to semantic validation and ensure connectors are imported before it runs.

## Testing Strategy Research

### Existing Test Patterns
- Unit tests for stage validation and internal helpers are extensive and assert internal behavior.
- Dedicated regression tests pin HTTP client/task leak fixes around BackendStage validation-time client creation.

### Implications for Refactor
- Stage-level tests must become **delegation-only**.
- Regression tests must be repointed to the new `ValidationHttpClientManager` and/or validation provider disposal behavior.

## Risks & Mitigations
- **Risk**: Startup validation allocates resources and leaks in failure or repeated build scenarios.  
  **Mitigation**: Validation-only provider is disposed deterministically; `ServiceCollection.dispose()` is called on failure paths.
- **Risk**: Import ordering issues cause static route validation to run before backends register.  
  **Mitigation**: Builder triggers `import src.connectors` before config validation.
- **Risk**: Behavior drift in “configured backends” detection.  
  **Mitigation**: Centralize detection logic in validation service and back it with migrated unit tests from stage tests.

## Performance Considerations
- Validation provider creation adds some overhead; it is bounded and does not impact steady-state request throughput.
- Strategy registry lookup is O(1) and should be negligible per backend init.

## References
- `src/core/app/application_builder.py` - stage validation/execution ordering
- `src/core/app/stages/backend.py` - current god-class responsibilities and fallbacks
- `src/core/services/backend_factory.py` - canonical backend initialization entry point
- `src/core/config/semantic_validation.py` - semantic config validation layer
- `src/connectors/__init__.py` - connector discovery/auto-registration
