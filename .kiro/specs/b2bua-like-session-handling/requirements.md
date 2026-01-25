# Requirements Document

## Introduction
This specification defines **B2BUA-like session handling** for the **LLM Proxy**.

The LLM Proxy acts as a back-to-back user agent between clients and upstream LLM
providers: it terminates inbound requests, applies transformations and policy,
and initiates new outbound requests. To support this safely and predictably,
the LLM Proxy needs explicit **A-leg** (client-facing) and **B-leg**
(backend-facing) session identity separation with mapping and observability.

This spec makes a strict distinction between:
- **Session IDs**: logical, chat-completion session identity (may span multiple requests)
- **Request IDs**: per-request correlation identifiers (never used as session identity)

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Developers integrating LLM capabilities via unified API
- Operators managing backend configurations and monitoring
- End-users consuming LLM responses through client applications
- Security reviewers validating anti-spoofing and identifier isolation properties

## Discovered Constraints (from Gap Analysis)
- The current codebase uses a single `session_id` across request processing, backend orchestration, usage tracking, and wire capture, and it is frequently sourced from client inputs (for example, `x-session-id`).
- Some parts of the observability stack currently fall back to `request_id` as a session-like identifier; this must be eliminated for B2BUA session handling.
- The current backend execution path injects `session_id` into outbound request objects; this must not cause A-leg or client identifier leaks to backends.
- There is no existing first-class identity scope in the request context contract suitable for scoping session continuity; session resume behavior requires a defined `auth_scope_id` (derived from the validated bearer token record identity, i.e. `token_id`, in multi-user mode, or a fixed implicit scope in single-user localhost mode).

## Requirements

### Requirement 1: A-leg / B-leg Session Identity Model
**Objective:** As an operator, I want the proxy to model A-leg and B-leg sessions explicitly, so that identifiers are isolated and backend attempts are attributable.

**Priority:** P0 (Critical)

#### Acceptance Criteria
- 1.1 The LLM Proxy shall assign an internal A-leg session identifier (`a_session_id`) for each logical chat-completion session it processes.
- 1.2 The LLM Proxy shall assign a distinct internal B-leg session identifier (`b_session_id`) for each outbound backend attempt performed on behalf of an A-leg session.
- 1.3 When the LLM Proxy performs multiple outbound backend attempts for the same A-leg session (for example, failover attempts or proxy-initiated follow-up calls), the LLM Proxy shall associate each B-leg with the same A-leg session.
- 1.4 The LLM Proxy shall support zero, one, or many B-legs per A-leg session.
- 1.5 When the LLM Proxy does not invoke any backend for an inbound request (for example, command-only flows), the LLM Proxy shall not create a B-leg for that request.
- 1.6 The LLM Proxy shall maintain an internal mapping from each `a_session_id` to the set of all `b_session_id` values created for that A-leg session.
- 1.7 The LLM Proxy shall maintain request identifiers (`request_id`) as a concept distinct from session identifiers (`a_session_id` / `b_session_id`).
- 1.8 The LLM Proxy shall not derive `a_session_id` or `b_session_id` from `request_id`.

#### Technical Constraints
- Async compatibility: Session identity operations shall be compatible with `async/await` request processing.
- DI integration: Session identity and mapping behavior shall be exposed via DI-managed services.
- Error hierarchy: Errors in session identity/mapping shall be represented as `LLMProxyError` subclasses where surfaced.
- Config precedence: Configuration controlling this feature shall follow CLI > ENV > YAML precedence.

### Requirement 2: Internal Identifier Formats and Generation
**Objective:** As a developer, I want stable, recognizable internal session identifier formats, so that debugging and correlation are straightforward without leaking client identifiers.

**Priority:** P0 (Critical)

