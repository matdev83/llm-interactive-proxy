# Requirements Document

## Project Description (Input)

**Problem Statement:**
The `BackendStage` class (`src/core/app/stages/backend.py`, 760 lines) is a god class that severely violates SOLID principles, specifically Single Responsibility Principle (SRP) and Open/Closed Principle (OCP). This violation has significant real-world impact on maintainability, testability, and extensibility.

**Current State:**
BackendStage currently has 7+ distinct responsibilities:
1. DI Container Registration (lines 65-134)
2. Backend Validation Logic (lines 136-223)
3. Backend Functionality Checks (lines 224-416)
4. Manual Backend Construction with Hardcoded Config (lines 417-598) - DUPLICATES BackendFactory logic
5. HTTP Client Lifecycle Management (lines 600-684) - Complex and leak-prone
6. Static Route Validation (lines 738-760)
7. TranslationService Registration (lines 450-496)

**Additional Findings (Gap Analysis):**
- **Stage validation order matters**: `ApplicationBuilder.validate_stages()` runs *before* any stage `execute()`. Validation that allocates resources (DI provider build, http clients, etc.) must be leak-safe or avoided.
- **Backend DI is already centralized**: `src/core/di/registrations/backend.py` exists and should be the single orchestration point for backend-related registrations; BackendStage should not do “extra” registration work beyond calling the registrar.
- **Config validation already exists**: there is an existing semantic validation layer under `src/core/config/semantic_validation.py`; static route validation should live there (or an equivalent config-level validator), not in BackendStage.

**Evidence of Impact:**
- **Code Duplication:** Backend-specific initialization logic hardcoded in TWO places (BackendStage lines 525-546 AND BackendFactory lines 202-221)
- **Testing Burden:** 22+ test cases, 600+ lines of test code just for BackendStage validation
- **Maintenance Cost:** Adding new backend requires modifying 4 places (2 in BackendStage, 2 in BackendFactory)
- **Resource Leaks:** Dedicated regression tests exist for HTTP client leaks caused by complex lifecycle management
- **OCP Violation:** Every new backend requires modifying existing code (hardcoded `if backend_name ==` logic)

**Target State:**
Extract BackendStage's responsibilities into focused, single-purpose components:
- BackendStage: ONLY DI registration orchestration (~100 lines, 86% reduction)
- BackendValidationService: Standalone validation logic
- ValidationHttpClientManager: HTTP client lifecycle
- BackendInitializationStrategy: Per-backend configuration (Strategy Pattern)
- ConfigValidator: Static route validation (config-level, not stage-level)

**Success Metrics:**
- BackendStage reduced from 760 → ~100 lines (86% reduction)
- Zero code duplication between BackendFactory and BackendStage
- New backends added via strategy pattern (1 file instead of 4 files)
- Test complexity reduced by 80%
- All 12,824 existing tests pass
- No performance regression (startup time ≤ baseline)

**Scope:**
- 53 files affected (14 core, 9 DI registrations, 19 connectors, 15 tests)
- Risk Level: Medium (requires careful DI coordination)
- Estimated Effort: 3-5 days

---

## Introduction

This specification defines the requirements for refactoring the BackendStage god class into focused, single-purpose components that adhere to SOLID principles. The refactoring eliminates code duplication, reduces testing complexity, and enables backend extensibility through the Strategy Pattern.

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture using staged initialization.

**Stakeholders**:
- Developers adding new backend connectors
- Maintainers debugging backend initialization and validation
- Test engineers writing and maintaining backend-related tests
- Operations teams deploying and troubleshooting backend configurations

---

## Requirements

### Requirement 1: Backend Initialization Strategy Extraction

**Objective:** As a developer adding new backend connectors, I want backend-specific initialization logic encapsulated in strategies, so that I can add new backends without modifying existing code (OCP compliance).

**Priority:** P0 (Critical)

#### Acceptance Criteria

