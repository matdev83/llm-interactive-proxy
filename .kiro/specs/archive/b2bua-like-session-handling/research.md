# Research & Design Decisions

---
**Purpose**: Capture discovery findings, architectural investigations, and rationale that inform the technical design.

**Project Context**: Universal LLM Proxy - FastAPI async, DI containers, staged initialization, adapter pattern.
---

## Summary
- **Feature**: `b2bua-like-session-handling`
- **Discovery Scope**: Complex Integration (Extension)
- **Key Findings**:
  - The codebase currently uses a single `session_id` across session state, backend execution, usage tracking, and wire capture; several paths treat client inputs as authoritative and some subsystems fall back to `request_id` as a “session-like” identifier.
  - Backend orchestration already supports multi-attempt failover, but has no first-class per-attempt identity; the same identifier is reused across attempts, which blocks correct A-leg→B-leg mapping.
  - Multi-user auth enforcement (SSO middleware) gates requests but does not attach a stable token identity to the request context; session continuity scoping therefore needs an explicit `auth_scope_id` derivation/injection strategy.

## Research Log

### Existing Codebase Analysis
- **Components Reviewed**:
  - RequestContext + adapters: `src/core/domain/request_context.py`, `src/core/transport/fastapi/request_adapters.py`
  - Session resolution and continuity: `src/core/services/session_resolver_service.py`, `src/core/services/intelligent_session_resolver.py`, `src/request_middleware.py`
  - Session-scoped state: `src/core/domain/session.py`, `src/core/services/session_enricher.py`, `src/core/services/session_manager_service.py`
  - Backend orchestration and multi-attempt flows: `src/core/services/backend_completion_flow/service.py`, `src/core/services/backend_completion_flow/completion_session_resolver.py`
  - Connector dispatch: `src/core/services/connector_invoker.py`, connectors under `src/connectors/`
  - Wire capture and fallbacks: `src/core/services/cbor_wire_capture_service.py`, `src/core/transport/fastapi/adapters/capture/wire_capture_coordinator.py`, `src/core/services/stream_session_id_resolver.py`
  - Usage tracking persistence: `src/core/domain/usage_record.py`, `src/core/database/models/usage.py`
  - Auth gating: `src/core/app/middleware/sso_middleware_adapter.py`, `src/core/auth/sso/middleware.py`
- **Patterns Identified**:
  - Staged init and DI seams are stable and support introducing new services behind flags.
  - Backend calls are centralized in `BackendCompletionFlow` which is the natural boundary for per-attempt (B-leg) identity allocation.
  - `RequestContext.extensions` exists as the explicitly allowed JSON-safe extension channel for cross-layer data, which can bridge identity propagation during migration.
- **Implications**:
  - The design should introduce a dedicated identity/mapping service and thread A-leg and B-leg identities through existing DI seams rather than continuing to overload the single `session_id`.

### Session Identity Semantics Collisions
- **Context**: Multiple subsystems assume `session_id` is both (1) the key for session-scoped state and (2) a backend-facing correlation identifier.
- **Findings**:
  - `BackendProcessor` loads session state using `session_id` (`src/core/services/backend_processor.py`), implying the “session_id” on that boundary must be the A-leg identifier.
  - Backend completion uses a “session_id_for_backend” value for both per-session backend caches and backend-call kwargs (`src/core/services/backend_completion_flow/service.py`), which must be split into A-leg vs B-leg identifiers.
  - Some components fall back to `request_id` for “session-like” correlation (`src/core/services/stream_session_id_resolver.py`, `src/core/transport/fastapi/adapters/capture/wire_capture_coordinator.py`), which violates the session-vs-request separation requirement.
- **Implications**:
  - The design must make A-leg identity the only key for session-scoped state and ensure B-leg identity is used only for outbound provider session/conversation correlation and per-attempt observability.

### Auth Scope Identity Availability
- **Context**: Requirements scope continuity to (`auth_scope_id`, `client_session_id`) and default multi-user behavior is “resume only with the same bearer token”.
- **Findings**:
  - SSO middleware validates tokens but does not propagate token identity or user identity into `RequestContext` / `request.state` (`src/core/app/middleware/sso_middleware_adapter.py`, `src/core/auth/sso/middleware.py`).
  - The SSO token database yields stable identifiers (`token_id`, `user_id`) once validated; those are suitable sources for `auth_scope_id` in multi-user mode (token-scoped by default).
  - In single-user localhost mode, there is no token; continuity needs an explicit “single implicit scope” representation.
- **Implications**:
  - The design needs an explicit `IAuthScopeResolver` (or equivalent) and a transport integration point (middleware/controller adapter) to inject `auth_scope_id` into RequestContext in a reliable, testable way.

### Concurrency and Atomic B-leg Sequencing
- **Context**: Requirement 2.5 demands atomic per-A-leg sequence allocation even under concurrency and multiple worker processes.
- **Findings**:
  - In-memory counters are not safe under multi-process deployments; atomicity needs a shared coordination mechanism.
  - The project already includes a DB layer (SQLModel/Alembic) and uses SQLite for other features; a persistence-backed counter can provide atomic increments when configured.
- **Implications**:
  - The design should support both in-memory (single-process) and persistent (multi-process-safe) sequence allocation with clear configuration gating and failure modes.