#### Acceptance Criteria
- 2.1 The LLM Proxy shall generate internal A-leg session identifiers in the form `llm-b2bua-<a-uuid>`.
- 2.2 The LLM Proxy shall generate internal B-leg session identifiers in the form `llm-b2bua-b-<a-uuid>-<seq>`.
- 2.3 When generating a B-leg session identifier, the LLM Proxy shall set `<a-uuid>` to the A-leg UUID component for the associated `a_session_id`.
- 2.4 When generating B-leg session identifiers for a given A-leg session, the LLM Proxy shall allocate `<seq>` values as monotonically increasing positive integers starting at 1.
- 2.5 When multiple B-legs are created concurrently for the same A-leg session, the LLM Proxy shall allocate `<seq>` values atomically such that no two B-legs for the same A-leg share the same sequence number, including when requests are handled by multiple worker processes.
- 2.6 The LLM Proxy shall ensure that generated `a_session_id` and `b_session_id` values are non-empty and safe to include in HTTP headers and structured logs.
- 2.7 The LLM Proxy shall preserve the last allocated `<seq>` value for an A-leg session for at least as long as the A-leg session mapping remains active.
- 2.8 Where persistent mapping storage is enabled, the LLM Proxy shall persist the last allocated `<seq>` value such that subsequent B-legs for a resumed A-leg session continue with a higher sequence number.

#### Technical Constraints
- Identifier generation shall not require network access.
- Identifier generation shall be concurrency-safe under async request handling.

### Requirement 3: Client-Provided Session Identifiers as Untrusted Metadata
**Objective:** As a security reviewer, I want client-provided identifiers treated as untrusted metadata, so that spoofing and session fixation risks are mitigated.

**Priority:** P0 (Critical)

#### Acceptance Criteria
- 3.1 When an inbound request contains a client-provided session identifier, the LLM Proxy shall store it as `client_session_id` metadata and shall not treat it as the canonical internal session identifier.
- 3.2 The LLM Proxy shall not derive `a_session_id` or `b_session_id` from `client_session_id`.
- 3.3 The LLM Proxy shall not forward `client_session_id` to any backend provider as a session/conversation identifier.
- 3.4 The LLM Proxy shall ignore any inbound `x-b2bua-session-id` header (or configured A-leg echo header name) for purposes of session identity, mapping, routing, failover, cancellation, and accounting.
- 3.5 When a request includes multiple candidate client session identifiers, the LLM Proxy shall select the `client_session_id` using the following precedence order: `x-session-id` header, then request body `session_id`, then `extra_body.session_id`.
- 3.6 If multiple candidate client session identifiers are present and they differ, the LLM Proxy shall record a diagnostic signal that a conflict occurred.
- 3.7 If a candidate client session identifier is empty after trimming, the LLM Proxy shall treat it as absent.
- 3.8 When B2BUA-like session handling is enabled for HTTP transports and no client session identifier is present, the LLM Proxy shall be able to mint a proxy-generated `client_session_id` and return it to the client using a cookie (see Requirement 4.11).
- 3.9 The LLM Proxy shall treat a proxy-generated `client_session_id` cookie value as untrusted input on subsequent requests (subject to normal trimming/sanitization), but may use it for continuity mapping when combined with `auth_scope_id`.

#### Technical Constraints
- Client-provided identifiers shall be treated as untrusted input and validated/sanitized before logging.

### Requirement 4: Session Continuity and Resume (Auth-Scope-Scoped)
**Objective:** As an end-user, I want to resume a logical chat session within the same authentication scope (bearer token in multi-user mode, or localhost mode), so that long-running sessions can continue safely across time.

**Priority:** P1 (High)