- 1.1 When a new backend is added to the system, the Initialization Strategy Registry shall accept registration without requiring modification to BackendFactory or BackendStage source code.
- 1.2 The Backend Initialization Strategy Interface shall define a method `augment_init_config(init_config: dict[str, Any]) -> dict[str, Any]` that accepts backend initialization kwargs and returns backend-specific augmented initialization kwargs.
- 1.3 When BackendFactory initializes a backend, the Backend Initialization Strategy Registry shall provide the appropriate strategy based on backend type (connector name).
- 1.4 If no custom initialization strategy is registered for a backend, then the Backend Initialization Strategy Registry shall provide a default strategy that passes configuration unmodified.
- 1.5 The BackendFactory shall delegate all backend-specific configuration augmentation to initialization strategies and shall not contain hardcoded `if backend_name ==` logic.
- 1.6 When BackendStage validates a backend, the validation logic shall use BackendFactory.ensure_backend() and shall not duplicate backend initialization logic.
- 1.7 The Backend Initialization Strategy implementations shall be colocated with their respective backend connectors under `src/connectors/strategies/` directory.
- 1.8 The following backends shall have dedicated initialization strategies: Anthropic, Gemini, OpenRouter (replacing lines 525-546 in BackendStage and lines 202-221 in BackendFactory).

#### Technical Constraints

- Async compatibility: Strategy augmentation must be compatible with async backend initialization flows
- DI integration: Strategy resolution must not depend on BackendStage (strategies can register via module import side effects and/or DI registration)
- Error hierarchy: Invalid configuration raises `LLMProxyError` subclass
- Backward compatibility: All existing backend initialization behavior must be preserved

---

### Requirement 2: Backend Validation Service Extraction

**Objective:** As a test engineer, I want backend validation logic isolated in a standalone service, so that I can test validation independently without instantiating the entire initialization stage.

**Priority:** P0 (Critical)

#### Acceptance Criteria

- 2.1 The Backend Validation Service shall perform all validation logic independently of BackendStage and shall be constructible with explicit dependencies (via constructor injection) for unit testing.
- 2.2 When the Backend Validation Service is invoked, the service shall identify all configured backends from AppConfig (default_backend, static_route, and named backend configurations).
- 2.3 When the Backend Validation Service checks backend functionality, the service shall use BackendFactory.ensure_backend() to create backend instances and shall not duplicate backend instantiation logic.
- 2.4 If a backend's `is_backend_functional()` method returns false, then the Backend Validation Service shall collect the backend name and any validation errors for reporting.
- 2.5 When all configured backends are non-functional and the environment is not a test environment, then the Backend Validation Service shall return validation failure (False).
- 2.6 When no backends are configured, then the Backend Validation Service shall allow startup for minimal/test environments and shall log a warning.
- 2.7 If the environment variable `PYTEST_CURRENT_TEST` is set and no functional backends exist, then the Backend Validation Service shall allow startup for test environments.
- 2.8 The BackendStage.validate() method shall delegate to Backend Validation Service and shall contain fewer than 20 lines of code (delegation only).
- 2.9 The Backend Validation Service shall be registered in the DI container via `src/core/di/registrations/_backend/validation.py` registrar.
- 2.10 If required validation dependencies (e.g., BackendFactory) cannot be resolved from DI, then the Backend Validation Service shall fail fast (raise `ServiceResolutionError` or `InitializationError`) and BackendStage shall not implement any fallback/manual validation path.
- 2.11 When `ApplicationBuilder.validate_stages()` runs, the builder shall establish a validation DI context that is accessible to stage validation without requiring any stage to build a ServiceProvider (for example, by temporarily setting the validation provider via `src.core.di.provider_lifecycle.set_service_provider(...)` behind a lock / context manager and restoring the previous provider afterward), and the validation provider build shall not execute unrelated post-build hooks.

#### Technical Constraints

- Async compatibility: All validation methods must use `async/await`
- DI integration: Service implements `IBackendValidator` interface
- Test isolation: Service can be instantiated independently for unit testing
- Environment detection: Must respect `PYTEST_CURRENT_TEST` for test environment handling

---

### Requirement 3: HTTP Client Lifecycle Management Extraction

**Objective:** As a maintainer, I want HTTP client lifecycle management isolated in a dedicated manager, so that resource leaks are prevented and cleanup logic is testable in isolation.

**Priority:** P0 (Critical)

#### Acceptance Criteria

