# Research Summary: AppConfig God Object Refactoring

## Summary
- **Feature**: `app-config-god-object-refactoring`
- **Discovery Scope**: Extension / Complex refactor (brownfield)
- **Key Findings**:
  - `src/core/config/app_config.py` is ~2895 LOC and mixes domain models with YAML/env I/O and backend instance discovery.
  - `BackendSettings` currently performs environment reads and filesystem scanning during model initialization, creating test-hostile side effects.
  - Consumers and tests import `AppConfig`, `BackendConfig`, `BackendSettings`, and other nested config types directly from `src.core.config.app_config`, so compatibility requires a facade strategy.

## Existing Codebase Analysis

### Current Configuration Entry Points
- `src/core/config/app_config.py`
  - `AppConfig` (Pydantic/DomainModel)
  - `AppConfig.from_env(...)` (large env mapping logic)
  - `load_config(...)` (YAML load, schema+semantic validation, merge, env overlay)
  - `BackendSettings` (dynamic backend storage + backend instance discovery via env and per-instance YAML files)
- `src/core/config/yaml_validation.py` provides reusable YAML schema validation utilities and raises `ConfigurationError`.
- `src/core/config/semantic_validation.py` provides semantic validation and raises `ConfigurationError`.
- `src/core/config/parameter_resolution.py` tracks origins and handles redaction in logs.

### Coupling Hotspots (Why the module became a “God Object”)
- Global reads:
  - `BackendSettings` reads `os.environ` directly
  - Schema path is derived from `Path.cwd()`
- Backend registry dependency:
  - Backend instance discovery depends on `backend_registry.get_registered_backends()`
- Dynamic behaviors:
  - Backend configs stored via `__dict__` keys (including dotted names like `openai.1`)
  - Custom serializer injects dynamic entries
  - Consumers (e.g., `BackendConfigProvider`) resort to `getattr`, dict access, and direct `__dict__` inspection

### Test Signals
- Tests currently patch:
  - `BACKEND_INSTANCES_DIR` and environment variables
  - `src.core.config.app_config.backend_registry`
- Several tests assume `BackendSettings()` triggers discovery side effects today; this is a refactor target (to remove side effects), so tests will need to pivot to exercising a discovery source/loader explicitly.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| A. Facade + Pipeline (Selected) | Keep `app_config.py` as facade; implement loader + sources + merger + validators | Preserves import stability; strong seams; aligns with DI/staged-init | Requires careful compatibility work and incremental migration | Best match for constraints and testability |
| B. Split by “just moving” to one new module | Move most logic to `config_loader.py`-like module | Quick | Violates “no new god module” constraint | Explicitly disallowed |
| C. Keep side-effectful models | Keep `BackendSettings` discovery in model init | Minimal change | Continues test-hostile globals/I/O; undermines layering | Conflicts with requirements 2.x and 9.x |
| D. Convert backends to pure dict everywhere | Replace dynamic backend model with dicts only | Simplifies some access | Large breaking surface; many consumers expect typed `BackendConfig` | Not compatible for near-term |

## Design Decisions (Rationale)

### Decision: Keep `src/core/config/app_config.py` as a Facade
- **Context**: Many imports from this module across `src/` and `tests/`.
- **Selected Approach**: `app_config.py` becomes thin: re-exports models/functions and delegates to new modules.
- **Trade-offs**: Slight indirection, but reduces breaking changes and enables incremental extraction.

### Decision: Make Domain Models Pure (No I/O)
- **Context**: Side effects on `AppConfig()` or `BackendSettings()` construction harm determinism and testability.
- **Selected Approach**: All env and filesystem reads occur only in sources/adapters; models are created from data.
- **Trade-offs**: Some legacy tests and behaviors that relied on implicit discovery must be rewritten to call the loader.

### Decision: Represent Backend Instance Discovery as a Source
- **Context**: Current discovery is intertwined with storage (`__dict__`) and registry access.
- **Selected Approach**: A dedicated `BackendInstanceSource` loads env-based instances and per-instance YAML configs with explicit precedence and validation.
- **Trade-offs**: Requires new boundary definitions but enables unit testing without mutating global environment.

### Decision: Stabilize Backend Lookup via Provider/Adapter
- **Context**: `BackendConfigProvider` currently uses multiple fallback access methods to accommodate dynamic behavior.
- **Selected Approach**: Introduce a typed lookup API on `BackendSettings` as the preferred contract; keep backward-compatible behavior via adapter while migrating callers.
- **Trade-offs**: Temporary duplication while consumers move to the new API.

## Risks & Mitigations

- **Risk**: Breaking subtle precedence semantics, especially backend instances.
  - **Mitigation**: Document domain-specific backend instance merge rules; add focused unit tests.
- **Risk**: Increased number of modules leads to “config sprawl”.
  - **Mitigation**: Enforce cohesive grouping by domain (models/sources/validation/merge/loading) and keep modules small and single-purpose.
- **Risk**: Import cycles while splitting models.
  - **Mitigation**: Keep models in `src/core/config/models/` and avoid importing loader/adapters from models; facade handles re-exports.

## References
- `src/core/config/app_config.py` (current state; refactor target)
- `src/core/config/parameter_resolution.py` (source tracking + redaction)
- `src/core/config/yaml_validation.py` (schema validation utilities)
- `src/core/config/semantic_validation.py` (semantic validation utilities)
- `src/core/services/backend_registry.py` (backend registry)
- `.kiro/steering/structure.md` and `.kiro/steering/tech.md` (staged init + DI conventions)

