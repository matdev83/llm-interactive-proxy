# Gap Analysis: `di-services-god-object-refactoring`

## Status Note (Approvals)
`spec.json` indicates requirements are approved (`approvals.requirements.approved: true`). This gap analysis is accepted and is intended to inform the design phase.

## 1. Current State Investigation

### Key assets and layout
- DI container implementation: `src/core/di/container.py` (`ServiceCollection`, `ServiceProvider`, lifetimes)
- Bulk DI registrations + global accessors: `src/core/di/services.py`
- Staged startup wiring (source of truth): `src/core/app/stages/`
  - `src/core/app/stages/core_services.py` calls `register_core_services(...)`
  - `src/core/app/stages/backend.py` contains logic that explicitly references DI factories and imports `_resolve_failure_strategy` from `src/core/di/services.py`

### What `src/core/di/services.py` currently does
`src/core/di/services.py` currently combines multiple responsibilities:
- Global DI state and service-locator style access (`get_service_collection`, `get_or_build_service_provider`, `get_service_provider`, `set_service_provider`)
- Feature parity initialization (post-provider build) (`_initialize_feature_parity_registry`)
- “Self-healing” DI behavior that rebuilds the provider when certain services are missing (`_ensure_tool_call_reactor_services`)
- Service registration composition root (`register_core_services`) spanning many feature areas (commands, streaming pipeline, memory/persistence, backends, safety, resilience, etc.)
- A helper that is imported by another module despite being “private” (`_resolve_failure_strategy` is imported from `src/core/app/stages/backend.py`)

### Size/complexity signals
- File size: `src/core/di/services.py` is ~3905 LOC.
- Cyclomatic complexity (Ruff `C901`, default threshold 10):
  - `register_core_services`: 275
  - `_tool_call_reactor_factory` (nested in `register_core_services`): 43
  - `_initialize_feature_parity_registry`: 12
  - `_ensure_tool_call_reactor_services`: 12

### Existing conventions/patterns relevant to this refactor
- Interfaces live under `src/core/interfaces/` and are used for DI seams (`I*` naming).
- Many DI factories use local imports to avoid circular import problems.
- Some behaviors rely on import side-effects (example: command handler discovery via importing modules; connector auto-registration via importing `src.connectors`).
- There is active test coverage guarding critical DI wiring:
  - `tests/unit/core/di/test_service_registration.py`
  - `tests/integration/test_di_container_integrity.py`
  - `tests/regression/test_backend_service_di_regression.py`
  - DI violation scanner tests in `tests/unit/test_di_container_usage.py`

## 2. Requirements Feasibility Analysis (What the requirements imply)

From the requirements, the refactor needs:
- A modular DI “composition root” with clear feature-area boundaries and discoverability.
- Stable behavior: same effective implementations/lifetimes when resolving services.
- Reduced module/file complexity and size (≤600 LOC per DI registration module; CC ≤50).
- Import discipline: avoid new circular imports; avoid import-time side effects beyond defining registrations.
- Optionality discipline: disabled features should not force imports/instantiation just to boot core proxy.

Key constraints from the existing architecture:
- Staged initialization remains the startup “truth”; DI registrations must align with stage ordering and existing late-binding patterns.
- Some call sites expect global access to a provider (`get_service_provider`) and will break if the symbol moves without a compatibility layer.
- Backend-related wiring currently has early-startup validation paths that intentionally run before all stages are executed (see `src/core/app/stages/backend.py`); DI refactor must preserve this behavior or provide a compatible replacement.

## 3. Requirement-to-Asset Map (with gaps)

### Requirement 1: Behavioral Compatibility and Startup Integrity
- Existing assets:
  - `src/core/app/stages/*` staged startup
  - `src/core/di/services.py:register_core_services`
  - Tests: `tests/integration/test_di_container_integrity.py`, `tests/regression/test_backend_service_di_regression.py`
- Gap status:
  - **Constraint**: `src/core/app/stages/backend.py` depends on details from `src/core/di/services.py` (private helper import + “replicating logic” comments).
  - **Unknown**: Whether all current registration call-sites resolve exactly the same lifetime semantics across both staged init and global provider paths (requires design-time inventory and validation plan).

### Requirement 2: Modular DI Registration (God-Object Elimination)
- Existing assets:
  - Partial modularization exists in stages, but `register_core_services` remains monolithic.
- Gap status:
  - **Missing**: DI registrations are concentrated in a single ~3905 LOC file.
  - **Missing**: No dedicated, feature-scoped “entry points” for registrations; discoverability is low.
  - **Constraint**: Some modules import global provider functions (service-locator pattern); refactor must preserve compatibility or migrate carefully.

### Requirement 3: Separation of Concerns and Layering
- Existing assets:
  - Interfaces (`src/core/interfaces/`) widely used; many interface-to-implementation registrations exist.
  - Local-import factory pattern reduces circular import risk.