- 3.1 The Validation HTTP Client Manager shall encapsulate all HTTP client creation, registration, and cleanup logic (replacing BackendStage lines 600-736).
- 3.2 When the Validation HTTP Client Manager creates an HTTP client, the manager shall attempt HTTP/2 configuration first and shall fallback to HTTP/1.1 if HTTP/2 initialization fails.
- 3.3 When the Validation HTTP Client Manager registers a client in the DI container, the manager shall track the client reference for cleanup and shall add the client to ServiceCollection.
- 3.4 If an exception occurs during client creation after the client object is instantiated, then the Validation HTTP Client Manager shall immediately close the client to prevent resource leaks.
- 3.5 When the Validation HTTP Client Manager cleans up resources, the manager shall close the validation client if it exists and is not already closed.
- 3.6 When cleanup tasks are pending, the Validation HTTP Client Manager shall wait for task completion with a 5-second timeout and shall cancel tasks if timeout is exceeded.
- 3.7 After cleanup completes (successful or timeout), the Validation HTTP Client Manager shall clear the cleanup tasks set to prevent memory leaks from task references.
- 3.8 The Validation HTTP Client Manager shall be registered in the DI container and shall be injected into Backend Validation Service.
- 3.9 When BackendStage cleanup is triggered, the stage shall delegate to Validation HTTP Client Manager and shall not directly manage httpx.AsyncClient lifecycle.
- 3.10 When stage validation fails (returns False or raises), then application startup code shall dispose of the `ServiceCollection` (or otherwise invoke cleanup) so that any validation-created http client resources cannot leak.

#### Technical Constraints

- Async compatibility: All cleanup methods must be async
- DI integration: Manager implements `IHttpClientManager` interface
- Resource safety: All client references must be properly tracked and cleaned up
- Regression prevention: All existing resource leak regression tests must pass

---

### Requirement 4: Static Route Configuration Validation Extraction

**Objective:** As an operator, I want static route validation to fail-fast during runtime configuration validation, so that invalid configurations are rejected before stage execution begins.

**Priority:** P1 (High)

#### Acceptance Criteria

- 4.1 When the final resolved application configuration is validated during `ApplicationBuilder.build()`, the Config Validator shall validate that `static_route` backend names reference registered backends.
- 4.2 If static_route specifies a backend that is not registered, then the Config Validator shall raise `ConfigurationError` with the invalid backend name, list of available backends, and expected format.
- 4.3 The Config Validator error message shall include the current static_route value and an example of correct usage (e.g., `gemini-oauth-plan:gemini-2.5-pro`).
- 4.4 When ApplicationBuilder.build() is invoked, configuration validation shall occur before any initialization stage executes.
- 4.5 The BackendStage shall not perform static route validation and shall not contain the `_validate_static_route_backend()` method.
- 4.6 The static route validation logic (BackendStage lines 738-759) shall be moved into the existing config validation layer (e.g., `src/core/config/semantic_validation.py`) or an equivalent dedicated config validator module.
- 4.7 If static route validation requires backend registration to be present, then ApplicationBuilder.build() shall ensure connector auto-discovery has been triggered (equivalent to importing `src.connectors`) before performing static route validation.
- 4.8 Static route validation shall run against the final resolved `AppConfig` (after YAML/ENV/CLI merging) and shall not be implemented as YAML-file-only semantic validation that runs on raw dict data before connector auto-discovery.

#### Technical Constraints

- Fail-fast behavior: Validation must occur before stage execution
- Error messages: Must provide actionable feedback with examples
- Backward compatibility: Same validation behavior as current implementation

---

### Requirement 5: BackendStage Simplification and Consolidation

**Objective:** As a developer, I want BackendStage to have a single responsibility (DI registration orchestration), so that the stage is maintainable, testable, and follows SRP.

**Priority:** P0 (Critical)

#### Acceptance Criteria

