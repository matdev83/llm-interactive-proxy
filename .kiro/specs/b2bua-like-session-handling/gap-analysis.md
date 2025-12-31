# Gap Analysis: B2BUA-like Session Handling

## Executive Summary

The codebase has a mature notion of “session” (`session_id`) that flows through request processing, backend orchestration, usage tracking, and wire capture. However, it is a **single identifier** that is often sourced from client-provided inputs and is frequently propagated into backend-facing request payloads/headers. This is inconsistent with a B2BUA model that requires **strict A-leg/B-leg identity isolation**, per-backend-attempt B-legs, and stable internal mapping for observability and safety.

Key gaps are:
- No explicit A-leg (`a_session_id`) vs B-leg (`b_session_id`) model or mapping store.
- No per-A-leg atomic B-leg sequence allocation.
- Session ID resolution currently treats client inputs as authoritative in multiple paths.
- Several observability components fall back to `request_id` as a “session-like” identifier, violating the requirement that request IDs are not session IDs.
- No existing first-class authenticated token identity is attached to the core request context to scope session resume in multi-user mode.

**Primary evidence (existing assets)**:
- Session resolution: `src/core/services/intelligent_session_resolver.py`, `src/core/services/session_resolver_service.py`, `src/request_middleware.py`
- Session injection into backend requests: `src/core/services/backend_executor.py`
- Backend orchestration and failover: `src/core/services/backend_completion_flow/service.py`, `src/core/services/backend_completion_flow/failure_recovery_executor.py`, `src/core/services/backend_completion_flow/completion_session_resolver.py`
- Wire capture: `src/core/services/backend_completion_flow/wire_capture_orchestrator.py`, `src/core/domain/cbor_capture.py`, `src/core/services/stream_session_id_resolver.py`
- Usage persistence: `src/core/domain/usage_record.py`, `src/core/database/models/usage.py`
- Connector session usage: `src/connectors/openrouter.py`, `src/connectors/_openai_codex_connector.py`, `src/connectors/hybrid_backend/compatibility.py`

**Effort**: XL (architectural cross-cut)  
**Risk**: High (touches request/streaming/capture/usage/connectors; behavior preservation and “no leaks” guarantees require careful migration)

## 1. Current State Investigation

### Key assets already in place

- **Session concept + repository**:
  - Session entity/state is modeled by `src/core/domain/session.py` and stored via `src/core/repositories/in_memory_session_repository.py` (TTL, eviction).
  - Session resolution is an injected seam (`ISessionResolver`) wired during staged init (`src/core/app/stages/core_services.py`).

- **Session resolution implementations (current behavior conflicts with new requirements)**:
  - `IntelligentSessionResolver` prioritizes explicit `x-session-id`/cookie as the resolved session ID and otherwise uses message-fingerprint continuity (`src/core/services/intelligent_session_resolver.py`).
  - `DefaultSessionResolver` also uses `x-session-id`, request/session fields, cookies, and generates UUIDs as fallback (`src/core/services/session_resolver_service.py`).
  - `CustomHeaderMiddleware` copies `x-session-id` into `request.state.session_id` (`src/request_middleware.py`).

- **Thin orchestrators + staged init**:
  - Request flow orchestrator delegates into components (`src/core/services/request_processor_service.py` and internal contracts under `src/core/interfaces/request_processor_internal.py`), which is a good fit for introducing a dedicated identity/mapping collaborator.

- **Backend orchestration supports multi-attempt flows already**:
  - BackendCompletionFlow centralizes retry/failover and delegates to collaborators (`src/core/services/backend_completion_flow/service.py`).
  - Failover planner/executor exists (`src/core/services/backend_completion_flow/failure_recovery_executor.py`), but there is no per-attempt identity concept today.

- **Observability foundations exist**:
  - Traffic legs are already modeled (CTP/PTB/BTP/PTC) (`src/core/domain/traffic_leg.py`).
  - CBOR capture metadata supports a single `session_id` and `request_id` (`src/core/domain/cbor_capture.py`).

### Active hotspots relative to the requirements

- **Single “session_id” is used end-to-end and is injected into backend requests**:
  - `BackendExecutor` explicitly injects the resolved `session_id` into outbound `ChatRequest.session_id` and `extra_body["session_id"]` before backend execution (`src/core/services/backend_executor.py`).
  - Multiple connectors read `request.session_id` for tracking and/or backend conversation/session headers (e.g., `src/connectors/openrouter.py`, `src/connectors/_openai_codex_connector.py`).

- **BackendCompletionFlow uses the same identifier for multiple purposes**:
  - `CompletionSessionResolver` returns `session_id_for_backend` from `context.session_id` or `request.extra_body["session_id"]` (`src/core/services/backend_completion_flow/completion_session_resolver.py`).
  - That same ID is used for:
    - per-session backend instance caching (`BackendLifecycleManager.get_or_create(..., session_id=...)` via `BackendManager.acquire_backend`) (`src/core/services/backend_lifecycle_manager.py`, `src/core/services/backend_completion_flow/backend_manager.py`)
    - non-forwardable enforcement scoping and logging (`src/core/services/backend_completion_flow/service.py`)
    - usage recording session attribution (`src/core/services/backend_completion_flow/usage_accounting_orchestrator.py`)

