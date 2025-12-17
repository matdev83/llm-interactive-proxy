# Research & Design Decisions

## Summary
- **Feature**: `tool-call-reactor-middleware-god-object-refactoring`
- **Discovery Scope**: Extension (brownfield refactor of an existing subsystem)
- **Key Findings**:
  - `src/core/services/tool_call_reactor_middleware.py` contains both `ToolCallReactorFeature` and a deprecated `ToolCallReactorMiddleware` with substantial duplicated logic, driving size/complexity.
  - Several downstream components rely on a stable swallow/steering metadata contract (for example retry-on-swallow and streaming accumulation reset).
  - Streaming tool-call buffering is accessed via a DI-registered `StreamingContextRegistry` that is also exposed through a global accessor used across multiple services; eliminating “required” global state is a central design constraint.

## Research Log

### Existing Codebase Analysis
- **Components Reviewed**:
  - `src/core/services/tool_call_reactor_middleware.py` (feature + legacy middleware, replacement response creation, parsing, fixups, lifecycle/dedup)
  - `src/core/services/tool_call_reactor_service.py` (handler orchestration, telemetry, argument snapshotting)
  - `src/tool_call_loop/lifecycle_registry.py` (stream lifecycle/dedup semantics)
  - `src/core/services/streaming/stream_context_registry.py` (buffer state + global registry entry points)
  - `src/core/services/backend_request_manager_service.py` (retry-on-swallow contract)
  - `src/core/services/streaming/content_accumulation_processor.py` (uses `_steering_replacement` to reset buffering)
  - `src/core/services/streaming/vtc_response_wrapper.py` (VTC path invokes reactor separately and sets VTC metadata)
  - `src/core/di/services.py` (DI wiring for feature, legacy middleware, and global streaming registry)
  - Tests: `tests/unit/core/services/test_tool_call_reactor_middleware.py`, `tests/integration/test_tool_call_reactor_wiring.py`, `tests/streaming_regression/test_streaming_features.py`
- **Patterns Identified**:
  - Feature parity migration pattern: `IResponseFeature` for parity + thin legacy `IResponseMiddleware` wrappers (observed in JSON repair and other middleware)
  - DI registration via `ServiceCollection` factory functions in `src/core/di/services.py`
  - Cross-cutting streaming state stored in `StreamingContextRegistry` and passed via context where possible
  - “Fail-open” behavior: exceptions inside middleware are logged and processing continues
- **Implications**:
  - The refactor must centralize shared logic so feature + legacy middleware delegate to the same core processor to eliminate duplication.
  - The refactor must preserve metadata keys relied upon by retry and streaming processors while preventing client-visible leaks.

### Metadata Contract (Swallow/Steering)
- **Context**: Replacement responses and retry-on-swallow behavior depend on metadata that is produced in the tool-call reactor layer and consumed later.
- **Sources Consulted**: `src/core/services/tool_call_reactor_middleware.py`, `src/core/services/backend_request_manager_service.py`, `src/core/services/steering_leak_protection.py`
- **Findings**:
  - `tool_call_swallowed`, `steering_message`, `swallowed_tool_calls`, `swallowed_original_content`, and `_steering_replacement` are effectively a public internal contract.
  - `ContentAccumulationProcessor` specifically depends on `_steering_replacement` to avoid appending steering content to previously accumulated content.
  - `SteeringLeakProtector` sanitizes leaked internal keys if they appear in outbound content, but the preferred strategy is prevention at the source.
- **Implications**:
  - The replacement response builder must remain stable and centralized, and it must ensure safe client-facing structures.
  - Design should treat these keys as “compatibility metadata” with explicit ownership.

### Streaming Context Registry and Global Access
- **Context**: Several services still use `get_global_streaming_context_registry()` as a fallback access path to stream state.
- **Sources Consulted**: `src/core/services/streaming/stream_context_registry.py`, `src/core/di/services.py`, call sites across `src/core/services/`
- **Findings**:
  - DI registers a singleton `StreamingContextRegistry` and sets it into a module-level global.
  - Tool-call reactor feature/middleware attempt to resolve buffer state from context first, then fall back to global registry by stream id.
- **Implications**:
  - The refactor should inject a buffer accessor abstraction so the subsystem is constructible without globals (7.3), even if other legacy call sites continue to use them.
  - The design should plan for incremental migration of other global call sites as follow-on work (out of scope for this spec unless required to meet 7.3 for the tool-call reactor subsystem).

### VTC Path Alignment
- **Context**: VTC clients trigger tool-call handling via `vtc_response_wrapper.py`, which separately invokes the reactor.
- **Sources Consulted**: `src/core/services/streaming/vtc_response_wrapper.py`, tool-call reactor middleware/feature
- **Findings**:
  - VTC wrapper parses tool arguments differently than the main feature (simpler JSON parse).
  - VTC wrapper sets VTC-specific metadata markers (`vtc_tool_calls`, `vtc_tool_calls_swallowed`) and is intentionally bypassed by the main reactor feature to avoid double-processing.
- **Implications**:
  - The design should explicitly decide whether VTC should reuse the same parsing/fixup pipeline as the main reactor feature, or remain separate with a shared compatibility surface only (metadata + handler invocation).

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| A: Extend existing file | Keep logic in `tool_call_reactor_middleware.py` with minor cleanup | Low integration churn | Cannot meet 8.1/8.2; duplication persists | Not viable |
| B: New subsystem package | Create `src/core/services/tool_call_reactor/` with small components and DI wiring | SOLID + testability; meets size/complexity gates | Requires careful contract preservation | Recommended |
| C: Hybrid incremental | First extract a shared processor used by both feature + legacy middleware; then split further | Lowest regression risk; enables checkpointed tests | Risk of stopping early with a “new god object” | Recommended rollout strategy |