- 5.1 After refactoring, the BackendStage class shall contain fewer than 150 lines of code total (86% reduction from 760 lines).
- 5.2 The BackendStage.execute() method shall perform exactly two responsibilities: importing connectors to trigger auto-registration, and invoking the backend DI registrar.
- 5.3 The BackendStage.validate() method shall delegate to Backend Validation Service and shall contain delegation logic only (fewer than 20 lines).
- 5.4 The BackendStage shall not contain the following methods: `_validate_backend_functionality`, `_manual_backend_validation`, `_register_validation_http_client`, `_cleanup_validation_client`, `_validate_static_route_backend`, `_register_backend_service`.
- 5.5 The BackendStage shall not directly manage httpx.AsyncClient lifecycle and shall not track `_validation_client` or `_cleanup_tasks` instance variables.
- 5.6 When BackendStage executes, the stage shall call `src.core.di.registrations.backend.register(services, config)` to register all backend-related services.
- 5.7 The BackendStage docstring shall clearly state its single responsibility: "Stage for registering backend-related services via DI registrar and delegating validation."
- 5.8 The BackendStage shall not contain conditional logic, exception handling for ServiceResolutionError, or fallback paths for missing services.
- 5.9 The BackendStage.validate() method shall not build a service provider, shall not mutate the ServiceCollection, and shall not instantiate backends or HTTP clients directly (delegation only).

#### Technical Constraints

- DI integration: Stage must register services via centralized registrar
- Validation delegation: Must use IBackendValidator interface from DI
- Simplicity: Stage logic must be easily understood in under 5 minutes

---

### Requirement 6: Code Duplication Elimination

**Objective:** As a maintainer, I want zero code duplication between BackendFactory and BackendStage, so that backend initialization logic has a single source of truth.

**Priority:** P0 (Critical)

#### Acceptance Criteria

- 6.1 After refactoring, BackendFactory and BackendStage shall not contain duplicate backend-specific initialization logic.
- 6.2 The BackendStage._manual_backend_validation() method (lines 417-598, 180 lines) shall be deleted and removed from the codebase.
- 6.3 When Backend Validation Service validates backends, the service shall always use BackendFactory.ensure_backend() and shall not manually instantiate backends.
- 6.4 The BackendFactory.ensure_backend() method shall be the single source of truth for backend initialization with configuration augmentation.
- 6.5 Backend-specific initialization logic (Anthropic, Gemini, OpenRouter) shall exist only in initialization strategies under `src/connectors/strategies/`.
- 6.6 The BackendFactory shall not contain hardcoded `if connector_type ==` logic for backend-specific augmentation (lines 202-221 shall be replaced with strategy delegation).
- 6.7 When a backend initialization strategy is not found, the Backend Initialization Strategy Registry shall log a warning and shall use default strategy behavior.
- 6.8 The refactoring shall remove BackendStage legacy/fallback/manual validation logic that duplicates initialization (including any “temporary backend factory” and “temporary http client” paths); validation must use the SOLID components exclusively.

#### Technical Constraints

- Single source of truth: Only one code path for backend initialization
- Strategy pattern: Backend-specific logic in strategies, not conditionals
- Maintainability: Changes to backend initialization require modifying one strategy only

---

### Requirement 7: Test Migration and Simplification

**Objective:** As a test engineer, I want backend validation tests migrated to new components, so that test complexity is reduced and components can be tested in isolation.

**Priority:** P1 (High)

#### Acceptance Criteria

- 7.1 When tests are migrated, the test file `tests/unit/core/app/stages/test_backend_startup_validation.py` shall contain fewer than 5 test cases (delegation tests only).
- 7.2 The new test file `tests/unit/core/services/test_backend_validation_service.py` shall contain 15+ test cases covering all validation scenarios previously tested in BackendStage.
- 7.3 The new test file `tests/unit/core/services/test_validation_http_client_manager.py` shall contain tests for HTTP client creation, registration, cleanup, and error handling.
- 7.4 The regression test files for resource leaks shall be updated to test Validation HTTP Client Manager instead of BackendStage: `test_backend_stage_cleanup_tasks_leak_regression.py`, `test_backend_validation_client_leak_regression.py`, `test_backend_stage_task_tracking_regression.py`.
- 7.5 When Backend Validation Service tests run, the tests shall instantiate the service directly without requiring BackendStage or full application initialization.
- 7.6 When HTTP Client Manager tests run, the tests shall verify resource cleanup without memory leaks using the existing regression test patterns.
- 7.7 The test file `tests/unit/core/app/stages/test_backend_stage_static_route_validation.py` shall be moved to `tests/unit/core/config/test_config_validator.py` (static route validation).
- 7.8 All 12,824 existing tests shall pass after refactoring with no changes to test behavior or assertions (only test organization changes).

