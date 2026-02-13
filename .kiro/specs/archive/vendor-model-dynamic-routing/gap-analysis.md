# Gap Analysis: vendor-model-dynamic-routing

## Executive Summary

The codebase already contains core building blocks for this feature: canonical `:` parsing, backend-instance and backend-type routing, resilience cooldown/disablement, and B2BUA A-leg/B-leg identity handling. The largest gaps are around **capability indexing**, **availability-aware candidate selection before dispatch**, **canonical backend-agnostic observability**, and **single-instance enforcement for constrained OAuth connector families**.

**Primary evidence (existing assets):**
- Parsing and resolver entry points: `src/core/domain/model_utils.py`, `src/core/services/backend_model_resolver.py`
- Routing behavior and round-robin counters: `src/core/services/backend_routing_service.py`
- Runtime availability primitives: `src/core/services/backend_completion_flow/availability_checker.py`, `src/core/services/resilience/coordinator.py`, `src/core/services/resilience/rate_limit_state.py`
- B2BUA continuity/isolation primitives: `src/core/services/backend_completion_flow/completion_session_resolver.py`, `src/core/services/backend_completion_flow/service.py`, `src/core/services/b2bua_session_resolver_service.py`
- Observability endpoints: `src/core/app/controllers/models_controller.py`, `src/core/app/controllers/diagnostics_controller.py`

**Effort:** L (1-2 weeks)
**Risk:** High (routing is hot-path/core behavior; regressions can affect availability, latency, and compatibility)

## 1. Current State Investigation

### Key assets already in place

- **Unambiguous parsing baseline exists:**
  - `parse_model_backend()` splits on first `:` and does not infer backend from `/`.
  - `parse_model_with_params()` preserves `vendor/model` payload semantics.
- **Routing primitives are present:**
  - Explicit instance routing (`backend.instance`) and backend-type round robin are implemented.
  - Model-only routing exists via config model lists and RR over discovered candidates.
- **Runtime resilience primitives are present:**
  - Instance-level cooldown/disablement and (instance, model) cooldown exist.
  - Authentication failures can permanently disable instances.
  - Success clears temporary model cooldown.
- **Session-aware execution is in place:**
  - B2BUA A-leg continuity and per-attempt B-leg allocation are implemented with fail-open behavior.
  - Auxiliary routing derives isolated session IDs (`aux::<session>`).
- **Shared backend call path mostly exists:**
  - `BackendService.chat_completions()` delegates to `BackendCompletionFlow.call_completion()`.
  - Quality verifier calls backend through `IBackendService`.

### Conventions and constraints relevant to implementation

- Async FastAPI and DI/staged startup patterns are established (`.kiro/steering/tech.md`).
- Round-robin state is lock-protected in `BackendRoutingService`.
- Existing diagnostics and models listing are backend-centric, not capability-index-centric.

## 2. Requirement-to-Asset Map (with Gaps)

Legend: **Present** / **Constraint** / **Missing** / **Unknown**