## Design Decisions

### Decision: Centralize Tool-Call Processing in a Delegating Orchestrator
- **Context**: Eliminate duplicated logic and provide a stable core for both feature and legacy middleware.
- **Alternatives Considered**:
  1. Keep feature and middleware separate and refactor both independently.
  2. Build a shared processor that both delegate to.
- **Selected Approach**: Introduce a `ToolCallReactorOrchestrator` component that owns the high-level flow and delegates to smaller collaborators (extraction, normalization, dedup, parsing, fixups, replacement creation).
- **Rationale**: Aligns with the project’s “thin orchestrator + collaborators” pattern used in other subsystems and enables strict LOC/CC caps.
- **Trade-offs**: More DI registrations and interfaces; requires clear ownership boundaries to avoid another monolith.
- **Follow-up**: Add characterization tests around metadata contracts before restructuring.

### Decision: Treat Swallow/Steering Metadata as a Compatibility Contract
- **Context**: Downstream retry and streaming processors depend on specific metadata keys and flags.
- **Alternatives Considered**:
  1. Keep keys but scatter creation across processors.
  2. Centralize creation and document ownership.
- **Selected Approach**: Centralize replacement response creation and metadata shaping in a `ReplacementResponseFactory`.
- **Trade-offs**: Some internal metadata remains “sticky” until a broader cleanup; mitigated by explicit sanitization strategy.

### Decision: DI-First Access to Streaming Tool-Call Buffers
- **Context**: Requirement 7.3 requires DI constructibility without global mutable state.
- **Alternatives Considered**:
  1. Continue using `get_global_streaming_context_registry()` everywhere.
  2. Inject `StreamingContextRegistry` and use global only as a legacy fallback outside the subsystem.
- **Selected Approach**: Inject a `ToolCallBufferAccessor` that uses DI-provided `StreamingContextRegistry`; the tool-call reactor subsystem does not require globals.
- **Trade-offs**: Other call sites may remain global; migration can be phased.

### Decision: Abstract Tool-Call Buffer State Contract to Preserve Layering
- **Context**: Interfaces under `src/core/interfaces/` must not import concrete types from `src/core/services/` to preserve dependency direction and avoid cross-layer coupling.
- **Alternatives Considered**:
  1. Expose `ToolCallBufferState` (from streaming services) directly in interfaces.
  2. Define an abstract buffer-state contract in `src/core/interfaces/` and adapt concrete streaming state behind it.
- **Selected Approach**: Define `IToolCallBufferState` in `src/core/interfaces/` and return it from `IToolCallStreamContextResolver`. Implement an adapter around the existing streaming `ToolCallBufferState`.
- **Rationale**: Preserves 7.4 while allowing incremental migration of legacy global access paths.
- **Trade-offs**: Adds a small adapter layer; requires careful mapping of cursor/processed signatures semantics.

### Decision: Typed Tool Arguments Envelope with Dict Compatibility Mapping
- **Context**: The current system can produce tool-argument shapes that do not match `ToolCallContext.tool_arguments: dict[str, Any]`, creating ambiguity and handler risk.
- **Alternatives Considered**:
  1. Preserve current variability and widen the handler contract (dict/list/str).
  2. Enforce a single normalized argument shape and map all inputs into it.
- **Selected Approach**: Introduce an internal Pydantic v2 model `ToolArgumentsEnvelope` and enforce `normalized_args` as the only shape passed to handlers. Non-object inputs are wrapped into a dict using reserved keys (for example `__proxy_args_list__`, `__proxy_args_raw__`).
- **Rationale**: Preserves existing public interface compatibility while enabling strong internal typing and consistent behavior across streaming, non-streaming, and VTC paths.
- **Trade-offs**: Adds a small internal schema layer; requires careful choice of reserved keys to avoid collisions.
- **Follow-up**: Decide and document the reserved key namespace and add tests to ensure these keys do not leak into client-visible outputs.

### Decision: Quality Gate Enforcement for 8.1/8.2
- **Context**: Requirements require measurable enforcement of `<600 LOC` per file and `CC < 50`.
- **Alternatives Considered**:
  1. Manual review only.
  2. Add a repo command/script using existing dev deps (`radon`/`xenon`) and wire into CI.
- **Selected Approach**: Define a single command in documentation/CI that checks complexity for the refactored package and fails on threshold violations.
- **Trade-offs**: Requires a clear single-source configuration for thresholds.

### Decision: DI Lifetime Selection
- **Selected Approach**:
  - Stateless processors/services: `Singleton`
  - Per-request / per-stream state: stored in `StreamingContextRegistry` and `ToolCallLifecycleRegistry` (both `Singleton` with internal bounded state)

### Decision: Error Handling Strategy
- **Selected Approach**:
  - Tool-call reactor processing remains fail-open: exceptions are logged with `exc_info=True`, processing continues or returns unchanged response when no actionable tool calls exist.
  - No new public exception types are introduced unless required for tests; internal errors remain internal.

## Risks & Mitigations
- Risk: Behavior drift in metadata keys used by retry and streaming processors - Mitigation: characterize key invariants with existing integration/regression tests and add targeted unit tests for `ReplacementResponseFactory`.
- Risk: Introducing a new “central processor” that becomes a new God Object - Mitigation: enforce component boundaries with LOC/CC limits and per-component focused interfaces.
- Risk: VTC path divergence - Mitigation: explicitly document whether VTC uses shared parsing/fixups; add regression tests for both paths.