### Wire Capture Schema Evolution
- **Context**: Requirements require capturing `a_session_id` and `b_session_id` distinctly.
- **Findings**:
  - Capture metadata currently supports only a single `session_id` field (`src/core/domain/cbor_capture.py`) and several call sites supply `session_id` from `context.session_id`.
  - `CborWireCaptureService` also falls back to request_id or an internal capture file id when `session_id` is empty (`src/core/services/cbor_wire_capture_service.py`).
- **Implications**:
  - The design should add explicit metadata fields for A-leg and B-leg IDs and remove the “request_id as session fallback” behavior when B2BUA mode is enabled (preserving legacy behavior when disabled).

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Extend existing `session_id` semantics | Reinterpret `session_id` as A-leg everywhere; derive B-leg ad-hoc | Fewer new types | High risk of leakage and subtle drift | Not preferred |
| Dedicated identity service | Introduce explicit identity/mapping service behind DI seam | Clear boundaries, testable | Requires threading identities through orchestrators | Preferred foundation |
| Hybrid staged migration | Add identity service + migrate highest-leverage seams first | Reduces rollout risk | Mixed-model period requires discipline | Recommended approach |

## Design Decisions

### Decision: Treat all client-provided session identifiers as untrusted metadata
- **Context**: Prevent spoofing/session fixation and eliminate identifier leaks.
- **Alternatives Considered**:
  1. Trust `x-session-id` as canonical session key
  2. Treat it as metadata and map to internal A-leg ids
- **Selected Approach**: Store client-provided identifiers as `client_session_id` metadata only; never use them as canonical internal IDs or forward them upstream.
- **Rationale**: Aligns with security requirements and B2BUA isolation.
- **Trade-offs**: Requires continuity mapping store to preserve usability for clients that expect stable sessions.

### Decision: Use `auth_scope_id` for continuity scoping
- **Context**: Multi-user mode must scope continuity to the same bearer token by default; localhost mode has no token.
- **Alternatives Considered**:
  1. User-level scope (`user_id`)
  2. Token-level scope (`token_id`)
  3. Token hash (derived from raw token)
- **Selected Approach**: Default `auth_scope_id` to a stable token identity (`token_id`) when available; represent localhost mode as a single implicit scope.
- **Rationale**: Matches “resume only with same token” default and avoids storing raw tokens.
- **Trade-offs**: Requires explicit context injection since current middleware gates but does not expose identity.

### Decision: Allocate B-legs at the backend-attempt boundary
- **Context**: B-legs must be created per attempt (failover, follow-ups) and have atomically incremented `<seq>`.
- **Alternatives Considered**:
  1. Allocate B-leg once per inbound request
  2. Allocate B-leg per backend attempt inside `BackendCompletionFlow`
- **Selected Approach**: Allocate B-leg within backend-attempt orchestration (inside/adjacent to `BackendCompletionFlow`) so each attempt gets a unique `b_session_id`.
- **Rationale**: Matches existing multi-attempt orchestration and supports accurate mapping and observability.
- **Trade-offs**: Requires threading B-leg identity into connector invocation and capture/usage layers.

### Decision: DI Lifetime Selection
- **Context**: Session identity and mapping are cross-cutting and must be concurrency-safe.
- **Selected Approach**:
  - Identity formatters/allocators: `Singleton` (stateless/pure functions).
  - Mapping store: `Singleton` (shared state / shared DB handle per process).
  - Per-request identity “view”: carried in `RequestContext` and/or request-scoped helper.
- **Rationale**: Aligns with existing DI patterns and avoids per-request recomputation of persistent mapping state.

### Decision: Error Handling Strategy
- **Context**: Failures in mapping/persistence must not leak identifiers and should fail-open safely.
- **Selected Approach**:
  - Introduce domain errors that extend `LLMProxyError` for identity/mapping failures.
  - When mapping store operations fail, create a new A-leg session and continue with degraded continuity (subject to config), emitting diagnostic logs.
- **Rationale**: Preserves availability while keeping security properties.

## Risks & Mitigations
- Risk 1: Identifier leakage through legacy `session_id` paths - Mitigation: Centralize B-leg injection at connector boundary; add explicit “no request_id fallback” rules when B2BUA enabled.
- Risk 2: Atomic `<seq>` allocation breaks under multi-process - Mitigation: Require a shared persistent allocator when multi-worker is enabled; provide clear config and startup validation.
- Risk 3: Schema evolution for captures/usage breaks tooling - Mitigation: Backward-compatible metadata additions and version-aware inspection tooling updates.

## Performance Considerations
- Mapping lookups should be O(1) with TTL and bounded growth.
- Persistent atomic sequencing introduces DB overhead; keep operations minimal (single-row transactional increment) and make persistence optional.
- Wire capture enrichment adds metadata only; payload capture remains byte-precise.

## References
- `src/core/services/backend_completion_flow/service.py` - Multi-attempt orchestration boundary
- `src/core/services/session_enricher.py` - Session-scoped state enrichment boundary
- `src/core/domain/request_context.py` - Cross-layer context contract + extensions container
- `src/core/services/connector_invoker.py` - Canonical connector context projection
- `src/core/services/cbor_wire_capture_service.py` and `src/core/domain/cbor_capture.py` - Capture metadata contract
- `.kiro/specs/b2bua-like-session-handling/requirements.md` - Requirements and EARS constraints
- `.kiro/specs/b2bua-like-session-handling/gap-analysis.md` - Implementation gap findings
