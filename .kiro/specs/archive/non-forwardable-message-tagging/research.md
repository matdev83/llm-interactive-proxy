# Research & Design Decisions

---
**Purpose**: Capture discovery findings, architectural investigations, and rationale that inform the technical design.

**Project Context**: Universal LLM Proxy - FastAPI async, DI containers, staged initialization, adapter pattern.
---

## Summary
- **Feature**: `non-forwardable-message-tagging`
- **Discovery Scope**: Extension / Complex Integration
- **Key Findings**:
  - Current “do not forward” behavior is partially implemented via regex-based command stripping and metadata-dependent heuristics, which is fragile under client history re-submission.
  - All remote backend calls are orchestrated through `BackendCompletionFlow`; enforcing filtering inside this flow provides the required single enforcement point across normal requests and internal workflows (retries/steering).
  - Client-provided message metadata is untrusted; reliable matching requires server-derived deterministic message identities stored server-side for the session lifetime.
  - Requirements explicitly mandate alpha-stage finality: remove legacy regex-based non-forwardable filtering mechanisms and do not preserve backward compatibility or fallback behavior.

## Research Log

### Existing Codebase Analysis
- **Components Reviewed**:
  - Request orchestration: `src/core/services/request_processor_service.py`
  - Command handling: `src/core/services/command_handler.py`, `src/core/commands/*`
  - Current filtering/heuristics: `src/core/services/redaction_middleware.py`, `src/security.py` (`ProxyCommandFilter`)
  - Backend orchestration boundary: `src/core/services/backend_completion_flow/service.py`
  - Session resolution/persistence: `src/core/services/session_service_impl.py`, `src/core/domain/session.py`, `src/core/services/intelligent_session_resolver.py`
  - Wire capture: `src/core/services/backend_completion_flow/service.py` (outbound capture before backend call)
- **Patterns Identified**:
  - Staged initialization and DI registration using `ServiceCollection` factories
  - Clear orchestration seams in `BackendCompletionFlow` (preparation → capture → backend invoke)
  - Existing per-session persistence and state management patterns via `ISessionService` and repository
- **Implications**:
  - Implementing non-forwardable filtering at the `BackendCompletionFlow` boundary can guarantee coverage of all backend calls and ensures wire captures reflect filtered payloads.
  - Tagging must be stored server-side as part of the session model or an associated persistence model (session lifetime durability).

### Current Non-Forwardable Mechanisms and Fragility
- **Context**: The requirements describe fragile behavior relying on regex matching and metadata that may not round-trip through clients.
- **Sources Consulted**:
  - `src/security.py` (`ProxyCommandFilter`)
  - `src/core/services/redaction_middleware.py` (command filtering and proxy-response pair removal)
  - `src/core/services/response_manager_service.py` (proxy response metadata marking)
- **Findings**:
  - Regex-based stripping is content-mutating and is not reliably tied to session identity or “previously seen” message recognition.
  - Proxy response filtering depends on `metadata` markers that clients may drop or modify.
- **Implications**:
  - The new design must remove regex-based non-forwardable enforcement and replace it with server-derived message identity + session-scoped tags.

### Backend Call Boundary Coverage
- **Context**: Requirement 7 requires a single authoritative enforcement point for all backend calls, including internal workflows.
- **Sources Consulted**:
  - `src/core/services/backend_service.py` (delegates to `BackendCompletionFlow`)
  - `src/core/services/backend_completion_flow/service.py` (orchestration + outbound capture + backend invoke)
  - `src/core/services/tool_call_retry_coordinator.py` (internal workflow that triggers backend calls)
- **Findings**:
  - Backend invocation occurs after outbound capture inside `BackendCompletionFlow`; filtering must occur before capture to satisfy requirement 6.3.
  - Multiple upstream call sites exist (normal request flow, internal retry/steering) but converge on `BackendCompletionFlow`.
- **Implications**:
  - The enforcement point should be introduced inside `BackendCompletionFlow` (or its request preparation collaborator) immediately prior to capture/invocation.

### Trust Boundaries and Provenance
- **Context**: Requirement 4.3 forbids trusting client-provided tags; clients may resend history with modified metadata.
- **Findings**:
  - Identity computation must not rely on client-preserved metadata, but the system still needs a way to prevent “client echo” of server-injected messages from being re-forwarded.
- **Implications**:
  - “Non-forwardable” must be driven by server-side registry membership, with a deterministic identity derived from message content/fields.
  - The design should treat message provenance (client history vs server injection) as an internal concept during backend request composition, rather than trusting message metadata from clients.

### Legacy Removal Requirement
- **Context**: Requirement 13.1-13.3 requires removal of regex-based non-forwardable mechanisms and forbids compatibility fallbacks.
- **Findings**:
  - Relevant legacy/fragile enforcement candidates include:
    - `src/security.py::ProxyCommandFilter` usage for stripping proxy commands from outbound prompts.
    - Command/proxy-response removal in `src/core/services/redaction_middleware.py` used to prevent forwarding command artifacts.
    - Tests asserting emergency-filter behavior (`tests/unit/test_emergency_command_filter.py`, `tests/unit/core/test_redaction_middleware.py` sections tied to command filtering).