#### Acceptance Criteria
- 4.1 When `client_session_id` is present and an `auth_scope_id` is available for the request, the LLM Proxy shall scope session continuity to the pair (`auth_scope_id`, `client_session_id`).
- 4.2 When an inbound request arrives with (`auth_scope_id`, `client_session_id`) matching an existing active mapping, the LLM Proxy shall reuse the previously assigned internal `a_session_id`.
- 4.3 If an inbound request arrives with the same `client_session_id` but a different `auth_scope_id`, the LLM Proxy shall not reuse the existing `a_session_id` and shall assign a new `a_session_id`.
- 4.4 Where the LLM Proxy is configured for single-user localhost mode and no bearer token is available, the LLM Proxy shall treat all accepted requests as belonging to a single implicit `auth_scope_id` for the purpose of continuity.
- 4.5 The LLM Proxy shall apply a configurable time-based expiration policy to the mapping from (`auth_scope_id`, `client_session_id`) to `a_session_id`.
- 4.6 When the mapping expires, the LLM Proxy shall assign a new `a_session_id` for subsequent requests with the same (`auth_scope_id`, `client_session_id`).
- 4.7 While a mapping remains active, the LLM Proxy shall extend the mapping’s expiration based on observed activity (sliding expiration).
- 4.8 Where persistent mapping storage is enabled, the LLM Proxy shall preserve continuity mappings across process restarts.
- 4.9 If `client_session_id` is absent, the LLM Proxy shall assign a new internal `a_session_id` and shall not infer session continuity from request message contents unless explicitly configured.
- 4.10 If `client_session_id` is present but `auth_scope_id` is not available and the LLM Proxy is not configured for single-user localhost mode, the LLM Proxy shall not reuse continuity mappings and shall assign a new `a_session_id`.

#### Technical Constraints
- The mapping store shall enforce bounded growth (time-based expiration and capacity controls).

### Requirement 5: Backend Attempt Tracking and B-leg Mapping
**Objective:** As an operator, I want each backend attempt to have its own B-leg identity, so that failover and proxy-initiated follow-ups are traceable.

**Priority:** P0 (Critical)

#### Acceptance Criteria
- 5.1 When the LLM Proxy initiates an outbound backend attempt for an A-leg session, the LLM Proxy shall create a new `b_session_id` for that attempt.
- 5.2 When the LLM Proxy performs failover for a request, the LLM Proxy shall create a new B-leg for each backend attempt.
- 5.3 When the LLM Proxy performs proxy-initiated follow-up backend calls for the same A-leg session, the LLM Proxy shall create a new B-leg for each follow-up call.
- 5.4 The LLM Proxy shall record, for each B-leg, at minimum: `b_session_id`, associated `a_session_id`, backend type, effective model, and an attempt reason.
- 5.5 When a backend attempt fails, the LLM Proxy shall retain the B-leg mapping record for diagnostic purposes until it expires per the configured policy.
- 5.6 Where the LLM Proxy scopes internal per-session state (for example, backend instance caches or enforcement registries), the LLM Proxy shall scope that state using `a_session_id` and not using any client-provided session identifier.

#### Technical Constraints
- Mapping updates shall be atomic with respect to B-leg sequence allocation for a single A-leg.

### Requirement 6: Backend Identifier Isolation (No Leaks)
**Objective:** As a security reviewer, I want strict identifier isolation between client-facing and backend-facing legs, so that identifiers never leak across trust boundaries.

**Priority:** P0 (Critical)

#### Acceptance Criteria
- 6.1 When invoking any backend provider, the LLM Proxy shall not include the internal `a_session_id` in outbound backend requests.
- 6.2 When invoking any backend provider, the LLM Proxy shall not include any `client_session_id` in outbound backend requests.
- 6.3 When a backend provider supports a session/conversation identifier field or header for correlation, the LLM Proxy shall use the internal `b_session_id` (or a value derived from it) rather than any client-provided identifier.
- 6.4 If a backend connector receives a request object that contains client-provided session identifiers, the LLM Proxy shall ensure those identifiers do not propagate into backend provider session/conversation fields.
- 6.5 When the LLM Proxy populates request fields intended for backend session/conversation correlation (for example, `session_id` fields in request payloads or metadata), the LLM Proxy shall populate them using `b_session_id` (or a value derived from it) and not using `a_session_id` or `client_session_id`.

#### Technical Constraints
- Connector integrations shall remain compatible with multi-backend routing and failover orchestration.

### Requirement 7: Diagnostics and Observability (Echo + Captures)
**Objective:** As a developer, I want to correlate observed behavior across proxy and backend legs, so that troubleshooting is fast and reliable.

**Priority:** P1 (High)

