# Gap Analysis: OAuth Connectors Extraction (Refined)

## Current State Investigation

### Domain Assets
- **Discovery Mechanism**: `src/connectors/__init__.py` uses `pkgutil.iter_modules` for local auto-discovery. `src/core/services/backend_imports.py` triggers this during `src/core/cli.py` import.
- **Backend Registry**: `BackendRegistry` in `src/core/services/backend_registry.py`.
- **Connectors to Extract**: 13 backends identified (Anthropic OAuth, Gemini suite including Cloud Project, Codex, etc.).
- **DI Registrations**: `src/core/di/registrations/backend.py` and sub-modules for Codex and Gemini.

### Conventions
- **Early Discovery**: Discovery runs at module-import time in `cli.py`.
- **Unconditional Imports**: `backend.py` unconditionally imports and calls `register_codex_services`.

### Integration Surfaces
- **BackendValidationService**: Handles startup validation but lacks actionable installation advice.
- **Packaging**: `pyproject.toml` contains all dependencies as mandatory.

---

## Requirements Feasibility Analysis

### Technical Needs
- **Requirement 1.3 (Entry Points)**: Implement `importlib.metadata` scanning in `src/connectors/__init__.py`.
- **Requirement 2.3 (Plugin API)**: Ensure `LLMBackend` and `AppConfig` are easily accessible for external use.
- **Requirement 2.5 (No Unconditional Imports)**: Refactor `src/core/di/registrations/backend.py` to use lazy imports or conditional registration for extracted connectors.
- **Requirement 3.2 (Actionable Warnings)**: Enhance `BackendValidationService` to detect missing but configured OAuth backends and suggest `pip install llm-interactive-proxy[oauth]`.
- **Requirement 5.3 (Optional Deps)**: Move `google-auth`, `google-auth-oauthlib`, and `watchdog` to the `oauth` extra in `pyproject.toml`.

### Gaps and Constraints (Updated)
- **DI Coupling (Gap)**: Codex and Gemini coordinators are currently hard-wired into core DI registration. This violates the goal of total extraction and non-breaking startup without the plugin.
- **Dependency Bloat (Gap)**: Core `pyproject.toml` still lists OAuth-only dependencies as mandatory.
- **Discovery Timing (Constraint)**: The early discovery in `cli.py` is necessary for CLI help but happens before DI container is ready. External registration hooks must be handleable by the discovery logic.

---

## Implementation Approach Options

### Option A: Clean Cut Extraction (Recommended)
**Rationale**: Physically move 13 connectors and their dedicated DI logic to the new repo. Update core to support `entry_points` and optional DI hooks.

- **Changes**:
  - `src/connectors/__init__.py`: Add entry point discovery.
  - `src/core/di/registrations/backend.py`: Make Codex/Gemini registration conditional.
  - `src/core/services/backend_validation_service.py`: Add actionable warnings for OAuth backends.
  - `pyproject.toml`: Move deps to `oauth` extra.

---

## Implementation Complexity & Risk

- **Effort**: **M (4–6 days)**
  - Core refactoring for discovery and DI (2 days).
  - Package setup and physical file migration (2 days).
  - Test verification and CI setup (1-2 days).
- **Risk**: **Medium**
  - **Import failures**: Breaking core startup if conditional imports are done incorrectly.
  - **Test coverage**: Ensuring existing tests for OAuth connectors still pass in the new environment.

---

## Recommendations for Design Phase

1. **Discovery Service**: Create a dedicated service for scanning both local and external backends.
2. **DI Hook**: Define a standard hook (e.g., `register_backend_services`) that plugins can expose and core can call if present.
3. **Validation Hints**: Implement a list of "known extracted backends" in `BackendValidationService` to provide targeted installation advice.
4. **Research Items**:
   - [ ] Confirm if any core components (outside connectors) depend on `watchdog` or `google-auth`.
   - [ ] Determine the best way to handle `GeminiCloudProjectConnector` since it's used in GCP contexts but uses OAuth.
