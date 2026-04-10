# Gap Analysis: composite-model-routing-failover-weighted-random

## Analysis Summary

- Requirements are not yet approved in `spec.json`, but gap analysis can still use them to shape the design phase.
- The codebase already has a strong shared routing spine for main requests and auxiliary reroutes through `BackendModelResolver` and `BackendRequestPreparer`, plus quality-verifier calls already flow through `IBackendService`.
- The largest gaps are not basic routing primitives; they are a missing composite-selector grammar/parser, a missing shared composite-routing decision object, bounded nested failover accounting across retry layers, and a migration bridge from random model replacement.
- Existing failover and retry mechanisms are spread across legacy config-driven failover, failure strategy retries, and quality-verifier/replacement flags, so the main design challenge is unifying behavior without duplicating or multiplying attempts.
- Most viable direction for design is a hybrid approach: add a dedicated composite-routing layer and context/diagnostics model, while reusing current resolver, routing, availability, and execution collaborators underneath.

## Document Status

- Analysis approach: loaded spec + requirements + all steering files + `gap-analysis.md`, then inspected current routing, failover, auxiliary, quality-verifier, and replacement code paths.
- Status warning: requirements are generated but not approved yet in `spec.json`.

## Current State Investigation

### Key assets already in place

- Shared request target resolution already exists in `src/core/services/backend_model_resolver.py`; it preserves alias resolution, `backend:model`, model-only routing, URI params, and static-route handling.
- Auxiliary routing already re-enters the shared resolver path in `src/core/services/backend_completion_flow/backend_request_preparer.py`, especially the auxiliary reroute flow.
- Backend instance/model-only routing and availability-aware candidate filtering already exist in `src/core/services/backend_routing_service.py`, with model-only discovery and ranking built in.
- Execution-time availability checks already classify unsupported / unavailable / rate-limited states in `src/core/services/backend_completion_flow/availability_checker.py`.
- Retry/failover bookkeeping already exists via `retry_attempt` context metadata in `src/core/services/backend_completion_flow/service.py` and `src/core/services/backend_completion_flow/failure_recovery_executor.py`.
- Quality Verifier is already routed as an internal backend call through `IBackendService` in `src/core/services/quality_verifier_orchestrator.py`.
- Random model replacement already mutates request routing state and marks context flags in `src/core/services/request_processor_service.py` and is implemented in `src/core/services/model_replacement_service.py`.

### Existing conventions and constraints

- Current selector parsing is intentionally conservative: explicit backend is only `:` before `/`, and URI params are parsed after `?`, in `src/core/domain/model_utils.py`.
- Backend routing today expects a single resolved backend/model pair, not a composite parse tree, in `src/core/services/backend_model_resolver.py`.
- Legacy failover config is model-keyed config data, not inline selector grammar, in `src/core/services/failover_service.py`.
- Failure handling already has its own retry/failover loop, which means composite failover must avoid stacking independent attempt budgets, in `src/core/services/backend_completion_flow/failure_recovery_executor.py`.

## Requirements Feasibility Analysis

### Requirement-to-Asset Map

| Requirement Area | Existing Assets | Status | Gap Notes |
|---|---|---:|---|
| R1 Unified composite routing entry point | `src/core/services/backend_model_resolver.py`, `src/core/services/backend_completion_flow/backend_request_preparer.py`, `src/core/services/quality_verifier_orchestrator.py` | Constraint | Main and auxiliary paths are close to unified already; quality verifier uses shared backend service but not the resolver directly as a first-class composite-routing entry point. |
| R2 Ordered failover `|` selectors | `src/core/services/failover_service.py`, `src/core/services/backend_completion_flow/failure_recovery_executor.py` | Missing | Existing failover is config-driven or error-driven, not selector-driven; no inline ordered composite selector support. |
| R3 Weighted random `^` selectors with `[weight=N]` | `src/core/services/backend_routing_service.py`, `src/core/services/model_replacement_service.py` | Missing | Round-robin and random replacement exist, but no weighted random selector grammar or shared weighted chooser. |
| R4 Deterministic parsing and validation | `src/core/domain/model_utils.py` | Constraint | Deterministic single-selector parsing exists, but there is no composite grammar, nesting policy, or validation error taxonomy for composite selectors. |
| R5 Nested failover safety / bounded retries | `src/core/services/backend_completion_flow/service.py`, `src/core/services/backend_completion_flow/failure_recovery_executor.py`, `config/schemas/app_config.schema.yaml` | Constraint | Retry metadata and max failover hops exist, but they are not clearly shared across nested composite layers plus legacy failure strategy plus quality-verifier calls. |
| R6 Backward compatibility for existing selectors | `src/core/domain/model_utils.py`, `src/core/services/backend_model_resolver.py` | Present | Existing non-composite semantics are explicit and stable; compatibility risk is mainly parser precedence and migration behavior. |
| R7 Deprecate random model replacement | `src/core/services/model_replacement_service.py`, `src/core/services/request_processor_service.py`, `config/config.example.yaml` | Missing | Feature exists, but no deprecation signaling, no compatibility bridge into composite selectors, and no N+1 removal messaging. |
| R8 Observability and diagnosability | `src/core/services/backend_completion_flow/service.py`, `src/core/services/quality_verifier_orchestrator.py`, usage and capture surfaces | Constraint | Context surfaces exist, but there is no structured composite-routing trace explaining parsed branches, selected branch, skipped targets, or exhaustion cause. |

### Missing capabilities

