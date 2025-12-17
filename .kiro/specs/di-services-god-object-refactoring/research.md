# Research & Design Decisions

---
**Purpose**: Capture discovery findings, architectural investigations, and rationale that inform the technical design.

**Project Context**: Universal LLM Proxy - FastAPI async, DI containers, staged initialization, adapter pattern.
---

## Summary
- **Feature**: `di-services-god-object-refactoring`
- **Discovery Scope**: Extension (brownfield refactor)
- **Key Findings**:
  - `src/core/di/services.py` centralizes global DI access, post-build initialization, self-healing, and most registrations (~3905 LOC), making it a God-Object hotspot.
  - Staged initialization relies on `register_core_services(...)` and some stages import private helpers from `src/core/di/services.py`, creating tight coupling that must be redesigned without breaking startup.
  - The repo already contains a complexity/LOC validator (`scripts/analyze_complexity.py`) that enforces `<600 LOC` and `<50` max function CC for other refactor scopes and can be extended for DI.

## Research Log

### Existing Codebase Analysis
- **Components Reviewed**:
  - `src/core/di/services.py` - bulk registrations, global provider access, parity/self-healing logic
  - `src/core/di/container.py` - `ServiceCollection` / `ServiceProvider` behavior, lifetimes, current diagnostics behavior
  - `src/core/app/stages/core_services.py` - stage bootstrapping and `register_core_services(...)` integration
  - `src/core/app/stages/backend.py` - early validation paths and imports of DI helpers
  - Tests guarding DI wiring: `tests/unit/core/di/test_service_registration.py`, `tests/integration/test_di_container_integrity.py`, `tests/regression/test_backend_service_di_regression.py`
- **Patterns Identified**:
  - Registration functions use local imports to reduce circular imports.
  - Many feature registrations are configuration-gated inside `register_core_services(...)`.
  - The codebase tolerates some global accessors for compatibility (`get_service_provider` et al).
- **Implications**:
  - The refactor should keep a stable compatibility facade while moving registrations into smaller feature-scoped modules.
  - DI coupling inside stages is an integration hotspot and must be handled explicitly (either by re-exporting stable helpers or relocating helpers to dedicated modules).

### Quality Gate Enforcement (LOC + CC)
- **Context**: Requirements require `<600 LOC` and `<50 CC` per DI module, and use Ruff `C901` (mccabe).
- **Sources Consulted**:
  - `scripts/analyze_complexity.py` (existing enforcement script)
  - `pyproject.toml` Ruff configuration (current rule selection does not include mccabe `C90*` by default)
- **Findings**:
  - Ruff can report `C901` but the threshold is configuration-driven; enforcement should be done via `pyproject.toml` rather than CLI flags.
  - `scripts/analyze_complexity.py` already encodes the exact thresholds and scope-based validation patterns used in other refactors.
- **Implications**:
  - Primary enforcement for this refactor will use `scripts/analyze_complexity.py` by adding a DI refactor scope and validation mode to make LOC/CC gates measurable.

### Requirements ID Canonicalization
- **Context**: Design rules require `N.M`-style numeric IDs for traceability (e.g., `2.1`).
- **Finding**: The acceptance criteria were originally numbered per-section (`1.`, `2.`, ...) without `N.M` IDs.
- **Implication**: The acceptance criteria numbering was normalized to `N.M` while preserving the exact text semantics to enable consistent design/task traceability.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| A: Extract feature registrars behind facade | Keep `src/core/di/services.py` as stable API and delegate to feature modules | Minimal import-path churn, incremental rollout, test-friendly | Requires careful boundary carving to avoid cycles | Recommended baseline |
| B: New composition root + migrate call sites | Introduce new DI root module and update stages/callers | Cleaner long-term ownership | Larger change surface, higher regression risk | Consider later |
| C: Hybrid phased approach | A first (God-Object split), then B-like cleanup of stage/legacy duplication | Best risk control | More planning, two-step rollout | Recommended overall plan |

## Design Decisions

### Decision: Keep a Compatibility Facade for DI Entry Points
- **Context**: Multiple modules import symbols from `src/core/di/services.py` directly.
- **Alternatives Considered**:
  1. Move all public APIs to a new module and update imports everywhere
  2. Keep `src/core/di/services.py` as a facade and delegate internally
- **Selected Approach**: Keep `src/core/di/services.py` as the facade for public entry points while moving registrations and helper logic into smaller modules.
- **Rationale**: Minimizes breakage risk and supports incremental extraction.
- **Trade-offs**: Some legacy/global patterns remain temporarily; requires discipline to keep the facade thin.
- **Follow-up**: After extraction, evaluate migrating stages to import from dedicated helper modules (reducing “private helper” coupling).

### Decision: Remove DI “Self-Healing” Provider Rebuilds
- **Context**: `src/core/di/services.py` currently rebuilds the global provider in `get_service_provider()` when selected components are missing (technical debt).
- **Alternatives Considered**:
  1. Preserve self-healing for compatibility
  2. Remove self-healing and enforce correctness via staged init + tests + diagnostics
- **Selected Approach**: Remove self-healing behavior. `get_service_provider()` returns the built provider as-is; missing registrations are treated as errors.
- **Rationale**: Self-healing hides wiring defects, introduces non-determinism, and undermines confidence in staged init.
- **Trade-offs**: Some tests and edge startup paths may require explicit wiring fixes rather than relying on late repair.
- **Follow-up**: Ensure DI integrity tests cover the previously “repaired” services and add diagnostics coverage for actionable errors.

### Decision: Feature-Scoped Registration Modules
- **Context**: `register_core_services(...)` currently spans many unrelated feature areas.
- **Selected Approach**: Introduce feature-scoped registrar modules under `src/core/di/registrations/` and have the facade call them in a defined order.
- **Rationale**: Enforces SRP/SoC, improves discoverability, reduces CC/LOC, supports parallel implementation.
- **Trade-offs**: More files; requires explicit ordering to preserve staged init semantics.

### Decision: Deterministic DI Resolution Diagnostics
- **Context**: Requirement 1.3 requires errors to include missing service + resolution path.
- **Selected Approach**: Add an optional resolution-tracing mechanism in the DI container that records the active dependency chain and includes it in `ServiceResolutionError` when enabled.
- **Rationale**: Provides actionable failure diagnostics without changing default behavior for production performance.
- **Trade-offs**: Additional complexity in the DI container; must be carefully scoped and gated behind a diagnostics flag.

### Decision: Align Legacy Registration Paths to a Single Source of Truth
- **Context**: `ServiceCollection.register_app_services(...)` and staged init both register overlapping services.
- **Selected Approach**: Refactor legacy paths to call the same feature registrars to prevent drift.
- **Rationale**: Ensures one definition of DI wiring and reduces regressions.
- **Trade-offs**: Requires careful sequencing and test updates.

## Risks & Mitigations
- Risk: Circular imports introduced by registrar extraction - Mitigation: keep local imports inside registrar functions and define strict dependency direction between registrar modules.
- Risk: Startup ordering regressions - Mitigation: preserve existing registration order as a documented contract and validate with existing integration/regression tests.
- Risk: Optional feature gating changes behavior - Mitigation: keep existing config gating conditions initially; migrate to cleaner gating only after tests confirm parity.

## References
- `src/core/di/services.py` (current composition root)
- `src/core/di/container.py` (container behavior, lifetimes)
- `src/core/app/stages/` (staged initialization order)
- `scripts/analyze_complexity.py` (LOC/CC validation scaffolding)
