# Tasks: Refactor Backend Connectors

- [ ] **1. Create TDD Tests for Configuration & Discovery** <!-- id: 0 -->
    -   Create `tests/unit/core/config/test_backend_discovery.py`.
    -   Test regex matching for instance names.
    -   Test env var scanning (Strategy A) with mocked environment.
    -   Test file scanning (Strategy B) with temporary directories.
    -   Test fallback logic for file-based connectors.
    -   Test uniqueness validation errors.

- [ ] **2. Multimodal Input Types Registry** <!-- id: 1 -->
    -   Create `src/core/domain/multimodal_types.py` with a dictionary of standard input types.
    -   Update `BackendConfig` in `src/core/config/app_config.py` to include `supported_input_types: list[str] | None`.

- [ ] **3. Update Configuration Schema & Implementation** <!-- id: 2 -->
    -   Modify `BackendConfig` to add `allow_concurrent_use: bool = True`.
    -   Ensure `BackendConfig` has `api_url` and `credentials_path`.
    -   Update `BackendSettings` to support arbitrary backend keys.
    -   Implement `_discover_backend_instances` method in `BackendSettings` (or helper) to pass the tests created in Task 1.

- [ ] **4. Create TDD Tests for Factory & Routing** <!-- id: 3 -->
    -   Create `tests/unit/core/services/test_backend_routing.py`.
    -   Test factory resolution of connector from instance name.
    -   Test Round Robin selection logic.
    -   Test model-centric routing (no backend specified).
    -   Test granular rate limiting (instance vs model).

- [ ] **5. Refactor Backend Factory** <!-- id: 4 -->
    -   Update `BackendFactory.ensure_backend`:
        -   Resolve connector from prefix.
        -   Pass `supported_input_types` to backend instance.
        -   Ensure config passed to backend is treated as immutable.

- [ ] **6. Implement Concurrency Control & Load Balancing** <!-- id: 5 -->
    -   Update `BackendService` to track instance usage.
    -   Implement non-blocking lock mechanism using `allow_concurrent_use`.
    -   **Instance Rotation**: Implement Round Robin load balancing in `BackendService`.
    -   **Global Model Routing**:
        -   Implement logic to build `model_name -> instances` map.
        -   Handle vendor prefixes (e.g., `google/`, `anthropic/`).
        -   Update `_resolve_backend_and_model` to support model-only requests.
    -   **Granular Rate Limiting**:
        -   Update `LLMBackend` to support `set_retry_after(seconds, model=None)`.
        -   Implement tracking of `instance_available_after` (global) and `model_available_after` (per-model).
        -   Update routing logic to skip unavailable instances/models.

- [ ] **7. Verify & Regression Testing** <!-- id: 6 -->
    -   Run full test suite to ensure no regressions.
    -   Verify integration with existing middleware.