- No parser/AST for composite selectors with operators, precedence, nesting, whitespace, or weight annotations.
- No typed "composite routing plan/decision" object flowing through resolver, execution, and observability layers.
- No single place that decides selection failure vs availability failure vs execution failure before meaningful output for composite target progression.
- No unified failover-hop budget spanning selector-level failover, legacy failover planning, failure-strategy retry/failover, and internal verifier calls when they themselves use composite selectors.
- No deprecation contract for replacement configuration to map or reject legacy replacement rules.

### Constraints from current architecture

- `BackendModelResolver` currently returns one `BackendTarget`, so adding composites there directly may overload its responsibility unless a pre-resolution composite layer is introduced.
- `BackendRoutingService` is backend-instance oriented; turning it into parser + executor + diagnostics would likely bloat a hot-path class.
- `FailureRecoveryExecutor` already increments retry metadata and decides retries; if composite failover also increments independently, attempts can explode.
- `RequestProcessorService` already treats replacement and quality-verifier scheduling specially; migration must preserve these interactions.

## Implementation Approach Options

### Option A: Extend existing components in place

**Description**

Add composite parsing and execution behavior directly into `BackendModelResolver`, `BackendRoutingService`, and `FailureRecoveryExecutor`.

**Likely touch points**

- `src/core/domain/model_utils.py`
- `src/core/services/backend_model_resolver.py`
- `src/core/services/backend_routing_service.py`
- `src/core/services/backend_completion_flow/failure_recovery_executor.py`
- `src/core/services/request_processor_service.py`
- `src/core/services/quality_verifier_orchestrator.py`

**Compatibility assessment**

- Preserves most existing call sites.
- Minimizes DI and stage wiring churn.
- High risk of mixing parsing, policy, execution, and observability responsibilities across already-important hot-path services.

**Trade-offs**

- Pros: smallest surface-area change to calling code; fastest initial implementation.
- Cons: highest risk of resolver/routing bloat, harder to test composite grammar separately, more fragile nested retry accounting.

### Option B: Create new composite-routing components

**Description**

Introduce dedicated components such as:

- composite selector parser / validator,
- composite routing plan model,
- composite routing executor / coordinator,
- composite diagnostics payload builder.

Existing resolver/routing services remain underneath as leaf primitives for single-target resolution.

**Likely integration points**

- New services under `src/core/services/`
- New interfaces under `src/core/interfaces/`
- Resolver integration at `src/core/services/backend_model_resolver.py`
- Backend execution integration at `src/core/services/backend_completion_flow/service.py`
- Replacement bridge integration at `src/core/services/request_processor_service.py`

**Responsibility boundaries**

- Parser owns syntax, weights, nesting, and validation.
- Coordinator owns branch progression and bounded hop accounting.
- Existing resolver/routing service still owns single-target backend/model resolution and candidate eligibility.
- Observability layer consumes structured routing decision objects.

**Trade-offs**

- Pros: cleaner separation, best long-term maintainability, easier unit/property testing.
- Cons: more files, more DI wiring, higher design overhead.

### Option C: Hybrid incremental migration

**Description**

Introduce a dedicated composite parser + decision context first, but reuse current single-target resolver/routing and failure executor underneath. Then layer deprecation/migration and observability on top.

**Combination strategy**

- New:
  - parser/validator,
  - composite decision model,
  - shared hop-budget context,
  - deprecation bridge adapter for replacement.
- Extend:
  - `BackendModelResolver` to delegate composite selectors,
  - `FailureRecoveryExecutor` to respect shared composite hop accounting,
  - request/quality-verifier flows to emit composite diagnostics.

**Risk mitigation**

- Preserve non-composite path unchanged.
- Gate composite selector handling on operator presence (`|`, `^`, weight syntax).
- Make migration bridge explicit and reversible in config behavior.
- Add regression tests for main, auxiliary, and quality-verifier surfaces before broad rollout.

**Trade-offs**

- Pros: best balance for a brownfield codebase; reuses proven primitives while isolating new grammar/policy.
- Cons: temporary mixed architecture until all routing surfaces fully converge.

## Complexity and Risk

- Effort: `L` — touches hot-path routing, failure handling, config/deprecation behavior, and three routing surfaces (main, auxiliary, verifier).
- Risk: `High` — parser precedence, retry explosion, and backward-compatibility regressions could affect core proxy behavior and operator trust.

## Design-Phase Recommendations

### Preferred direction to evaluate further

- Option C looks strongest for design: keep existing single-target resolution intact, but add a new composite-routing layer above it.
- Option B is the cleanest end-state and may become the target architecture if Option C is used as a staged migration.

### Research Needed

1. How should operator precedence and nesting work between `|`, `^`, URI params, and `[weight=N]` without breaking current `backend:model?x=y` semantics?
2. What exact event should consume a composite failover hop: parse rejection, candidate ineligibility, backend unavailability, retry attempt, or only branch transitions?
3. How should composite routing interact with existing failure strategy in `src/core/services/backend_completion_flow/failure_recovery_executor.py` so there is one bounded attempt budget?
4. What is the safest compatibility mapping from replacement rules in `src/core/services/model_replacement_service.py` into composite weighted-random selectors, and when must mapping fail explicitly?
5. Which observability surfaces should carry composite metadata first: wire capture, usage records, logs, diagnostics endpoints, or all of them?
6. Should quality verifier and auxiliary requests allow full composite syntax, or should some surfaces restrict explicit backend requirements for safety and clarity?

## Next Steps

1. Approve or refine the requirements in `.kiro/specs/composite-model-routing-failover-weighted-random/requirements.md`.
2. Move to `/kiro:spec-design composite-model-routing-failover-weighted-random`, carrying forward the hybrid approach and research items above.
3. In design, define a single composite-routing contract that all three surfaces use, plus a single shared attempt-budget model.