- **Implications**:
  - Design and implementation must explicitly delete these mechanisms (not just disable them) and adjust tests to assert the new final behavior.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Extend existing redaction/regex filters | Keep filtering in request transform pipeline | Minimal wiring changes | Fail-open semantics; incomplete coverage of internal backend calls; violates 13.1-13.3 | Rejected |
| **Service + boundary enforcement (Option B)** | New registry + identity service; enforce inside backend completion flow | Single enforcement point; covers retries/steering; wire capture correctness | Requires cross-cutting integration for tagging and injection provenance | **Selected** |
| Hybrid (temporary dual behavior) | Keep legacy as fallback while introducing new mechanism | Lower migration risk | Explicitly forbidden by 13.2 and alpha finality | Rejected |

## Design Decisions

### Decision: Enforce Filtering in BackendCompletionFlow
- **Context**: Requirement 7.1/7.2 require filtering immediately before every backend call; requirement 6.3 requires wire capture reflect filtered payloads.
- **Alternatives Considered**:
  1. Transform pipeline enforcement (fail-open) in `RequestTransformPipeline`
  2. Enforcement inside `BackendCompletionFlow` prior to capture/invocation
- **Selected Approach**: Apply non-forwardable filtering inside `BackendCompletionFlow` (or its request preparation collaborator) after session resolution and before outbound capture/backend invocation.
- **Rationale**: All backend calls converge on this flow; it provides a single gate that also affects wire capture content.
- **Trade-offs**: Requires tagging to be accessible from multiple upstream components (commands, steering injectors).
- **Follow-up**: Verify there are no out-of-band backend calls bypassing `BackendCompletionFlow`; if found, refactor to converge.

### Decision: Deterministic Message Identity
- **Context**: Requirement 1.2/1.4 requires recognition of previously tagged messages without relying on client metadata.
- **Selected Approach**: Define a deterministic identity derived from stable message fields (role + normalized content + relevant structured fields) and store only the identity (hash) in session tags.
- **Trade-offs**: Collision risk (mitigated by strong hash); normalization policy must be consistent across protocols/content variants.
- **Follow-up**: Confirm which message fields are stable across protocol translations and ensure identity computation is canonical.

### Decision: Persistence Model for Session Lifetime
- **Context**: Requirement 1.3 requires tag immutability for the session lifetime; restarts should not silently lose tags if sessions are persisted.
- **Selected Approach**: Persist non-forwardable identities in session storage (either as part of session state or a session-associated persistence structure).
- **Trade-offs**: Potential growth in stored data; must apply retention bounds consistent with session lifetime semantics.
- **Follow-up**: Decide whether to store tags in `SessionState` or a dedicated repository model; ensure repository update semantics are safe under concurrent requests.

### Decision: Alpha Finality and Legacy Deletion
- **Context**: Requirement 13.1-13.3 requires removal of regex-based non-forwardable filtering and forbids fallbacks/backward compatibility.
- **Selected Approach**: Remove legacy enforcement code paths and their tests; update behavior to rely solely on message tagging + boundary enforcement.
- **Follow-up**: Ensure no remaining regex-based non-forwardable enforcement or “compat” toggles exist post-implementation.

### Decision: DI Lifetime Selection
- **Selected Approach**:
  - Identity computation: `Singleton` (pure, stateless)
  - Registry service: `Singleton` (coordinates persistence/caching; keyed by session id)
  - Backend-call filter/enforcer: `Singleton` (stateless; uses registry)

### Decision: Error Handling Strategy
- **Context**: Requirement 7.3 and requirement 10.1 require fail-closed behavior when filtering cannot be safely performed.
- **Selected Approach**:
  - Introduce a dedicated `LLMProxyError` subclass for non-forwardable enforcement failures (internal error → fail before backend call).
  - Introduce a client-visible structured error for “no forwardable content” (requirement 5.3).

## Testing Strategy Research

### Existing Test Patterns
- Unit tests for middleware and request processing exist under `tests/unit/core/` and `tests/unit/services/`.
- Integration tests cover orchestration and retry flows under `tests/integration/`.

### Coverage Requirements (for this feature)
- Ensure non-forwardable messages are excluded from outbound backend payloads for:
  - Normal requests (history re-submission)
  - Internal workflows that cause backend calls (retry/steering)
- Ensure legacy regex-based filtering is removed (tests updated accordingly).

## Risks & Mitigations
- Risk: Message identity mismatch due to protocol translation differences — Mitigation: define canonical identity inputs at a stable boundary (domain `ChatMessage` contract) and use deterministic serialization.
- Risk: Tag storage growth — Mitigation: define explicit bounds consistent with session lifetime and operational expectations; store hashes only.
- Risk: Concurrent requests mutating tag state — Mitigation: use repository-level atomic updates or optimistic concurrency strategy; treat tags as append-only/monotonic.

## Performance Considerations
- Identity hashing adds per-message overhead; mitigate via:
  - Hashing only fields required for identity
  - Caching identities for repeated message objects within a request
- Ensure filtering happens before wire capture to avoid duplicated compute/capture work.

## References
- Project steering: `.kiro/steering/structure.md`, `.kiro/steering/tech.md`, `.kiro/steering/testing.md`
- Error hierarchy: `src/core/common/exceptions.py`
- Backend orchestration: `src/core/services/backend_completion_flow/service.py`
- Session domain model: `src/core/domain/session.py`
