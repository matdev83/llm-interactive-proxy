# Research & Gap Analysis

---
**Purpose**: Analyze the gap between the requirements for `codex-connector-refactoring-follow-up` and the current codebase to inform design and implementation strategy.

**Project Context**: Universal LLM Proxy - FastAPI async, staged initialization, DI-managed services, adapter pattern for LLM backends.
---

## Summary
- **Feature**: `codex-connector-refactoring-follow-up`
- **Discovery Scope**: Extension (brownfield refactor with strict non-regression)
- **Key Findings**:
  - The componentized `src/connectors/openai_codex/` package exists and is well-tested, but `src/connectors/openai_codex.py` still contains significant orchestration and streaming retry logic.
  - There are currently **two** streaming auth-retry implementations: an inline connector path and `ResponseExecutor` (`src/connectors/openai_codex/executor.py`), creating duplication and encapsulation violations.
  - DI registration provides a **partial** `CodexConnectorDependencies` bundle (connector-bound components are `None` by design), which is compatible with current staged init but deviates from earlier “everything via DI” expectations.

## Current State Investigation

### Key assets (Codex connector area)
- Facade connector: `src/connectors/openai_codex.py` (~1957 LOC)
- Component package: `src/connectors/openai_codex/`
  - Settings: `src/connectors/openai_codex/settings.py`
  - Credentials: `src/connectors/openai_codex/credentials.py`
  - Payload: `src/connectors/openai_codex/payload.py`
  - Executor: `src/connectors/openai_codex/executor.py`
  - Compatibility: `src/connectors/openai_codex/compat.py`
  - Tool execution: `src/connectors/openai_codex/tools.py`
  - Interfaces/contracts: `src/connectors/openai_codex/interfaces.py`, `src/connectors/openai_codex/contracts.py`

### Registration / wiring surfaces
- Backend registration: `src/connectors/openai_codex.py` registers `openai-codex` via `backend_registry`.
- DI registrations: `src/core/di/registrations/_backend/codex.py` registers `ISettingsLoader`, `ICredentialManager`, `IToolExecutionService`, and a `CodexConnectorDependencies` bundle factory.
- Backend completion orchestration and wire capture live in core: `src/core/services/backend_completion_flow/service.py` (captures inbound responses; handles streaming capture via collaborators).

### Tests pinning behavior (non-regression anchors)
- Streaming retry parity: `tests/integration/test_codex_streaming_retry_parity.py`
- Backend wiring/config precedence: `tests/integration/test_codex_backend_wiring.py`
- Component unit tests: `tests/unit/connectors/openai_codex/`

### Notable coupling / duplication hotspots (evidence)
- Inline streaming retry path still exists in connector: `src/connectors/openai_codex.py:1167` (nested `_perform_request()` / `_rendered_iterator()`).
- Connector writes executor private fields: `src/connectors/openai_codex.py:362`.
- Connector reads executor private fields: `src/connectors/openai_codex.py:1186`, `src/connectors/openai_codex.py:823`.

## Requirements Feasibility Analysis

### Requirement-to-Asset Map (with gaps)

| Requirement | Primary assets today | Status | Gaps / constraints |
|---|---|---:|---|
| Req 1 Behavior Compatibility | `src/connectors/openai_codex.py`, component package, integration tests | Partial | Behavior appears pinned by tests, but duplicate execution paths increase regression risk during further refactors. |
| Req 2 SOLID boundaries | `src/connectors/openai_codex/interfaces.py`, `src/connectors/openai_codex/*` | Partial | Facade still contains logic that belongs in services; direct private-state access violates contract boundaries. |
| Req 3 Single execution path | `src/connectors/openai_codex.py`, `src/connectors/openai_codex/executor.py` | Missing | Connector can bypass `ResponseExecutor` using inline `_perform_request` path; executor is not the sole path. |
| Req 4 DI and wiring compatibility | `src/core/di/registrations/_backend/codex.py`, `CodexConnectorDependencies` | Partial | DI provides a partial bundle (connector-bound components omitted). This is a constraint to document and design around, not necessarily a bug. |
| Req 5 Credential safety | `src/connectors/openai_codex/credentials.py`, tests | Likely satisfied | Needs preservation; risk is regressions when moving refresh orchestration between facade and executor. |
| Req 6 Streaming retry parity | `src/connectors/openai_codex/executor.py`, tests | Partial | Parity tests exist, but retry logic is duplicated in connector; must converge to one owner to meet the requirement intent. |
| Req 7 Compatibility flows | `src/connectors/openai_codex/compat.py`, `src/connectors/openai_codex.py` | Partial | Behavior seems tested, but connector injects compatibility internals (`_session_detector`, `_kilo_translator`) instead of using explicit public APIs. |
| Req 8 Observability/capture | Core flow + envelopes: `src/core/services/backend_completion_flow/service.py` | Constraint | Capture/usage are predominantly orchestrated in core; connector must preserve envelope fields, headers, and usage metadata. Any “connector supplies capture data” requirement should be interpreted as “doesn’t break core capture expectations”. |
| Req 9 Testability/maintainability | Unit/integration tests; component interfaces | Partial | Test seams exist but are currently achieved partly through private attribute access; goal is stable public configuration and fewer internals in tests. |

