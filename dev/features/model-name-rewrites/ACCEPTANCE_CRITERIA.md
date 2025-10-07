# Acceptance Criteria & Deliverables: Model Name Rewrites

This document defines the conditions that must be met for the "Model Name Rewrites" feature to be considered complete and ready for release.

## 1. Acceptance Criteria

### 1.1. Configuration

- **AC1**: The proxy MUST start without errors when a valid `model_aliases` list is present in `config.yaml`.
- **AC2**: The proxy MUST fail to start with a clear error message if a rule in `model_aliases` contains an invalid regular expression in its `pattern`.
- **AC3**: The proxy MUST start and operate normally if the `model_aliases` key is absent from the configuration.

### 1.2. Rewrite Logic

- **AC4**: Given a request with a model name that exactly matches a `pattern` for a static replacement, the model name MUST be rewritten to the corresponding `replacement` value.
- **AC5**: Given a request with a model name that matches a regex `pattern` with capture groups, the model name MUST be rewritten using the `replacement` string with the captured values correctly substituted.
- **AC6**: Given multiple rules in `model_aliases`, if a model name matches more than one `pattern`, only the **first** matching rule in the list MUST be applied.
- **AC7**: Given a request with a model name that does not match any `pattern` in `model_aliases`, the model name MUST remain unchanged.

### 1.3. Integration with Other Features

- **AC8**: If the `--static-route` CLI parameter is set, it MUST take precedence over any `model_aliases` rules. The model alias logic should not be executed.
- **AC9**: If a model name is rewritten by an alias, the `planning_phase` logic MUST operate on the *new, rewritten* model name. If the session is in the planning phase, the rewritten model name should be subsequently overridden by the `strong_model`.

## 2. Deliverables

The following artifacts must be completed and delivered for this feature to be considered finished:

1. **Configuration Models**:
    - `ModelAliasRule` and the corresponding field in `AppConfig` implemented in [`src/core/config/app_config.py`](src/core/config/app_config.py).

2. **Core Implementation**:
    - The model rewriting logic implemented within `src/core/services/backend_service.py` as described in the architecture document.

3. **Unit Tests**:
    - A new test file (e.g., `tests/unit/core/services/test_model_name_rewrites.py`) that provides comprehensive coverage for all acceptance criteria listed above.

4. **Configuration Example**:
    - The `config/config.example.yaml` file MUST be updated to include a commented-out example of the `model_aliases` configuration, demonstrating both static and regex-based rules.

5. **Documentation**:
    - Updates to the project's documentation (e.g., in the `docs/` directory or `README.md`) explaining what the feature is, why it's useful, and how to configure it, with clear examples.