#### Acceptance Criteria
- 7.1 Where A-leg session echo is enabled, when the LLM Proxy returns an HTTP response, the LLM Proxy shall include a response header named by configuration (default `x-b2bua-session-id`) whose value equals the internal A-leg session identifier for that request.
- 7.2 Where A-leg session echo is disabled, when the LLM Proxy returns an HTTP response, the LLM Proxy shall not include the configured A-leg echo response header.
- 7.3 Where A-leg session echo is enabled, when the LLM Proxy returns a streaming HTTP response, the LLM Proxy shall include the same configured A-leg echo response header value for the lifetime of the stream.
- 7.4 When the LLM Proxy performs an outbound backend attempt, the LLM Proxy shall emit structured logs that include both `a_session_id` and `b_session_id`.
- 7.5 Where wire capture is enabled, the LLM Proxy shall record `a_session_id` and `b_session_id` in capture metadata such that captures can be correlated across legs and across multiple backend attempts.
- 7.6 Where usage tracking is enabled, the LLM Proxy shall attribute usage metrics to `a_session_id` and shall record sufficient per-attempt metadata to distinguish multiple B-legs under one A-leg.
- 7.7 The LLM Proxy shall not use `request_id` as a substitute for `a_session_id` or `b_session_id` in observability outputs.
- 7.8 Where wire capture is enabled, the LLM Proxy shall record A-leg and B-leg session identifiers as distinct metadata values (and not as a single combined identifier).
- 7.9 If `a_session_id` or `b_session_id` cannot be resolved for an observability event due to an internal error, the LLM Proxy shall omit that identifier rather than substituting `request_id`.
- 7.10 Where usage tracking persists records for backend-attempt traffic legs, the LLM Proxy shall record `b_session_id` (or its `<seq>` component) with those records to distinguish multiple backend attempts under one A-leg session.

#### Technical Constraints
- Capture and log metadata fields shall be JSON-serializable.
- Wire capture shall remain byte-precise for payloads while permitting enriched metadata for correlation.

### Requirement 8: Configuration and Compatibility Controls
**Objective:** As an operator, I want to control rollout of B2BUA session handling, so that behavior changes can be enabled intentionally and diagnosed safely.

**Priority:** P1 (High)

#### Acceptance Criteria
- 8.1 The LLM Proxy shall provide configuration to enable or disable B2BUA-like session handling.
- 8.2 Where B2BUA-like session handling is enabled, the LLM Proxy shall apply the session identity and isolation requirements in this specification.
- 8.3 Where B2BUA-like session handling is disabled, the LLM Proxy shall not enforce A-leg/B-leg session identity separation requirements defined in this specification.
- 8.4 The LLM Proxy shall provide configuration for session continuity mapping expiration, including whether expiration is sliding and the maximum age.
- 8.5 The LLM Proxy shall provide configuration to enable or disable persistent continuity mapping storage across process restarts.
- 8.6 The LLM Proxy shall provide configuration to enable or disable A-leg session echo to clients.
- 8.7 The LLM Proxy shall provide configuration to set the A-leg echo response header name, with default value `x-b2bua-session-id`.
- 8.8 The LLM Proxy shall provide configuration to enable/disable proxy-issued `client_session_id` cookies (HTTP only), and configure the cookie name and security attributes (Secure/SameSite/Max-Age).

### Requirement 9: Session-Scoped State Consistency Across Legs
**Objective:** As a developer, I want session-scoped variables to be set/read/updated reliably across A-leg and B-leg activity, so that session behavior is stable regardless of backend attempts and proxy-internal follow-ups.

**Priority:** P0 (Critical)

#### Acceptance Criteria
- 9.1 The LLM Proxy shall maintain session-scoped state keyed by `a_session_id`.
- 9.2 When processing an inbound client request, the LLM Proxy shall read and update session-scoped state using the resolved `a_session_id`.
- 9.3 When processing an outbound backend attempt (including failover attempts), the LLM Proxy shall read and update session-scoped state using the associated `a_session_id`, regardless of the `b_session_id` used for backend session/conversation correlation.
- 9.4 When the LLM Proxy performs proxy-initiated follow-up backend calls for the same logical session, the LLM Proxy shall preserve and reuse the same session-scoped state associated with the `a_session_id`.
- 9.5 The LLM Proxy shall support session-scoped variables that include, at minimum: authenticated user identifier (when available), current project root folder selection (when applicable), and user language preference (when configured).
- 9.6 The LLM Proxy shall ensure that session-scoped state is not inadvertently partitioned by B-leg identity such that the same A-leg session behaves inconsistently across backend attempts.
- 9.7 The LLM Proxy shall not use `request_id` as a key for session-scoped state.

