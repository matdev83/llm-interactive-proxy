# Research & Design Decisions

---
**Purpose**: Capture discovery findings, architectural investigations, and rationale that inform the technical design.

**Project Context**: Universal LLM Proxy - FastAPI async, DI containers, staged initialization, adapter pattern.
---

## Summary
- **Feature**: `backend-completion-flow-architecture-refactoring`
- **Discovery Scope**: Extension / Refactor (Complex)
- **Key Findings**:
  - Backend completion orchestration is functionally correct (tests green), but structural issues remain: a very large orchestrator module, test shims leaking into production code, and transport-layer types in core service code.
  - The repo already has a clear pattern for decomposing a “god object” into an orchestrator + phase handlers (`.kiro/specs/request-processor-refactoring/design.md`) that preserves behavior while improving boundaries and testability.
  - The codebase already contains the correct place for HTTP/transport mapping (`src/core/transport/fastapi/exception_adapters.py`) and domain error handling (`src/core/common/exceptions.py`), so transport exceptions should not leak into orchestration.

## Research Log

### Existing Codebase Analysis
- **Components Reviewed**:
  - Backend orchestration: `src/core/services/backend_completion_flow.py`, `src/core/services/backend_service.py`
  - Transport error mapping: `src/core/transport/fastapi/exception_adapters.py`, `src/core/app/error_handlers.py`
  - DI wiring: `src/core/di/services.py`, `src/core/app/stages/backend.py`
  - Failure decisions: `src/core/interfaces/failure_strategy_interface.py`
- **Patterns Identified**:
  - Orchestrator + phase handlers is a preferred refactoring pattern in this repo (RequestProcessor refactor).
  - DI uses factories for complex services; service implementations generally depend on `src/core/interfaces/` seams.
  - Domain/service errors are expected to be `LLMProxyError` subclasses; transport is responsible for HTTP mapping.
- **Current Issues Observed (in the working tree)**:
  - `backend_completion_flow.py` imports `fastapi.HTTPException` and treats it as a first-class exception type in orchestration.
  - A “parent service” compatibility shim exists to preserve tests that mock private methods (`parent_service`).
  - Some seams are private-method reach-through (e.g., `BackendService` calling a private planner method), and temporary stub modules exist alongside real implementations.
- **Implications**:
  - The next refactor must focus on boundaries and compositional design, not moving code into a different monolithic module/class.
  - Removing transport dependencies from core requires normalizing “foreign” exceptions into domain errors without importing FastAPI/Starlette in core code.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| A. Split into modules only | Keep `BackendCompletionFlow` logic but move functions/classes into multiple files | Quickly meets line-count gate | Can become “same god object, multiple files” if boundaries aren’t real | Insufficient alone |
| B. Orchestrator + phase handlers (recommended) | Keep `BackendCompletionFlow` as coordinator; extract cohesive collaborators with explicit interfaces and DI wiring | Aligns with repo patterns; improves SRP/DIP/ISP; testable seams | Requires careful boundary design to avoid churn and circular deps | Best balance |
| C. Full clean-architecture rewrite | Introduce new application layer, new boundary abstractions, rewrite call chain | Maximal theoretical separation | High risk, high effort, likely behavior drift | Not justified for refactor-only scope |

## Design Decisions

### Decision: Use orchestrator + phase handlers
- **Context**: Requirement `2.1` and `2.2` require true decomposition without creating another god object/module.
- **Alternatives Considered**:
  1. Split the existing module by file only (Option A)
  2. Orchestrator + focused collaborators with explicit DI seams (Option B)
- **Selected Approach**: Option B.
- **Rationale**: This matches established project precedent (RequestProcessor refactor) and improves SRP/DIP/ISP without changing public contracts.
- **Trade-offs**: More DI wiring and more small interfaces; requires discipline to keep “phases” cohesive.
- **Follow-up**: Verify that module size gates can be satisfied without creating a “god package” where all logic remains in the orchestrator.

### Decision: Remove transport/framework exceptions from core orchestration
- **Context**: Requirement `1.1`/`1.2` requires core/service modules to avoid FastAPI/Starlette types, and to represent failures with domain errors.
- **Alternatives Considered**:
  1. Keep catching `HTTPException` directly in core code
  2. Normalize any “foreign” exception that carries HTTP-like status into a domain error using attribute-based inspection (no FastAPI imports)
- **Selected Approach**: Option 2.
- **Rationale**: Preserves semantics while enforcing dependency direction. Transport mapping already exists (`exception_adapters.py`).
- **Trade-offs**: Requires defining a stable normalization policy for “status_code-carrying” exceptions (e.g., 401 auth failures) without referencing FastAPI types directly.

### Decision: Replace “parent service” compatibility shim with explicit strategy injection in tests
- **Context**: Requirement `4.1`/`4.2` wants testability without production boundary leaks.
- **Alternatives Considered**:
  1. Keep `parent_service` shim and private-method mocking compatibility
  2. Update tests to inject `IFailureHandlingStrategy` (already a seam) or a new small interface specifically for failure recovery execution
- **Selected Approach**: Option 2 (prefer using existing `IFailureHandlingStrategy` seam).
- **Rationale**: Keeps production code clean and uses a stable, explicit contract instead of private method patching.
- **Trade-offs**: Requires touching tests and builder fixtures, but keeps behavior the same.

### Decision: Keep compatibility surface stable
- **Context**: Requirement `5.1` demands `IBackendService` contract stability and existing behavior preservation.
- **Selected Approach**:
  - Keep `IBackendCompletionFlow.call_completion` signature unchanged.
  - Keep `BackendService.call_completion` as a façade.
  - Introduce internal interfaces for extracted collaborators; do not expose new external/public API surface.

## Risks & Mitigations
- Risk: Behavioral drift in subtle streaming/failover/capture interactions - Mitigation: keep orchestration flow order stable and rely on the existing full suite + add a few characterization tests targeted at extracted seams.
- Risk: Over-abstraction and DI churn - Mitigation: limit to a small number of cohesive collaborators and align boundaries to existing method groupings.
- Risk: Circular dependencies between orchestrator and collaborators - Mitigation: collaborators must not depend on `IBackendCompletionFlow` or `IBackendService`; orchestrator owns coordination.

## Performance Considerations
- The refactor is structural; the design must preserve async behavior and avoid extra buffering/copying in streaming.
- Any new abstraction must remain allocation-light in the hot path (streaming chunk loop).

## References
- `.kiro/specs/request-processor-refactoring/design.md` - orchestrator + phase handler pattern in this repo
- `src/core/common/exceptions.py` - domain error hierarchy (`LLMProxyError`)
- `src/core/transport/fastapi/exception_adapters.py` - domain-to-HTTP mapping (transport layer)
- `src/core/di/services.py` and `src/core/app/stages/backend.py` - DI and staged init wiring patterns