#### Technical Constraints

- Test isolation: New component tests must not require full DI container
- Regression coverage: All existing test scenarios must be preserved
- Test maintainability: Tests should target the appropriate component level

---

### Requirement 8: Interface Definitions and DI Registration

**Objective:** As a developer, I want clear interface contracts for new components, so that dependencies are explicit and components can be mocked for testing.

**Priority:** P0 (Critical)

#### Acceptance Criteria

- 8.1 The project shall define the `IBackendValidator` interface in `src/core/interfaces/backend_validator_interface.py` with method `async validate_all(config: AppConfig) -> bool`.
- 8.2 The project shall define the `IBackendInitializationStrategy` interface in `src/core/interfaces/backend_initialization_strategy_interface.py` with method `augment_init_config(init_config: dict[str, Any]) -> dict[str, Any]`.
- 8.3 The project shall define the `IHttpClientManager` interface in `src/core/interfaces/http_client_manager_interface.py` with methods `get_or_create_client() -> httpx.AsyncClient` and `async cleanup()`.
- 8.4 The Backend Validation Service shall implement `IBackendValidator` interface and shall be registered as a singleton in the DI container.
- 8.5 The Validation HTTP Client Manager shall implement `IHttpClientManager` interface and shall be registered as a singleton in the DI container.
- 8.6 The Backend Initialization Strategy Registry shall provide method `get_strategy(backend_type: str) -> IBackendInitializationStrategy` and shall return default strategy if custom strategy not found.
- 8.7 The DI registrar `src/core/di/registrations/_backend/validation.py` shall register Backend Validation Service and Validation HTTP Client Manager.
- 8.8 When services are registered, the DI registrations shall follow the existing pattern of focused registrar files under `src/core/di/registrations/_backend/`.

#### Technical Constraints

- Interface contracts: All interfaces must follow Protocol pattern for type safety
- DI patterns: Follow existing registration patterns in `src/core/di/registrations/`
- Type hints: All interface methods must have complete type annotations

---

### Requirement 9: Eliminate BackendStage Legacy/Fallback Validation (SOLID-Only Path)

**Objective:** As a maintainer, I want backend validation and initialization to follow one SOLID-compliant path with no legacy fallbacks, so that startup behavior is deterministic and resource leaks cannot be reintroduced by duplicated logic.

**Priority:** P0 (Critical)

#### Acceptance Criteria

- 9.1 BackendStage shall not contain any validation-time fallback logic (no manual backend instantiation, no temporary DI wiring, no temporary TranslationService registration, and no temporary `httpx.AsyncClient` creation).
- 9.2 The only backend validation implementation shall be the Backend Validation Service (`IBackendValidator`), and the only backend initialization implementation shall be `BackendFactory.ensure_backend()` + initialization strategies.
- 9.3 If backend validation cannot proceed because required dependencies are missing, then startup shall fail fast with a clear error (no “best effort” fallback to legacy logic).
- 9.4 All existing leak regression coverage currently targeting BackendStage validation-client lifecycle shall be repointed to the Validation HTTP Client Manager, and BackendStage shall no longer expose `_validation_client` / `_cleanup_tasks` state for tests.
- 9.5 When ApplicationBuilder.build() is invoked with a runtime `AppConfig`, the builder shall register that `AppConfig` instance (and its `IConfig` binding) into the `ServiceCollection` as a replacement for any default/global registration before `validate_stages()` runs, so DI-resolved services observe the same configuration that the builder was given.

#### Technical Constraints

- Reliability: validation must not allocate resources that cannot be deterministically cleaned up on failure.

## Non-Functional Requirements

### NFR 1: Performance

**Requirement:** The refactoring shall not introduce performance regression in application startup time.

#### Acceptance Criteria

- 10.1 When the application starts with the refactored BackendStage, startup time shall be less than or equal to baseline startup time (measured with 10 iterations).
- 10.2 When Backend Validation Service validates backends, validation duration shall be less than or equal to current validation duration.
- 10.3 When initialization strategies are invoked, the strategy pattern shall introduce less than 5ms overhead per backend initialization.

