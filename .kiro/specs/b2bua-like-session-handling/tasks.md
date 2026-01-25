# Implementation Plan

- [ ] 1. Foundations: configuration, identifiers, and request context
- [ ] 1.1 Add B2BUA configuration surface and startup validation
  - Add a feature flag to enable/disable B2BUA-like session handling.
  - Add configuration for continuity mapping expiration, including sliding vs fixed expiration and maximum age.
  - Add configuration for enabling/disabling persistent continuity mapping across restarts.
  - Add configuration for enabling/disabling A-leg session echo and for setting the echo header name (default `x-b2bua-session-id`).
  - Add configuration for deployment mode expectations and enforce “multi-worker requires persistent mapping store” at startup when applicable.
  - Ensure the configuration participates in the established CLI > ENV > YAML precedence model.
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 11.2, 12.2_

- [ ] 1.2 (P) Add a proxy-internal identity carrier to support A-leg/B-leg separation
  - Introduce a request-scoped, proxy-internal identity container that can carry `a_session_id`, `b_session_id`, `b_seq`, `auth_scope_id`, and `client_session_id`.
  - Ensure the A-leg identity remains stable for the lifetime of request processing and is suitable as the key for session-scoped state.
  - Ensure per-attempt B-leg identity can be represented without mutating the shared A-leg identity.
  - Ensure any connector-facing projection uses only connector-safe identity metadata and never includes `client_session_id`.
  - _Requirements: 1.1, 1.2, 6.4, 13.3_

- [ ] 1.3 (P) Implement internal A-leg/B-leg identifier generation helpers
  - Generate internal A-leg session identifiers in the form `llm-b2bua-<a-uuid>`.
  - Generate internal B-leg session identifiers in the form `llm-b2bua-b-<a-uuid>-<seq>`.
  - Ensure generated identifiers are non-empty and safe for HTTP headers and structured logs.
  - Ensure identifier generation is local-only (no network access) and safe under async concurrency.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 10.1_

- [ ] 2. Auth scope and client session inputs
- [ ] 2.1 Expose authenticated token identity to core request processing
  - Extend the authentication path so a validated request can provide a stable token identity and user identity to downstream services.
  - Ensure raw bearer token values are never stored or used as internal identifiers.
  - Define localhost behavior as a single implicit authentication scope for accepted requests.
  - _Requirements: 4.1, 4.4, 9.5_

- [ ] 2.2 Implement `auth_scope_id` derivation and continuity scoping rules
  - Derive `auth_scope_id` from the validated bearer token record identity in multi-user mode.
  - Ensure the same `client_session_id` with a different `auth_scope_id` cannot resume the same A-leg session.
  - Ensure missing `auth_scope_id` in non-localhost mode disables continuity reuse and results in a new A-leg session.
  - _Requirements: 4.1, 4.3, 4.4, 4.10_

- [ ] 2.3 (P) Implement client session identifier extraction as untrusted metadata
  - Accept client session inputs from the defined precedence order and store them only as `client_session_id` metadata.
  - Ignore any inbound `x-b2bua-session-id` (and any configured echo header name) for all identity, mapping, routing, failover, cancellation, and accounting decisions.
  - Record a diagnostic signal when multiple candidate client session identifiers are present and differ.
  - Treat empty/whitespace-only identifiers as absent.
  - _Requirements: 3.1, 3.2, 3.4, 3.5, 3.6, 3.7, 13.1, 13.2_


- [ ] 2.4 (P) Implement proxy-issued `client_session_id` cookie for HTTP clients (no client config required)
  - When `client_session_id` is absent on inbound HTTP requests, mint an opaque random token and return it via `Set-Cookie`.
  - Add configuration for enabling/disabling cookie issuance, cookie name, Max-Age, SameSite, and Secure behavior.
  - Ensure cookie values are treated as untrusted input when received (trim/sanitize) and are never derived from internal ids.
  - Ensure inbound `x-b2bua-session-id` is still ignored for identity decisions.
  - _Requirements: 3.8, 3.9, 4.11, 4.12, 4.13, 4.14, 8.8_

- [ ] 3. Continuity mapping and expiration
- [ ] 3.1 Implement in-memory continuity mapping store with TTL, sliding expiration, and bounded growth
  - Map (`auth_scope_id`, `client_session_id`) to a proxy-generated `a_session_id`.
  - Reuse `a_session_id` while mapping remains active and create a new one after expiration.
  - Extend expiration based on observed activity while a mapping is active (sliding expiration).
  - Enforce bounded growth through expiration and capacity controls.
  - Fail open on internal store errors by creating a new A-leg session and emitting a diagnostic error signal.
  - _Requirements: 4.1, 4.2, 4.5, 4.6, 4.7, 10.2, 11.3_