- **Request ID is treated as a “session-like” fallback in capture/streaming paths**:
  - `StreamSessionIdResolver` falls back to `context.request_id` then UUID (`src/core/services/stream_session_id_resolver.py`).
  - Wire capture session resolution can fall back to `request_id` (`src/core/transport/fastapi/adapters/capture/wire_capture_coordinator.py`).
  - CBOR capture writer code also uses `request_id` as a “resolved_session” fallback in some paths (`src/core/services/cbor_wire_capture_service.py`).

- **No auth-token identity scope is currently available in `RequestContext`**:
  - `RequestContext` has `client_host` and `agent`, but there is no first-class field representing the validated bearer token identity that could be used to scope session continuity mappings (`src/core/domain/request_context.py`).
  - SSO middleware validates authentication but does not attach an identity object to request context (`src/core/app/middleware/sso_middleware_adapter.py`, `src/core/auth/sso/middleware.py`).

- **Some code already acknowledges “session_id inheritance” risk**:
  - Hybrid connector compatibility code strips `session_id` from `extra_body` to prevent session backend inheritance (`src/connectors/hybrid_backend/compatibility.py`), suggesting this problem has been encountered in practice.

## 2. Requirement-to-Asset Map (with Gaps)

Legend: **Present** / **Missing** / **Constraint** (present but insufficient) / **Unknown** (requires research)

| Requirement Area | Existing Assets | Status | Gap Notes |
|---|---|---:|---|
| R1: A-leg/B-leg identity model + mapping | `RequestContext.session_id` (`src/core/domain/request_context.py`), session repo (`src/core/repositories/in_memory_session_repository.py`), request orchestrators | Constraint | Only a single `session_id` exists; no explicit `a_session_id`/`b_session_id`, no mapping store. |
| R2: ID formats + atomic B-leg sequence | UUID generation in resolvers; no sequence allocator | Missing | No `llm-b2bua-*` formatting, no per-A-leg atomic `<seq>` allocation, no concurrency-safe B-leg issuance. |
| R3: Client IDs as untrusted metadata + ignore inbound `x-b2bua-session-id` | Header/session extraction in resolvers (`src/core/services/intelligent_session_resolver.py`, `src/core/services/session_resolver_service.py`) | Constraint | Current resolvers treat `x-session-id` and body `session_id` as authoritative session identity; no concept of `client_session_id` as metadata; no dedicated ignore rule for inbound `x-b2bua-session-id`. |
| R4: Auth-scope-scoped session resume with TTL + optional persistence | In-memory session TTL + client-key tracking (`src/core/repositories/in_memory_session_repository.py`), fingerprint continuity (`src/core/services/intelligent_session_resolver.py`) | Constraint / Unknown | Continuity is based on client_key (IP/user-agent) + message fingerprints, not (`auth_scope_id`, `client_session_id`). Auth scope identity is not currently attached to `RequestContext`; persistence would require new DB table(s) or reuse of existing DB infrastructure. |
| R5: Per-attempt B-leg tracking across failover/follow-ups | Failover planner/executor (`src/core/services/backend_completion_flow/failure_recovery_executor.py`), BackendCompletionFlow multi-attempt loops | Constraint | Multiple backend attempts exist, but they reuse a single `session_id_for_backend` and have no per-attempt identity record. |
| R6: Backend identifier isolation (no leaks) | Connector layer (`src/connectors/`), backend execution (`src/core/services/backend_executor.py`) | Constraint | Current system injects `session_id` into outbound request objects and many connectors use it; isolation requires systematic changes across orchestrators + connectors. |
| R7: Echo header + logs/captures/usage attribution without request_id fallback | Wire capture system (`src/core/services/*wire_capture*`, `src/core/domain/cbor_capture.py`), usage tables (`src/core/database/models/usage.py`) | Constraint | No echo header today; capture/streaming sometimes fall back to `request_id`; capture/usage schemas store only one `session_id` value, so they cannot represent both A-leg and B-leg identifiers. |
| NFRs: perf/reliability/security | Existing async architecture + DI; CBOR captures; best-effort capture wrappers | Constraint | Correct atomic sequencing and cross-worker correctness (multi-process) is not currently addressed; “fail-open safely” needs explicit policy for mapping store failures and persistence choices. |

## 3. Implementation Approach Options

### Option A: Extend existing “session_id everywhere” semantics (rename + thread new fields)

**Description**: Reinterpret the existing `session_id` flow to mean internal `a_session_id`, introduce `client_session_id` as explicit metadata, and add `b_session_id` generation at backend-attempt boundaries. Update connectors and capture/usage to use the new identities.

