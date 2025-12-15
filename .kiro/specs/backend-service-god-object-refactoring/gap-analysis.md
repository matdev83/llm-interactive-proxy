# Gap Analysis: BackendService God Object Refactoring

## Executive Summary

The largest gap between the current implementation and the desired architecture is concentrated in `BackendService.call_completion`, which is both large and highly complex (CC 180). Several supporting responsibilities already exist as dedicated services and are registered in DI, but orchestration remains monolithic and `BackendService.__init__` still contains runtime fallback instantiation.

**Recommended approach**: A hybrid decomposition that reuses existing extracted services, introduces a small number of new collaborators to isolate the remaining embedded responsibilities (completion orchestration, target resolution, failover planning, streaming session-id resolution), and preserves existing test seams via wrapper methods.

**Effort**: Large

**Risk**: Medium (behavior preservation + test seams)

## Current State Investigation

### Verified assets already in place

- Lifecycle management via `IBackendLifecycleManager`
- Failover policy via `IFailoverCoordinator` and optional `IFailoverStrategy`
- Failure handling policy via `IFailureHandlingStrategy`
- Streaming formatting via `IStreamFormattingService`
- Usage tracking wrapper via `IUsageTrackingWrapper`
- Model aliasing, planning phase management, reasoning config, URI parameters, exception normalization
- DI wiring in `src/core/di/services.py` already registers many of these services

### Remaining “God Object” hotspots

- `BackendService.call_completion` mixes orchestration for most of the above concerns.
- `BackendService.__init__` supports optional dependency injection and runtime fallback creation.
- Streaming session-id resolution is duplicated in two services with divergent logic.

## Requirements-to-Asset Mapping (High Level)

| Requirement | Primary Gap | Existing Asset | Needed Work |
|-------------|-------------|----------------|------------|
| 1.1-1.4 | Orchestration + metrics targets | Partial (services exist) | Extract completion orchestration and further decompose hotspots |
| 2.1-2.3 | Runtime fallback instantiation | Partial | Remove fallbacks, wire everything via DI |
| 3.1-3.4 | Test seam preservation | Present | Keep helper wrappers and preserve semantics |
| 6.1-6.2 | Target resolution isolation | Embedded in BackendService | Extract into dedicated resolver |
| 7.1-7.3 | Failover isolation | Partial | Extract plan selection/filtering, keep semantics for complex failover |
| 8.1-8.2 | Streaming session-id DRY | Duplicated | Centralize a shared algorithm and reuse |

## Implementation Options

### Option A: Minimal refactor (not recommended)

**Description**: Keep `call_completion` in BackendService and only clean up the constructor and a few helper methods.

**Pros**:
- Smaller change surface
- Lower short-term risk

**Cons**:
- Does not materially reduce the God Object problem or complexity metrics
- Fails key maintainability targets

### Option B: Move code only (not recommended)

**Description**: Move `call_completion` into another file/class without decomposing responsibilities further.

**Pros**:
- BackendService becomes smaller quickly

**Cons**:
- Creates a new God Object elsewhere (does not meet “no new hotspots” intent)
- Complexity remains dangerous (just relocated)

### Option C: Hybrid decomposition (recommended)

**Description**:
- Create a dedicated completion orchestration service and split critical sub-responsibilities into smaller services:
  - Target resolution
  - Failover plan selection/filtering
  - Streaming session-id resolution
- Reuse existing extracted services as dependencies of the orchestration flow.
- Keep BackendService as façade + wrapper methods used by tests.

**Why it fits this codebase**:
- Aligns with staged init + DI patterns already in place.
- Preserves existing tests (many touch helper methods directly).
- Allows incremental refactoring and verification without behavior drift.

## Primary Risks and Mitigations

1. **Behavior drift in complex orchestration**
   - Mitigation: characterization tests for resolution, failover, and streaming invariants; incremental extraction.

2. **Breaking test seams**
   - Mitigation: keep helper methods as delegating wrappers with stable semantics.

3. **Circular dependencies (failover recursion)**
   - Mitigation: completion orchestrator must not depend on `IBackendService`; implement internal invocation paths that preserve `allow_failover=False` semantics.