- [ ] 3.2 Implement optional persistence for continuity mapping across restarts
  - Persist continuity mappings across process restarts when enabled.
  - Persist the last allocated B-leg sequence number so resumed A-leg sessions continue allocating higher sequence numbers.
  - Ensure persisted mappings still respect expiration policy and bounded growth constraints.
  - _Requirements: 2.8, 4.8, 8.5_

- [ ] 4. B-leg sequencing and attempt tracking
- [ ] 4.1 Implement multi-worker safe atomic sequence allocation in persistent mode
  - Allocate B-leg `<seq>` values atomically so concurrent workers cannot allocate the same sequence number for a single A-leg.
  - Enforce startup validation that multi-worker deployments require a persistent mapping store.
  - _Requirements: 2.5, 11.1, 11.2_

- [ ] 4.2 Implement B-leg allocation per backend attempt using atomic per-A-leg sequencing
  - Allocate `<seq>` values as monotonically increasing integers starting at 1 for each A-leg.
  - Preserve the last allocated `<seq>` value for as long as the A-leg mapping remains active.
  - Create `b_session_id` using the A-leg UUID component and the allocated `<seq>`.
  - Record backend attempt metadata (backend type, effective model, and attempt reason) and retain failed attempts until expiration.
  - _Requirements: 1.2, 1.3, 1.4, 1.6, 2.2, 2.3, 2.4, 2.7, 5.1, 5.2, 5.3, 5.4, 5.5_

- [ ] 5. A-leg session resolution (B2BUA mode)
- [ ] 5.1 Implement B2BUA A-leg session resolution and mapping behavior
  - Resolve or create an internal `a_session_id` and make it the canonical session identity used by core request processing.
  - Assign a new `a_session_id` by default when `client_session_id` is absent.
  - Ensure `request_id` remains distinct from session identity and is never used to derive `a_session_id` or `b_session_id`.
  - Ensure each `a_session_id` maintains a mapping to the set of B-legs created for that session.
  - _Requirements: 1.1, 1.6, 1.7, 1.8, 3.1, 4.1, 4.2, 4.3, 4.9, 4.10_

- [ ] 5.2 Wire B2BUA session handling behind the feature flag and preserve legacy behavior when disabled
  - Select between legacy session handling and B2BUA session handling based on configuration.
  - Ensure disabling B2BUA does not enforce A-leg/B-leg separation and preserves existing externally observable behavior.
  - _Requirements: 8.1, 8.2, 8.3_

- [ ] 5.3 Ensure session-scoped state is consistent across A-leg and B-leg activity
  - Key session-scoped state by `a_session_id` for both inbound request processing and outbound backend attempts.
  - Ensure proxy-initiated follow-up calls reuse the same session-scoped state for the same `a_session_id`.
  - Ensure session-scoped variables can be set/read/updated reliably, including authenticated user identifier, project root folder selection, and user language preference.
  - Ensure session-scoped state is not inadvertently partitioned by B-leg identity.
  - _Requirements: 5.6, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

- [ ] 6. Backend attempt integration and identifier isolation
- [ ] 6.1 Allocate a new B-leg for each outbound backend attempt (including failover and follow-ups)
  - Allocate a new `b_session_id` for each outbound backend attempt performed on behalf of an A-leg session.
  - Allocate a new B-leg for each failover attempt and each proxy-initiated follow-up call.
  - Support zero, one, or many B-legs per A-leg session (including no backend invocation flows).
  - _Requirements: 1.2, 1.3, 1.4, 1.5, 5.1, 5.2, 5.3_

- [ ] 6.2 Enforce backend identifier isolation at the outbound boundary (no leaks)
  - Ensure outbound backend requests never include `a_session_id`.
  - Ensure outbound backend requests never include `client_session_id`.
  - Populate provider session/conversation correlation fields using `b_session_id` (or a value derived from it) rather than any client-provided identifier.
  - Ensure connectors cannot accidentally propagate client-provided identifiers into upstream provider correlation fields.
  - _Requirements: 3.3, 6.1, 6.2, 6.3, 6.4, 6.5, 13.3_

- [ ] 6.3 Preserve A-leg scoping for internal caches, enforcement, and cancellation
  - Scope internal per-session caches and enforcement registries using `a_session_id` (not B-leg identity).
  - Ensure cancellation scoping remains stable across multiple B-legs under the same A-leg.
  - _Requirements: 5.6, 9.1, 9.6_