#### Technical Constraints
- Session-scoped state shall be accessible from DI-managed services participating in request processing and backend orchestration.
- Session-scoped state updates shall be safe under concurrent requests for the same `a_session_id`.

## Non-Functional Requirements

### Requirement 10: Performance
**Objective:** As an operator, I want session identity handling to add minimal overhead, so that the proxy remains responsive under load.

**Priority:** P2 (Medium)

#### Acceptance Criteria
- 10.1 The LLM Proxy shall resolve internal session identity and allocate B-leg sequence numbers using local computation and configured storage only.
- 10.2 When session mapping is enabled, the LLM Proxy shall ensure mapping operations are bounded and do not grow unbounded with time or traffic.

### Requirement 11: Reliability
**Objective:** As an operator, I want session identity and mapping to behave correctly under failures and concurrency, so that sessions remain consistent.

**Priority:** P1 (High)

#### Acceptance Criteria
- 11.1 The LLM Proxy shall ensure B-leg sequence allocation is correct under concurrent backend attempt creation.
- 11.2 Where the LLM Proxy is deployed with multiple worker processes and B-legs for the same A-leg can be created concurrently, the LLM Proxy shall preserve B-leg sequence allocation correctness.
- 11.3 If the session mapping store encounters an internal error, the LLM Proxy shall fail open where safe (for example, by creating a new A-leg session) and shall emit a diagnostic error signal.

### Requirement 12: Observability
**Objective:** As an operator, I want sufficient session identity metadata for troubleshooting, so that multi-attempt flows can be reconstructed.

**Priority:** P1 (High)

#### Acceptance Criteria
- 12.1 The LLM Proxy shall provide enough metadata in logs/captures to reconstruct an A-leg’s set of backend attempts.
- 12.2 The LLM Proxy shall support configuration to enable/disable A-leg session echo independently of wire capture and logging verbosity.

### Requirement 13: Security
**Objective:** As a security reviewer, I want identifier handling to be resistant to spoofing/session fixation and to preserve A-leg/B-leg isolation, so that trust boundaries are protected.

**Priority:** P0 (Critical)

#### Acceptance Criteria
- 13.1 The LLM Proxy shall treat all client-provided session identifiers as untrusted input and shall not accept them as canonical session identity.
- 13.2 The LLM Proxy shall not allow inbound `x-b2bua-session-id` to influence behavior.
- 13.3 The LLM Proxy shall ensure that identifier isolation is preserved across routing, failover, and proxy-internal follow-up calls.

## Glossary
| Term | Definition |
|------|------------|
| A-leg | Client-facing logical session leg managed by the LLM Proxy. |
| B-leg | Backend-facing attempt leg created by the LLM Proxy for an outbound provider call. |
| `a_session_id` | Internal A-leg session identifier generated by the LLM Proxy (format `llm-b2bua-<a-uuid>`). |
| `b_session_id` | Internal B-leg session identifier generated by the LLM Proxy per backend attempt (format `llm-b2bua-b-<a-uuid>-<seq>`). |
| `client_session_id` | Any client-provided session identifier accepted as untrusted metadata only (never canonical, never forwarded upstream). |
| `request_id` | Per-request correlation identifier distinct from session identity. |
| `auth_scope_id` | An identifier representing the caller’s authentication scope used for session continuity mapping: derived from the validated bearer token record identity (`token_id`) in multi-user mode, or a single implicit scope in single-user localhost mode. Users may have multiple bearer tokens; by default continuity is token-scoped (the raw token value is never used as an identifier). |