---

### NFR 2: Reliability

**Requirement:** The refactoring shall maintain or improve system reliability regarding resource management and error handling.

#### Acceptance Criteria

- 11.1 When HTTP clients are created for validation, the Validation HTTP Client Manager shall prevent resource leaks in all error scenarios (verified by regression tests).
- 11.2 When BackendStage validation fails, the application shall fail-fast with clear error messages (existing behavior preserved).
- 11.3 When a backend initialization strategy raises an exception, the Backend Initialization Strategy Registry shall propagate the exception with context about which backend failed.
- 11.4 When cleanup is interrupted by exceptions, the Validation HTTP Client Manager shall still close all tracked resources (fail-safe cleanup).

---

### NFR 3: Observability

**Requirement:** The refactoring shall maintain existing logging behavior and shall not reduce visibility into backend initialization.

#### Acceptance Criteria

- 12.1 When backends are initialized via strategies, the BackendFactory shall log initialization details at INFO level with backend name and configuration.
- 12.2 When Backend Validation Service detects non-functional backends, the service shall log detailed validation errors at ERROR level.
- 12.3 When the Validation HTTP Client Manager performs cleanup, the manager shall log cleanup actions at DEBUG level.
- 12.4 When static route validation fails, the Config Validator shall log the validation error with actionable error messages before raising an exception (including when raising `ConfigurationError` per `4.2`).

---

### NFR 4: Maintainability

**Requirement:** The refactoring shall improve code maintainability by reducing complexity, eliminating duplication, and improving testability.

#### Acceptance Criteria

- 13.1 After refactoring, adding a new backend shall require modifying exactly 1 file (creating a new initialization strategy) instead of 4 files.
- 13.2 After refactoring, the cyclomatic complexity of BackendStage shall be reduced by at least 80% (measured by code complexity tools).
- 13.3 After refactoring, backend initialization and validation behavior shall be covered by unit/regression tests at least as thoroughly as before the refactor (by migrating existing test scenarios to the new components and adding focused unit tests for the new strategy/validation boundaries).
- 13.4 After refactoring, the repository shall include an executable example demonstrating how to add a backend-specific initialization strategy without editing BackendFactory or BackendStage (for example, an example strategy module + a unit test that asserts the registry selects it).

---

### NFR 5: Backward Compatibility

**Requirement:** The refactoring shall maintain backward compatibility with existing backend configurations and behavior.

#### Acceptance Criteria

- 14.1 All existing backend connectors (OpenAI, Anthropic, Gemini, OpenRouter, etc.) shall continue to initialize and function identically after refactoring.
- 14.2 All existing configuration files (`config/config.example.yaml`) shall work without modification after refactoring.
- 14.3 All existing CLI flags and environment variables related to backend configuration shall work without modification.
- 14.4 The public API surface of BackendFactory (methods like `ensure_backend()`) shall remain unchanged for backward compatibility.

---

## Glossary

| Term | Definition |
|------|------------|
| BackendStage | Initialization stage responsible for registering backend-related services in the DI container |
| BackendFactory | Service responsible for creating and initializing LLM backend connector instances |
| Backend Connector | Provider-specific adapter that calls external LLM APIs (OpenAI, Anthropic, Gemini, etc.) |
| Initialization Strategy | Strategy pattern implementation for backend-specific configuration augmentation |
| SOLID Principles | Software design principles: Single Responsibility, Open/Closed, Liskov Substitution, Interface Segregation, Dependency Inversion |
| SRP (Single Responsibility) | A class should have only one reason to change |
| OCP (Open/Closed) | Software entities should be open for extension but closed for modification |
| DI Container | Dependency Injection container (`ServiceCollection`) for service registration and resolution |
| EARS Format | Easy Approach to Requirements Syntax for writing testable acceptance criteria |
| God Class | Anti-pattern where a class has too many responsibilities and knows too much |
| Wire Capture | CBOR-encoded binary recording of LLM API traffic for debugging |
| Staged Initialization | Sequential initialization phases (Infrastructure → Services → Backends → Controllers) |