- Gap status:
  - **Constraint**: Current DI module also performs post-build initialization and “self-healing” behaviors, which mixes concerns beyond pure registration.
  - **Unknown**: Optional feature import behavior: `src/core/di/services.py` imports many feature modules at module import time; whether this violates “disabled feature should not require import” depends on how strict we interpret the requirement and what “disabled” means in practice.

### Requirement 4: Code Size and Complexity Limits
- Existing assets:
  - Ruff is present; `C901` can be run explicitly (`ruff check --select C901`).
- Gap status:
  - **Missing**: `register_core_services` complexity is 275 and cannot meet a 50 threshold without decomposition.
  - **Missing**: No current Ruff config enabling `C901` or setting a max complexity of 50 in `pyproject.toml`.
  - **Unknown**: Tooling choice for LOC enforcement; `radon` failed to run in this repo environment due to `pyproject.toml` parsing issues (investigate alternatives or configuration).

## 4. Implementation Approach Options

### Option A: Extend existing `src/core/di/services.py` by extracting registration modules (recommended baseline)
**Idea**: Keep `src/core/di/services.py` as the stable public API surface, but move the bulk of registrations into new feature-scoped modules, then have `register_core_services(...)` delegate to them.

- Likely changes:
  - New modules such as `src/core/di/registrations/commands.py`, `.../streaming.py`, `.../memory.py`, `.../backend.py`, `.../safety.py`, `.../resilience.py` (names to be decided in design).
  - `register_core_services` becomes a thin orchestrator (and stays idempotent).
  - Keep `get_service_provider` / global-provider functions in place (or move to a dedicated module with re-exports).
- Compatibility assessment:
  - ✅ Minimizes import-path churn for existing call sites.
  - ✅ Allows incremental extraction and test-driven safety.
  - ❌ Requires careful boundary carving to avoid circular imports.
  - ❌ Preserving current “self-healing” behavior may keep some complexity unless that logic is also extracted/isolated.

### Option B: Create a new DI “composition root” component and migrate call sites
**Idea**: Introduce a new central registration API (for example, `src/core/di/registration_root.py`) and make stages call it; keep `src/core/di/services.py` only as a compatibility shim.

- Likely changes:
  - New composition root module with feature registrars.
  - Stages updated to call the new composition root directly, reducing duplication and “replicated DI factory” code in stages.
- Compatibility assessment:
  - ✅ Cleaner architecture over time; stages become the true owners of what’s registered.
  - ✅ Enables removing private-import couplings like `_resolve_failure_strategy`.
  - ❌ Higher risk and broader change surface (more call sites; more opportunities for subtle behavior changes).

### Option C: Hybrid, phased extraction + staged-init alignment cleanup
**Idea**: First do Option A to split the God-Object safely, then in a second phase reduce duplication and tighten staged-init boundaries (for example, eliminate stage code that “replicates DI logic” by reusing extracted registrars).

- Compatibility assessment:
  - ✅ Best risk control for a brownfield refactor.
  - ✅ Allows measurable milestones: LOC/CC reduction first, then architectural cleanup.
  - ❌ Requires disciplined sequencing and agreement on migration strategy.

## 5. Effort & Risk
- **Effort**: **L (1–2 weeks)** — the file spans many subsystems and is referenced by stages, tests, and runtime “global provider” access paths.
- **Risk**: **Medium** — strong test coverage exists for several DI chains, but subtle lifetime/ordering differences and import cycles are plausible during extraction.

## 6. Research Needed (for design phase)
- How to enforce “CC ≤ 50” with Ruff in this repo:
  - Ruff `C901` is not currently enabled in `pyproject.toml`; determine the preferred project-level configuration approach (likely via `[tool.ruff.lint.mccabe]`).
  - Note: Ruff CLI does not accept flake8-style `--max-complexity`; the threshold is configuration-driven.
- How to enforce “≤ 600 LOC per file”:
  - Decide whether to use `xenon`, a lightweight script, or CI checks; `radon cc` currently fails in this repo due to `pyproject.toml` parsing/interpolation issues.
- Confirm which DI path is authoritative:
  - Staged init vs `ServiceCollection.register_app_services` vs global provider in `src/core/di/services.py`.
- Inventory of optional features + import behavior:
  - Identify which registrations/features must remain import-light when disabled (and what “disabled” means: config flag, env var, or stage omission).

## 7. Recommendations to Carry into Design
- Preserve `src/core/di/services.py` as the public API surface initially to avoid breaking import paths, but move registrations into feature-scoped registrars (Option A / Option C).
- Treat `src/core/app/stages/backend.py` imports of private DI helpers and “replicated factory logic” as a high-priority integration hotspot to address explicitly in the design.
- Define a validation strategy in design that uses existing DI integrity/regression tests as gates, plus a targeted “service descriptor/lifetime snapshot” approach for high-risk services.
