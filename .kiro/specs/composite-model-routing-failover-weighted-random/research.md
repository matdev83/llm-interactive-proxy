# Research & Design Decisions

## Summary
- **Feature**: `composite-model-routing-failover-weighted-random`
- **Discovery Scope**: Full discovery for a complex brownfield routing change.
- **Key Findings**:
  - The routing spine is already unified for main and auxiliary flows through `BackendModelResolver` and `BackendRequestPreparer`, but it only supports single-target outcomes today.
  - Retry/failover safety already exists in `DefaultFailureHandlingStrategy` + `FailureRecoveryExecutor`; composite routing must share that budget instead of creating nested retry loops.
  - Quality Verifier already routes through `IBackendService`, and random replacement still mutates effective routing state, so migration and observability must be designed up front.

## Research Log

### Existing Codebase Analysis
- **Reviewed components**:
  - `src/core/domain/model_utils.py`
  - `src/core/services/backend_model_resolver.py`
  - `src/core/services/backend_routing_service.py`
  - `src/core/services/backend_completion_flow/backend_request_preparer.py`
  - `src/core/services/backend_completion_flow/failure_recovery_executor.py`
  - `src/core/services/failure_handling_strategy.py`
  - `src/core/services/request_processor_service.py`
  - `src/core/services/model_replacement_service.py`
  - `src/core/services/quality_verifier_orchestrator.py`
- **Observed patterns**:
  - Selector semantics are explicit: backend selection uses `:` only (before `/`), and URI parameters are parsed from `?`.
  - `BackendModelResolver` is the core resolution boundary; `BackendRoutingService` performs backend-instance/model-only selection.
  - Auxiliary rerouting already re-enters shared resolution, which matches the desired "one entry point" direction.
  - Runtime failover is governed by hop/time budgets and "content started" protection.

### Brownfield Constraints
- **Main flow**: `resolve_target(...)` returns one `BackendTarget` and assumes leaf selectors only.
- **Auxiliary flow**: already executes a second pass with shared resolver and context metadata.
- **Quality Verifier flow**: `quality_verifier_model` is string-configured and executed via `backend_service.chat_completions(...)`.
- **Replacement flow**: replacement rules are probabilistic and session-scoped, with no composite grammar or deprecation bridge contract.

### External Research Notes
- Python `random` docs confirm weighted selection is relative-weight based and practical via an injectable RNG boundary.
- Python typing/style guidance reinforces explicit typed contracts and avoidance of hidden mutable global state.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Decision |
|--------|-------------|-----------|---------------------|----------|
| Extend existing services in place | Put parsing + composite execution directly in current resolver/routing services | Minimal caller changes | Hot-path bloat, weak separation, retry-coupling risk | Rejected |
| Dedicated composite subsystem | New parser/planner/coordinator + diagnostics boundary above current services | Clean boundaries, better tests, safer migration | More DI wiring | Viable |
| Hybrid layered composition | Add composite parser/coordinator/budget layer while reusing current leaf resolution | Best brownfield balance, preserves compatibility | Transitional complexity | **Selected** |

## Design Decisions

### 1) Hybrid layered composite routing
- **Selected**: dedicated composite parser + coordinator + attempt context above current resolver/routing leaf services.
- **Why**: preserves stable legacy behavior and isolates new grammar/policy logic.

### 2) Legacy selector semantics remain canonical at leaf level
- **Selected**: preserve existing `backend:model`, backend-instance, model-only, vendor/model, and URI parameter behavior for each composite leaf.
- **Why**: direct coverage of backward compatibility requirements.

### 3) One shared attempt budget across composite and existing failover
- **Selected**: composite branch progression uses one request-scoped budget integrated with existing failover-hop and timeout controls.
- **Why**: prevents retry explosion and aligns with existing runtime safety behavior.

### 4) Weighted random is single-branch selection
- **Selected**: choose exactly one branch for each weighted node.
- **Why**: satisfies weighted-routing requirements while avoiding hidden fan-out retries.

### 5) Deprecation bridge for random replacement
- **Selected**: keep legacy replacement during deprecation window via explicit compatibility mapping to composite behavior; reject unsafe mappings with explicit migration errors.
- **Why**: avoids silent behavior drift and supports N+1 removal timeline.

### 6) Mixed operators forbidden in v1
- **Selected**: reject selectors that mix `|` and `^` in a single string; expand to defined precedence in a future version if needed.
- **Why**: avoids grammar/debugging complexity and parser-collision risk with URI-style parameters; aligns with the original risk-mitigation agreement from planning discussion.

### 7) Weight annotation is prefix-only
- **Selected**: `[weight=N]` must appear immediately before the target selector (e.g., `[weight=2]backend:model`).
- **Why**: prevents ambiguity with URI-style query parameters that follow the selector and matches the original user examples.

## Risks and Mitigations
- **Grammar regressions**: constrain composite parsing to explicit operators, forbid mixed operators, and keep current leaf parser contract unchanged.
- **Retry multiplication**: enforce a single shared attempt context and reuse existing "no failover after meaningful output" guard.
- **Non-deterministic tests**: inject RNG/selector abstraction for weighted selection.
- **Migration ambiguity**: publish structured deprecation metadata and explicit mapping failures.
- **Shell-sensitive operators**: `|` and `^` require escaping in PowerShell, CMD, and bash; operator documentation and CLI help should include shell-safe quoting examples to prevent user confusion.

## Testing Focus for Implementation
- Parser determinism, mixed-operator rejection, weight-prefix parsing, invalid-weight validation.
- Weighted branch selection with deterministic injected RNG.
- Composite failover budget exhaustion and runtime-failure progression.
- End-to-end coverage for main, auxiliary, and quality-verifier routing surfaces.
- Replacement compatibility bridge translation and rejection paths.

## References
- Python docs: `random` module weighted-selection guidance.
- Project source files listed in Existing Codebase Analysis.