- [ ] 7. Observability and diagnostics
- [ ] 7.1 Implement A-leg session echo header (diagnostic-only)
  - When echo is enabled, include a response header (default `x-b2bua-session-id`) with value equal to the internal `a_session_id`.
  - When echo is disabled, omit the configured echo response header.
  - For streaming responses, emit the same echo header value for the lifetime of the stream.
  - Ensure inbound echo headers are ignored for identity and mapping.
  - _Requirements: 3.4, 7.1, 7.2, 7.3, 8.6, 8.7, 12.2, 13.2_

- [ ] 7.2 Emit structured logs for backend attempts with both A-leg and B-leg identifiers
  - Emit structured logs for outbound backend attempts that include both `a_session_id` and `b_session_id` (and `b_seq` where available).
  - Ensure observability outputs never substitute `request_id` for missing session identifiers and omit identifiers on internal resolution errors.
  - _Requirements: 7.4, 7.7, 7.9, 12.1_

- [ ] 7.3 Extend wire capture metadata to carry A-leg and B-leg identities (no request_id fallback)
  - Record `a_session_id` and `b_session_id` as distinct capture metadata values.
  - Preserve backward compatibility by continuing to populate existing capture “session id” fields with `a_session_id`.
  - Ensure missing session identifiers are omitted rather than substituted.
  - _Requirements: 7.5, 7.7, 7.8, 7.9, 12.1_

- [ ] 7.4 Update capture tooling to display and preserve the new identity metadata fields (backward compatible)
  - Ensure capture inspection/replay tooling can read older capture files and display new identity metadata when present.
  - Avoid inventing identifiers in tooling when capture metadata is missing.
  - _Requirements: 7.5, 7.8, 12.1_

- [ ] 7.5 Update usage tracking to attribute usage to A-leg and record per-attempt B-leg metadata
  - Attribute session-level usage metrics to `a_session_id`.
  - Record `b_session_id` (or `b_seq`) for backend-attempt legs so multiple B-legs under one A-leg are distinguishable.
  - Ensure usage outputs do not rely on `request_id` as a session fallback.
  - _Requirements: 7.6, 7.7, 7.10, 12.1_

- [ ] 8. Protocol integration and verification
- [ ] 8.1 Align all protocol frontends on session resolution ordering for captures and backend calls
  - Ensure internal `a_session_id` is resolved before capturing inbound request metadata across all frontend protocols.
  - Ensure session resolution occurs before backend attempts are initiated so B-leg allocation and outbound correlation remain consistent.
  - _Requirements: 7.5, 9.2, 13.3_

- [ ] 8.2 (P) Unit test: identifier generation and formatting
  - Cover A-leg/B-leg id formats and header-safe constraints.
  - Cover embedding of the A-leg UUID component and formatting of B-leg sequence numbers.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6_

- [ ] 8.3 (P) Unit test: client session extraction and auth-scope-scoped continuity rules
  - Cover precedence order, trimming/empty handling, and conflict diagnostics for client session identifiers.
  - Cover ignoring inbound echo headers for identity decisions.
  - Cover continuity scoping behavior for same vs different `auth_scope_id` and localhost implicit scope.
  - _Requirements: 3.4, 3.5, 3.6, 3.7, 4.1, 4.3, 4.4, 4.10_

- [ ] 8.4 (P) Unit test: continuity mapping expiration, bounded growth, and fail-open behavior
  - Cover reuse vs new A-leg generation across expiration and sliding expiration.
  - Cover bounded growth/eviction behavior.
  - Cover fail-open behavior on mapping store errors.
  - _Requirements: 4.2, 4.5, 4.6, 4.7, 4.9, 10.2, 11.3_

- [ ] 8.5 Integration test: failover produces multiple B-legs under one A-leg with correct sequencing
  - Validate a single logical session can produce multiple backend attempts with unique `b_session_id` values and monotonically increasing sequences.
  - Validate attempt records are retained for diagnostics until expiration.
  - _Requirements: 2.5, 2.7, 5.2, 5.5, 11.1_

- [ ] 8.6 Integration test: observability includes correct A-leg/B-leg ids and no-leak guarantees
  - Validate echo header enable/disable behavior for streaming and non-streaming responses.
  - Validate logs, wire captures, and usage records include appropriate A-leg and B-leg identifiers and omit request-id-based fallbacks.
  - Validate outbound provider correlation does not leak `a_session_id` or `client_session_id`.
  - _Requirements: 6.1, 6.2, 6.3, 6.5, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10, 12.1, 12.2, 13.3_
