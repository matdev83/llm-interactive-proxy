# Implementation Tasks

## Phase 1: Core Plugin Infrastructure

### Task 1.1: Implement BackendDiscoveryService
- **Description**: Create a new service `src/core/services/backend_discovery.py` that uses `importlib.metadata.entry_points` to scan the `llm_proxy_backends` group.
- **Details**:
    - Implement `discover_external_backends` method.
    - Add version compatibility check (`min_core_version`).
    - Handle loading failures gracefully with logging.
- **Traceability**: Req 1.1, 1.3, 1.4, 2.6
- **Status**: pending

### Task 1.2: Update BackendRegistry for Metadata Tracking
- **Description**: Update `BackendRegistry` to store metadata about discovered backends (e.g., whether it's a plugin, compatibility version, optional DI hooks).
- **Details**:
    - Add methods to store and retrieve plugin metadata.
    - Ensure thread-safe access to metadata.
- **Traceability**: Req 1.5, 2.3
- **Status**: pending

### Task 1.3: Integrate Discovery into src/connectors/__init__.py
- **Description**: Call `BackendDiscovery.discover_external_backends()` within `src/connectors/__init__.py` to ensure plugins are loaded alongside internal connectors.
- **Traceability**: Req 1.1, 1.2
- **Status**: pending

## Phase 2: DI Hardening & Pluggable Service Registration

### Task 2.1: Implement Pluggable DI Hook in Backend Registrar
- **Description**: Update `src/core/di/registrations/backend.py` to iterate through registered plugins and call an optional `register_services` hook if provided by the plugin.
- **Traceability**: Req 2.5
- **Status**: pending

### Task 2.2: Guard Core DI against Missing Extracted Connectors
- **Description**: Refactor `src/core/di/registrations/backend.py` and its sub-modules (`codex.py`, `gemini.py`) to use conditional imports and registrations.
- **Details**:
    - Wrap Codex and Gemini registration calls in try-except or check for package presence.
- **Traceability**: Req 2.5, 3.3
- **Status**: pending

## Phase 3: Runtime Behavior & Validation

### Task 3.1: Enhance BackendValidationService with Actionable Warnings
- **Description**: Update `src/core/services/backend_validation_service.py` to detect configurations referencing extracted but unregistered backends.
- **Details**:
    - Add `KNOWN_EXTRACTED_BACKENDS` list.
    - Implement logic to suggest `pip install llm-interactive-proxy[oauth]` in warnings.
- **Traceability**: Req 3.2, 3.5
- **Status**: pending

### Task 3.2: Implement Request-Time Error Handling for Unregistered Backends
- **Description**: Ensure that requests targeting a configured but unregistered backend return a clear error response (503 Service Unavailable or similar) instead of crashing.
- **Traceability**: Req 3.4
- **Status**: pending

## Phase 4: Consolidation & Extraction

### Task 4.1: Consolidate Universal Mixins and Utils
- **Description**: Move truly universal mixins (e.g., `usage_calculation_mixin.py`) and utils to a stable location in core (e.g., `src/connectors/base_mixins.py`).
- **Traceability**: Req 2.4, 3.1
- **Status**: pending

### Task 4.2: Move OAuth Connectors to External Package
- **Description**: Physically move the 13 identified OAuth-based connectors and their dedicated tests/utilities to the new `llm-proxy-oauth-connectors` repository.
- **Traceability**: Req 2.1, 2.2, 6.3
- **Status**: pending

## Phase 5: Packaging & Installation

### Task 5.1: Update Core pyproject.toml
- **Description**: Move OAuth-only dependencies (`google-auth`, `watchdog`, etc.) to an optional extra named `oauth`.
- **Details**:
    - Define `oauth` extra that depends on the external package.
- **Traceability**: Req 5.1, 5.2, 5.3
- **Status**: pending

### Task 5.2: Create pyproject.toml for External Package
- **Description**: Define the metadata, dependencies, and entry points for the `llm-proxy-oauth-connectors` package.
- **Traceability**: Req 2.2, 5.3
- **Status**: pending

## Phase 6: Testing & Verification

### Task 6.1: Implement Core Mock Discovery Tests
- **Description**: Add unit tests in core using `unittest.mock` to verify that `BackendDiscovery` correctly handles mocked entry points.
- **Traceability**: Req 6.1, 6.2
- **Status**: pending

### Task 6.2: Final Integration Verification
- **Description**: Verify that the proxy starts and functions correctly with and without the `oauth` extra installed.
- **Traceability**: Req 4.1, 4.2, 6.3
- **Status**: pending
