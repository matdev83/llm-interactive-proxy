# Research & Design Decisions

## Summary
- **Feature**: `vendor-model-dynamic-routing`
- **Discovery Scope**: Complex Integration (critical routing behavior + runtime availability)
- **Key Findings**:
  - Backend selection and model-only discovery are currently config-driven (`BackendConfig.models`) and do not reflect runtime availability or connector-reported capability.
  - The resilience layer already tracks temporary availability (instance cooldown + (instance, model) cooldown) and permanent instance disablement on auth failures, but routing and failover do not fully consult this state during candidate selection.
  - `/` must be treated as part of a model identifier (e.g., `vendor/model`); only `:` can represent backend selection. This impacts parsing, routing, failover, and observability surfaces.

## Research Log

### Existing Codebase Analysis
- **Components Reviewed**:
  - `src/core/domain/model_utils.py` - parsing and URI parameter parsing
  - `src/core/services/backend_service.py` - routing resolution and failover execution
  - `src/core/services/backend_routing_service.py` - instance resolution + model discovery + alternative instance enumeration
  - `src/core/services/resilience/*` - cooldown tracking and permanent instance disable
  - `src/core/app/controllers/models_controller.py` - current models endpoint behavior
  - `src/core/app/controllers/diagnostics_controller.py` - current diagnostics endpoint behavior
- **Patterns Identified**:
  - Routing policies exist (`RoutingConfig.disable_*`) and are enforced in `BackendRoutingService`.
  - Failure handling uses a strategy (`DefaultFailureHandlingStrategy`) and currently depends on `BackendRoutingService.find_alternative_instances`.
  - Resilience decisions are modeled as pre-call availability checks and post-call failure recording.
- **Implications**:
  - A runtime capability/availability index must become the source-of-truth for model-only routing, and it should be used consistently by both initial selection and failover selection.

### Capability Discovery Constraints
- **Connector variability**:
  - Some connectors can enumerate models asynchronously (`get_available_models_async`), others rely on cached state or do not offer authoritative model listing.
  - Vendor-prefixed models (`vendor/model`) are already the preferred normalized representation at the connector boundary.
- **Configuration variability**:
  - Many backends are configured with model hints via `BackendConfig.models`, which are often unqualified model names (e.g., `gpt-4`) and may become stale.
  - Some multi-vendor backends list `vendor/model` strings; this must not be confused with backend selection.
- **Implications**:
  - Startup discovery must be best-effort and must degrade gracefully to config hints when enumeration is not available or fails.

### Availability & Error Signals
- **Existing availability signals**:
  - Resilience layer supports instance-wide cooldown and model-specific cooldown.
  - Auth failures can permanently disable instances.
  - Backend health checks can mark endpoints unhealthy (`is_backend_functional()`), which is used in parts of failover filtering.
- **Missing availability signals**:
  - No shared “permanent model unsupported on instance” state exists today for model-not-found scenarios.
  - Pre-call availability checks can currently surface a rate limit error before the system attempts alternative instances.
- **Implications**:
  - Add explicit tracking for permanent model unsupported `(instance, model)` and integrate it into candidate filtering and selection.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Extend `BackendRoutingService` | Add capability index + availability filtering into existing service | Minimal surface changes, leverages existing RR counters | Risk of growing into another “god service”; harder to test in isolation | Feasible but less clean |
| Dedicated Model Routing Service (Selected) | New service that owns model/instance selection and alternative enumeration | Clear boundary, testable, composes existing routing + resilience | Requires new interfaces + DI wiring | Preferred for long-term maintainability |
| Connector-driven routing | Ask each backend at runtime “can you handle this model?” | Most accurate | Adds latency, requires network calls per request | Rejected for perf |

## Design Decisions

### Decision: Canonical Model Identifier
- **Selected Approach**: Treat `vendor/model` as canonical model identity, and treat `/` as part of the model identifier (never backend selection).
- **Rationale**: Avoid ambiguity and align with connector contracts that already prefer vendor-prefixed models.
- **Trade-offs**: Plain model requests (e.g., `gpt-4`) become inherently ambiguous; the proxy must define a candidate discovery strategy that can return multiple candidates.

### Decision: Capability Index Implementation Strategy
- **Selected Approach**: Maintain a copy-on-write in-memory index mapping `model_id -> frozenset(instance_ids)` and `instance_id -> frozenset(model_ids)` and refresh it via best-effort startup discovery and optional periodic refresh.
- **Rationale**: Supports O(1) lookups and lock-free reads, which aligns with performance and concurrency requirements.
- **Trade-offs**: Requires careful normalization rules and a clear distinction between authoritative enumeration and config hints.

### Decision: Availability Integration
- **Selected Approach**: Candidate selection filters must consult:
  - instance-level and model-level cooldowns (resilience)
  - permanent instance disablement (auth failures)
  - permanent model unsupported `(instance, model)` state (new)
- **Rationale**: Minimizes wasted attempts and supports deterministic behavior during rate limits and misconfiguration.

## Testing Strategy Research
- Existing unit tests cover `BackendRoutingService` routing behavior and model parsing. The new routing service and capability index require focused unit tests for:
  - model-only selection behavior (`model`, `vendor/model`)
  - backend selection behavior (`backend:model`, `backend-instance:model`)
  - availability filtering (cooldown, disablement, permanent unsupported)
- Integration tests should validate DI wiring and the `/v1/models` and `/v1/diagnostics` outputs when enabled.

## Risks & Mitigations
- Risk: Over-aggressive permanent model unsupported tagging can reduce capacity.
  - Mitigation: Restrict permanent tagging to explicit “model not found” signals and provide manual reset capability.
- Risk: Startup discovery failures block availability.
  - Mitigation: Treat discovery as best-effort, fall back to configured model hints, and allow later refresh.
- Risk: Concurrency bugs in shared indexes.
  - Mitigation: Use immutable snapshots for reads and a single async lock for mutation; avoid nested locks.

## Performance Considerations
- Reads should be lock-free and constant-time for hot-path routing decisions.
- Discovery and refresh should run off the request path (startup stage and/or background task) to avoid tail latency.

## References
- Project `src/core/services/backend_service.py` - execution and failover entry point
- Project `src/core/services/backend_routing_service.py` - existing instance routing and RR pattern
- Project `src/core/services/resilience/*` - existing cooldown tracking and auth-disable logic
