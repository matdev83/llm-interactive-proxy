# Research: OAuth Connectors Extraction

## Discovery Findings

### 1. Current Discovery Mechanism
The proxy currently uses `pkgutil.iter_modules` in `src/connectors/__init__.py` to import all modules in the `src/connectors` directory. Registration happens as a side effect of these imports via `backend_registry.register_backend`.

### 2. DI Registration Hotspots
Specific connectors (Gemini, Codex) have dedicated registration logic in `src/core/di/registrations/_backend/`.
- `gemini.py`: Registers `GeminiCredentialCoordinator`, `GeminiErrorMapper`, etc.
- `codex.py`: Registers `CredentialManager`, `SettingsLoader`, `ToolExecutionService`, and `CodexConnectorDependencies`.

These registrations are currently triggered in `src/core/di/registrations/backend.py`. For a modular architecture, the external package should provide its own registration logic that the core can invoke upon discovery.

Design constraint discovered during review: backend discovery currently runs very early (module import time via `src/core/cli.py` importing `src/core/services/backend_imports.py`). At that point, DI (`ServiceCollection`) and `AppConfig` are not available. This makes “plugin registers DI services during discovery” impractical as a primary mechanism.

### 3. Shared Utilities
Connectors depend on:
- `src/connectors/utils/`: `cline_auth.py`, `gemini_request_counter.py`, `model_capabilities.py`, etc.
- `src/connectors/mixins/`: `antigravity_auth_mixin.py`, `gemini_code_assist_mixin.py`, `usage_calculation_mixin.py`.

Extraction of these utilities is risky because some are used by core (non-extracted) connectors. Example: `UsageCalculationMixin` is imported by the core `gemini` connector.

### 4. Configuration Precedence
Backend configurations are dynamic in `BackendSettings`. Any attribute not matching a pre-defined field is treated as a `BackendConfig`. This naturally supports external backends as long as they are registered in the `BackendRegistry`.

### 5. Validation Logic
`BackendValidationService` currently filters "configured" backends against "registered" backends. If a backend is configured (e.g., has an `api_key` or is `default_backend`) but not registered, it should trigger a specific warning suggesting the installation of the OAuth package.

## Architecture Decisions

### D1: Entry Point Selection
We will use the group name `llm_proxy_backends`. The entry point will point to a factory or the backend class itself.

### D2: Optional DI Dependencies
Core DI registration must not hard-import extracted connector modules. Connector-specific DI helpers (e.g., Codex components) should be guarded/optional, and extracted connectors should remain functional without requiring core-side DI wiring.

### D3: Core Package as Dependency
The external package will depend on `llm-interactive-proxy` to access `LLMBackend`, `BackendRegistry`, and common interfaces.

### D4: Extraction Scope Reality Check
`gemini-cli-cloud-project` is an OAuth-based backend in core and depends on `google-auth` and `watchdog`. To meet the “optional plugin” separation goal, it must be part of the extracted set (otherwise core will retain OAuth-only dependencies).

## Research Needed (Carry Forward)
- [ ] Test `importlib.metadata.entry_points(group="...")` compatibility with Python 3.10 and 3.11.
- [ ] Verify if `pyproject.toml` `optional-dependencies` can depend on a package that is not yet published (for local testing).