| Requirement Area | Existing Assets | Status | Gap Notes |
|---|---|---:|---|
| R1: Model addressing semantics (`:`, first-split, `/` payload) | `model_utils.py`, `backend_model_resolver.py` | Present | Core semantics are implemented; consistency across all auxiliary feature entry points should still be verified by tests. |
| R2: `backend:model` instance selection + pre-call no-available error | `backend_routing_service.py` | Constraint | Round robin exists, but selection-time filtering only uses externally excluded backends; resilience cooldown state is checked later in completion flow, not during candidate selection. |
| R3: Model-only routing (`model` / `vendor/model`) | `backend_routing_service.py` | Constraint | Candidate discovery is config-list driven and not backed by a dedicated capability index; unknown-model vs unavailable classification is not explicit at routing boundary. |
| R4: Runtime availability integration | `availability_checker.py`, `resilience/*` | Constraint | Instance/model cooldown and auth disablement exist, but no permanent `(instance, model)` unsupported state for model-not-found and no full pre-selection filtering pipeline. |
| R5: Capability discovery/indexing | none dedicated; partial behavior in `models_controller.py` and backend config lists | Missing | No shared `model -> instances` index used by request routing and `/v1/models`; no atomic refresh model. |
| R6: Observability of routing/availability | `models_controller.py`, `diagnostics_controller.py` | Missing | `/v1/models` emits backend-prefixed IDs in many cases; diagnostics do not expose eligibility mapping or unknown vs temporarily unavailable classification. |
| R7: NFR performance/concurrency/bounded attempts | RR lock, async flow, `FailureHandlingConfig.max_failover_hops` | Constraint | Bounded attempts are present, but constant-time capability lookup path is missing until capability index is introduced. |
| R8: Compatibility/migration | `parse_model_backend()`, `validate_static_route()` | Constraint | `backend/model` parsing behavior is correct, but broad config/input validation for explicit-backend-required contexts is not centralized. |
| R9: Session-aware routing and B2BUA identity isolation | `completion_session_resolver.py`, `b2bua_session_resolver_service.py`, `backend_completion_flow/service.py` | Present | A-leg continuity, per-attempt B-leg identity, fail-open, and auxiliary isolation are implemented. |
| R10: Project-wide routing unification | `BackendModelResolver` + completion flow usage + quality verifier via `IBackendService` | Constraint | Core paths are largely unified; explicit development-time anti-bypass validation is not present. |
| R11: Connector autonomy and hierarchical composition | Connector boundaries + proxy flow separation | Constraint | Current behavior mostly preserves connector autonomy, but precedence rules (proxy timeout/cancel/failover vs connector hold/wait) are not formalized in one policy surface. |
| R12: Single-instance policy for constrained OAuth families | no dedicated validator found | Missing | No semantic validation currently enforces one-instance constraint for `gemini-oauth*`, `antigravity*`, and `qwen-oauth`. |

## 3. Implementation Approach Options

### Option A: Extend existing components in place

**Description:** Keep `BackendRoutingService` as the central selector and extend it with availability-aware candidate filtering, capability indexing behavior, and clearer error classification.

**Likely touch points:**
- `src/core/services/backend_routing_service.py`
- `src/core/services/backend_model_resolver.py`
- `src/core/services/backend_completion_flow/availability_checker.py`
- `src/core/services/resilience/rate_limit_state.py`
- `src/core/app/controllers/models_controller.py`, `src/core/app/controllers/diagnostics_controller.py`
- `src/core/config/semantic_validation.py`

**Trade-offs:**
- Pros: fewer new files, faster initial delivery.
- Cons: risks turning routing service into a large mixed-responsibility component.

### Option B: Introduce dedicated capability/routing components

**Description:** Add explicit `ModelCapabilityIndex` and `ModelCapabilityDiscoverer` services, plus a dedicated routing facade that all outbound call categories use.

**Likely integration points:**
- New services/interfaces in `src/core/services/` and `src/core/interfaces/`
- DI wiring in `src/core/di/registrations/`
- Models/diagnostics controllers consume index snapshots

**Trade-offs:**
- Pros: clean boundaries, better long-term maintainability, easier isolated testing.
- Cons: larger initial refactor and DI wiring complexity.

### Option C: Hybrid incremental migration

**Description:** Introduce capability index and constrained-instance validator first, while reusing existing resolver/routing service for initial adoption; then move non-primary call paths and observability fully onto the new index-backed contracts.

**Trade-offs:**
- Pros: balanced risk, incremental rollout, easier regression control.
- Cons: temporary dual behavior during transition.

## 4. Implementation Complexity & Risk

- **Effort: L (1-2 weeks)** - Multi-surface work across routing, resilience integration, observability endpoints, config semantic validation, and tests.
- **Risk: High** - Changes affect request hot path, failover behavior, and compatibility semantics across multiple features.

## 5. Recommendations for Design Phase (Information, not final decisions)

### Likely preferred direction

- **Option C (Hybrid)** is the safest path for brownfield integration: add missing capability/index and validation primitives first, then converge all routing/observability paths on those primitives.

### Research Needed

1. **Model-not-found classification contract:** normalize provider-specific signals for permanent `(instance, model)` unsupported marking.
2. **Canonical model normalization policy:** deterministic handling of `model` vs `vendor/model` collisions and alias interactions.
3. **Routing error taxonomy surface:** standardize API error codes/details for `unknown_model` vs `temporarily_unavailable`.
4. **Constrained-family policy source of truth:** finalize exact connector-family match rules (prefix/pattern vs explicit names) and migration diagnostics.
5. **No-bypass enforcement mechanism:** define development-time guardrails (tests/lint/check script) for outbound call paths.
6. **Observability payload bounds:** design scalable diagnostics for `model -> eligible instances` without payload explosion or secret leakage.