### Complexity signals
- Streaming + retry + auth refresh is inherently stateful and subtle (ordering, cancellation, header refresh, error shapes).
- Compatibility flows add cross-cutting translation and per-request state lifecycle (especially for streaming).
- The codebase’s “truth” for capture/usage is in core orchestration; refactor must respect that boundary.

### Research Needed (for design phase)
- Streaming cancellation and cleanup semantics: ensure moving execution to executor preserves cancellation callback behavior and compatibility state cleanup timing.
- Kilo/Droid post-processing location: determine whether `_format_kilo_stream_response` and response merging should remain in facade, move to compatibility layer, or be treated as part of compatibility pipeline.
- Executor configuration surface: define public configuration (constructor vs. setters) that avoids tests mutating private fields (e.g., `_max_retries`).
- Envelope metadata expectations: confirm which envelope fields are consumed by core usage accounting/capture and ensure they remain stable.

## Implementation Approach Options

### Option A: Extend existing components (minimal structural change)
**Idea**: Keep the current component set; refactor `src/connectors/openai_codex.py` to always delegate execution (streaming + non-streaming) to `ResponseExecutor`, and remove inline retry paths.

**Pros**: Lowest footprint; best chance of non-regression; leverages existing tests and service implementations.  
**Cons**: Still leaves some connector-bound dependencies awkward for DI unless clarified; may require careful relocation of Kilo/Droid formatting logic.

### Option B: Create new micro-components (policy/header builder)
**Idea**: Introduce explicit `RetryPolicy` / `HeaderBuilder` services and shift more logic out of executor.

**Pros**: Cleanest SRP boundaries on paper; policy logic becomes independently testable.  
**Cons**: Higher change surface and higher regression risk; more files and new abstractions may not be justified given existing test coverage and current architecture.

### Option C: Hybrid phased migration (recommended for design exploration)
**Idea**: Phase 1: make `ResponseExecutor` the single execution path and remove private-state pokes; Phase 2: optionally extract policy/header helpers if still beneficial.

**Pros**: Preserves behavior while tightening boundaries; reduces regression risk by sequencing; lets tests validate each step.  
**Cons**: Requires disciplined staging and temporary compatibility shims during transition.

## Effort & Risk
- **Effort**: L (1–2 weeks) — touches streaming execution, DI seams, compatibility lifecycle, and tests; requires multiple safe refactor passes.
- **Risk**: Medium–High — streaming auth retry and compatibility flows are sensitive; mitigated by strong existing unit/integration test coverage.

## Recommendations for Design Phase
- Prefer Option C as the planning baseline: converge on a single execution path first, then decide if further extraction is worth the added abstraction.
- Treat DI “partial bundle” behavior as a first-class constraint: document which components are connector-bound and how overrides are supported.
- Use existing integration tests as the primary non-regression contract; add targeted tests only for newly introduced public configuration APIs (not for internal structure).

## Design Decisions (to carry into design.md)

### Decision: Single execution path via response executor
- **Context**: Req 3.1–3.4, Req 6.1–6.4. Duplicate streaming retry implementations increase drift risk.
- **Alternatives Considered**:
  1. Keep the connector inline `_perform_request` streaming path and treat `ResponseExecutor` as optional.
  2. Make `ResponseExecutor` the single execution path for streaming and non-streaming Codex responses calls.
- **Selected Approach**: Always delegate Codex responses calls to `ResponseExecutor.execute(...)` and remove inline retry logic from the facade.
- **Rationale**: Centralizes retry, token refresh, cancellation, and error-shape parity in one independently testable unit.
- **Trade-offs**: Requires migrating any remaining connector-local formatting/translation hooks into either the executor or the compatibility layer.
- **Follow-up**: Confirm cancellation callback semantics and compatibility state cleanup timing remain unchanged in integration tests.

### Decision: Public configuration APIs instead of private field mutation
- **Context**: Req 2.4 and Req 9.6. Existing tests and connector code mutate private executor fields (e.g., `_max_retries`).
- **Alternatives Considered**:
  1. Continue mutating private fields (fast but brittle).
  2. Configure executor via constructor parameters and/or explicit public configuration methods.
- **Selected Approach**: Configure retry/backoff and compatibility integration via constructor parameters; reserve explicit setters only when runtime reconfiguration is required.
- **Rationale**: Preserves encapsulation and prevents tests from depending on internal attributes.

### Decision: DI remains a partial bundle for connector-bound components
- **Context**: Req 4.2–4.4. Some services require a connector instance reference.
- **Alternatives Considered**:
  1. Register all components in DI (requires connector-aware factories and more complex lifetimes).
  2. Register connector-agnostic components in DI and keep connector-bound components constructed by the connector, with explicit override hooks.
- **Selected Approach**: Continue with a partial `CodexConnectorDependencies` bundle: DI provides connector-agnostic singletons and optional overrides; the connector constructs connector-bound defaults.
- **Rationale**: Fits staged initialization patterns and keeps backend factory wiring stable.