**Likely touch points**:
- Session resolver(s): `src/core/services/intelligent_session_resolver.py`, `src/core/services/session_resolver_service.py`
- Request pipeline: `src/core/services/request_processor_service.py`, `src/core/services/backend_executor.py`
- BackendCompletionFlow: `src/core/services/backend_completion_flow/service.py` (+ failover executor)
- Wire capture + streaming session-id resolution: `src/core/services/stream_session_id_resolver.py`, `src/core/services/*wire_capture*`, `src/core/domain/cbor_capture.py`
- Usage + DB schema: `src/core/domain/usage_record.py`, `src/core/database/models/usage.py`
- Connectors: any connector reading/setting provider session/conversation IDs

**Pros**:
- Fewer parallel identity concepts; aligns most call sites around one internal A-leg identifier.
- Uses existing seams (DI, staged init, orchestrator delegation) for integration.

**Cons**:
- High risk of breaking assumptions: many parts of the code and clients treat `session_id` as “client session”.
- Requires wide refactor across connectors and observability surfaces; difficult to stage safely without a compatibility layer.

### Option B: Introduce a dedicated B2BUA “Session Identity” service (new component) and keep legacy `session_id` as client metadata

**Description**: Add a new service that resolves/creates `a_session_id`, stores `client_session_id` metadata, allocates `b_session_id` per backend attempt, and maintains the A→B mapping. Thread these identities through the request/response flow using typed additions to `RequestContext` (preferred) or `RequestContext.extensions` (as a compatibility bridge).

**Integration points**:
- Ingress controllers establish `a_session_id` for the request and optionally echo it via `x-b2bua-session-id`.
- Backend-attempt boundary allocates `b_session_id` and passes it to connectors for provider session/conversation fields.
- Capture/usage layers consume both IDs from context.

**Pros**:
- Keeps “untrusted client identifiers” clearly separated from internal identifiers.
- Enables a staged rollout: identity service can be introduced behind a config flag without rewriting every call site immediately.

**Cons**:
- More plumbing work to thread new IDs through orchestrators and adapters.
- Risk of dual-path drift if legacy `session_id` continues to be used implicitly by connectors or capture code.

### Option C: Hybrid (introduce identity service + targeted migration of the highest-leverage seams first)

**Description**: Implement the identity/mapping service (Option B core) and migrate the highest-leverage seams first: backend-attempt boundaries, connector conversation/session injection points, capture metadata, and usage attribution. Keep legacy behaviors behind compatibility flags until fully migrated.

**Pros**:
- De-risks the change by letting you lock “no leaks” guarantees first at the connector boundary.
- Allows gradual refactoring of “request_id as session fallback” behavior with clear compatibility notes.

**Cons**:
- Requires disciplined scoping and an explicit migration plan to avoid a long-lived mixed model.

## 4. Implementation Complexity & Risk

- **Effort: XL (2+ weeks)** — Requires introducing a new identity/mapping abstraction and modifying multiple cross-cutting flows: request processing, backend orchestration (including failover), connector session propagation, wire capture schemas, and usage persistence (likely DB migration if B-leg attribution is persisted).
- **Risk: High** — Session identity is a core axis for correctness, observability, and security. Mistakes can cause identifier leaks, mis-attribution of usage/captures, and behavioral regressions in streaming/failover scenarios.

## 5. Recommendations for the Design Phase (Information, not final decisions)

### Likely preferred direction

- **Option C (Hybrid)** is the most practical: introduce an explicit identity/mapping service and migrate the most sensitive seams first (connector boundary + backend-attempt creation + capture metadata), then broaden coverage.

### Research Needed (carry into design)

1. **Auth scope identity source**: define how a stable `auth_scope_id` is derived from validated bearer tokens in multi-user mode (and how localhost mode is represented), and how it is injected into `RequestContext` for session continuity and mapping.
2. **Multi-process correctness**: decide whether the proxy runs with multiple workers; if so, “atomic B-leg sequence allocation” cannot rely solely on in-memory counters and may require a shared store (DB/redis) or a different sequencing strategy.
3. **Resolver strategy reconciliation**: decide what happens to `IntelligentSessionResolver` fingerprint-based continuity (keep, disable in B2BUA mode, or repurpose as a heuristic for selecting/creating internal A-leg IDs without trusting client IDs).
4. **Connector inventory**: enumerate which connectors use `session_id`/conversation identifiers and define a consistent contract for passing `b_session_id` without leaking `a_session_id` or `client_session_id`.
5. **Capture schema evolution**: plan CBOR capture metadata changes to include both A-leg and B-leg IDs while preserving backward compatibility for existing capture files and tooling (`scripts/inspect_cbor_capture.py`).
6. **Usage schema evolution**: decide how to attribute usage to `a_session_id` while recording per-attempt B-leg metadata (new columns vs new table vs embedding in metadata), including migration strategy for existing DB data.
7. **“Request ID vs Session ID” naming**: reconcile existing `SessionKey` naming/usage (currently built from `request_id` for cancellation/EoS scoping in `src/core/transport/session_key_resolver.py`) with the new explicit A/B session identity model to reduce conceptual confusion.
8. **Echo header behavior**: decide where to implement `x-b2bua-session-id` (controller vs middleware), streaming behavior, and default config surface and precedence.
9. **Fail-open policy**: define what happens when mapping store operations fail (e.g., create new A-leg, create B-leg without mapping, suppress echo header) and what diagnostics are emitted.
