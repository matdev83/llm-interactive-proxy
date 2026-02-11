# Implementation Plan

- [ ] 1. Align canonical model parsing and resolution boundaries with the refactored architecture
- [ ] 1.1 Enforce `:`-only backend selection parsing in shared model utilities and resolver entry points
  - Apply one canonical parser path for all request-model inputs so `/` remains model payload and never backend selection.
  - Preserve first-colon split behavior and multi-colon tail preservation for effective model identifiers.
  - Ensure colon-after-slash selectors (for example `vendor/model:free`) stay in model-only mode.
  - Ensure `backend/model` remains model-only syntax unless explicitly rewritten by validated config rules.
  - _Requirements: 1.1, 1.2, 1.4, 1.5, 1.6, 1.7, 8.1, 10.1_

- [ ] 1.2 Apply parsing and selector validation consistently across explicit-backend features
  - Ensure explicit backend features validate `backend:model` and reject malformed selectors with structured errors.
  - Ensure explicit instance syntax continues to route as concrete instance selection with no load balancing.
  - _Requirements: 1.3, 8.2, 8.3_

- [ ] 1.3 Parse URI-like model-selector parameters as first-class routing inputs
  - Parse query-like selector suffixes for all routing modes and preserve them in normalized routing target metadata.
  - Ensure parsing behavior is protocol-agnostic across all ingress surfaces.
  - _Requirements: 13.1_

- [ ] 2. Extend resolver-centric dynamic routing for all request variants
- [ ] 2.1 Route `backend:model` via deterministic round robin across eligible instances
  - Use backend-type instance discovery with deterministic ordering and concurrency-safe counters.
  - Keep single-target fallback behavior when numbered instances do not exist.
  - _Requirements: 2.1, 2.2, 2.3_

- [ ] 2.2 Route model-only identifiers (`model`, `vendor/model`) through capability-driven candidate selection
  - Select candidates from capability index mappings and policy gates before backend dispatch.
  - Apply configured preference ordering for model-only candidates before final selection.
  - Return explicit unknown-model errors when no candidates exist.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 14.1_

- [ ] 2.3 Ensure no-backend-available outcomes fail before connector invocation
  - Return structured routing errors when all candidates are filtered as unavailable.
  - _Requirements: 2.4, 6.3_

- [ ] 2.4 Introduce one shared routing entry point for outbound inference target resolution
  - Provide a standardized routing function/method that all outbound backend call paths can invoke.
  - Ensure the primary message path uses this routing entry point as the source of truth.
  - _Requirements: 10.1_

- [ ] 2.5 Enforce shared resolver usage across all protocol ingress surfaces
  - Ensure OpenAI-compatible, Anthropic-compatible, Gemini-compatible, interactive command, and auxiliary inference ingress paths all route through the same resolver contract.
  - Ensure protocol adapters cannot bypass routing semantics while transforming transport envelopes.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 8.4, 10.1_

- [ ] 2.6 Implement URI-parameter inheritance and precedence during dispatch
  - Inherit parsed URI-like parameters across candidate expansion, primary dispatch, and failover attempts for one logical request.
  - Enforce deterministic merge precedence: connector-forced settings > explicit request fields > URI-like model parameters > defaults.
  - _Requirements: 13.2, 13.3, 13.4, 13.5_

- [ ] 2.7 Implement user-configurable preference-policy ranking for model-only routing
  - Support first-class cost-based and priority-based ranking policies.
  - Support deterministic policy scope resolution (model override > backend-family override > global default).
  - Define deterministic handling for missing cost/priority metadata.
  - Use deterministic Round Robin for equivalent-score tie sets.
  - _Requirements: 14.1, 14.2, 14.3, 14.5, 14.7_

- [ ] 3. Implement capability indexing as shared source for routing and models listing
- [ ] 3.1 Build startup capability snapshots from connector enumeration with config-hint fallback
  - Discover per-instance support via `get_available_models_async`/`get_available_models` when available.
  - Fall back to configured hints without failing startup.
  - _Requirements: 5.1, 5.2_

- [ ] 3.2 Maintain backend-agnostic canonical model keys with fast candidate lookups
  - Keep canonical `vendor/model` keys and compatibility aliases where needed.
  - Define deterministic tie-breaking for `model` vs `vendor/model` normalization collisions and surface diagnostics for ambiguous mappings.
  - Apply deterministic source precedence and refresh merge semantics for mixed enumeration/config/alias inputs.
  - Guarantee request-path lookup performance suitable for per-request use.
  - _Requirements: 5.3, 5.5, 7.3_

- [ ] 3.3 Support safe runtime refresh of capability snapshots
  - Replace index snapshots atomically and avoid blocking request processing.
  - _Requirements: 5.4, 7.1, 7.2_

- [ ] 3.4 Implement capability refresh control-plane lifecycle policy
  - Implement startup, periodic, and on-demand refresh triggers with single in-flight refresh guarantees.
  - Implement bounded backoff and last-known-good snapshot retention on refresh failures.
  - _Requirements: 5.4, 5.5, 7.1, 7.2_

- [ ] 4. Integrate availability and resilience state into candidate eligibility
- [ ] 4.1 Filter candidates using permanent disablement and cooldown state
  - Apply instance-level and (instance, model)-level availability checks before selection.
  - _Requirements: 4.1, 4.2, 4.3, 4.5_

- [ ] 4.2 Track permanent unsupported-model outcomes and use them in future selection
  - Normalize provider-specific model-not-found signals into one classifier contract used across protocol adapters.
  - Record classified permanent model-not-found outcomes as unsupported `(instance, model)` facts.
  - Exclude unsupported pairs in both primary routing and failover retries.
  - _Requirements: 4.4, 4.5_

- [ ] 4.3 Clear temporary cooldown state on successful recovery attempts
  - Restore candidate eligibility for recovered `(instance, model)` pairs after successful calls.
  - Preserve precedence so success recovery does not clear permanent unsupported/permanent disabled state.
  - _Requirements: 4.6_

- [ ] 4.4 Implement explicit backend reactivation control-plane contract
  - Provide a deterministic reactivation path for permanently disabled backend instances with validation, state transition rules, and audit/diagnostics visibility.
  - Ensure reactivation does not implicitly clear unrelated persistent state unless explicitly requested.
  - _Requirements: 4.3, 6.2_

- [ ] 5. Wire routing behavior into BackendCompletionFlow failover lifecycle
- [ ] 5.1 Keep failover attempts bounded and model-aware under the new routing rules
  - Enforce max distinct backend attempts per request and avoid retry loops.
  - Define deterministic attempt counting (initial dispatch + proxy failovers) and precedence with connector-internal hold/wait plus request cancellation/timeouts.
  - Ensure failover proceeds within highest-preference equivalent set before lower-preference sets.
  - _Requirements: 7.4, 11.4, 14.4_

- [ ] 5.2 Harmonize failure classification across routing, availability, and execution layers
  - Ensure unknown-model and temporarily-unavailable classes propagate consistently to API errors and captures.
  - _Requirements: 2.4, 3.3, 6.3_

- [ ] 5.5 Standardize canonical routing error envelope and protocol adapter mappings
  - Define one canonical internal routing-error schema and map it consistently to OpenAI-compatible, Anthropic-compatible, and Gemini-compatible transport error shapes.
  - Ensure retryability and `details.code` semantics remain equivalent across protocols.
  - _Requirements: 6.3, 10.1_

- [ ] 5.3 Define and enforce proxy-vs-connector precedence rules for routing and wait behavior
  - Specify deterministic precedence between proxy-level timeout/cancellation/failover limits and connector-internal hold/wait behavior.
  - Ensure orchestration applies boundaries without duplicating connector-internal scheduling logic.
  - _Requirements: 11.2, 11.4_

- [ ] 5.4 Define constrained connector-family policy for single-instance self-managed OAuth backends
  - Define one centrally reused constrained-family policy covering `gemini-oauth*`, `antigravity*`, and `qwen-oauth`.
  - Ensure this policy is consumed by both config validation and routing behavior.
  - _Requirements: 12.1, 12.4_

- [ ] 6. Integrate B2BUA session semantics with routing and execution identity handling
- [ ] 6.1 Preserve A-leg continuity for routing/session context in B2BUA mode
  - Ensure session lookup and routing continuity use canonical A-leg identity rather than transient client-provided ids.
  - _Requirements: 9.1_

- [ ] 6.2 Allocate B-leg identity per backend attempt and isolate connector-facing session IDs
  - Use per-attempt B-leg ids for outbound connector calls, including retry/failover attempts.
  - Preserve stable A-leg continuity while rotating B-leg attempts.
  - _Requirements: 9.2, 9.3_

- [ ] 6.3 Isolate auxiliary/sidecar request session lifecycle from primary conversation continuity
  - Derive effective auxiliary session ids and prevent sidecar state from mutating primary routing/session continuity.
  - Implement deterministic derived-identity contract for auxiliary calls (input/output/invariants).
  - Implement deterministic fail-open fallback semantics (omit connector-facing `session_id` when allowed, opaque surrogate otherwise) with no A-leg leakage.
  - Ensure fail-open behavior if B2BUA allocation fails, without identity leakage.
  - _Requirements: 9.4, 9.5, 10.1, 10.4_

- [ ] 6.4 Route Random Model Replacement backend calls through the shared routing entry point
  - Ensure replacement model dispatch uses the same standardized routing function/method as primary message calls.
  - Preserve replacement-specific policy while reusing shared backend/model resolution and availability semantics.
  - _Requirements: 10.1, 10.2_

- [ ] 6.5 Route Quality Verifier backend calls through the shared routing entry point
  - Ensure quality verification model invocation uses the same standardized routing function/method as primary message calls.
  - Preserve verifier-specific execution controls while reusing shared backend/model resolution and availability semantics.
  - _Requirements: 10.1, 10.3_

- [ ] 6.6 Enforce no-bypass integration rules for outbound inference routing
  - Add guardrails so new outbound inference integrations cannot bypass the shared routing function/method.
  - Surface validation/test failures when bypass patterns are introduced.
  - Implement mandatory CI compliance gate execution for bypass detection (non-optional merge blocker).
  - Define and maintain an authoritative outbound call-surface inventory artifact used by the compliance gate.
  - Bind the compliance gate to required status check identifier `routing-unification-compliance`.
  - Add automated outbound call-site discovery/registration checks and fail CI when unregistered call surfaces are detected.
  - Implement both static bypass inspection and runtime contract tests as mandatory gate checks.
  - _Requirements: 10.5, 10.6_

- [ ] 6.7 Preserve connector-internal autonomy for multi-identity connectors
  - Ensure unified proxy routing resolves connector instance/model only and does not perform account-level rotation for connectors that already own that logic.
  - Explicitly support connector-managed internal round robin/affinity behavior (for example `gemini-oauth-auto`).
  - _Requirements: 11.1, 11.3_

- [ ] 6.8 Ensure B2BUA/session safety during connector-internal hold and resume windows
  - Validate that temporary connector-level waiting (for account cooldown/hold) does not break A-leg continuity or leak identity across sessions.
  - _Requirements: 9.1, 9.2, 9.3, 11.2_

- [ ] 6.9 Enforce single-instance validation for constrained connector families at startup
  - Validate merged backend instances (YAML/env/default/file-discovery) and fail fast when constrained families define more than one proxy instance.
  - Implement one deterministic matcher for explicit constrained names and wildcard families used by both validation and routing policy checks.
  - Implement canonical connector normalization (case/aliases) and precedence rules (explicit-name > wildcard > specificity tie-break).
  - Return actionable migration guidance to consolidate legacy multi-instance configurations.
  - _Requirements: 12.1, 12.2, 12.3, 12.5_

- [ ] 6.10 Ensure routing behavior respects constrained connector-family single-instance policy
  - Prevent proxy-level multi-instance round-robin from activating for connector families constrained to one proxy instance.
  - Preserve connector-internal scheduling autonomy inside the single selected instance.
  - _Requirements: 11.1, 11.3, 12.4_

- [ ] 7. Update observability surfaces to reflect canonical routing state
- [ ] 7.1 Serve canonical backend-agnostic model identifiers from capability index
  - Expose canonical model set for `/v1/models` with compatibility options for legacy clients.
  - _Requirements: 5.3, 6.1_

- [ ] 7.2 Extend diagnostics with routing eligibility state and safe correlation metadata
  - Expose availability summaries and candidate eligibility views without exposing secrets or internal identity fields.
  - Distinguish proxy-level routing decision metadata from connector-internal scheduling metadata.
  - Keep diagnostics output bounded/deterministic for large model-instance sets using stable ordering, hard caps, and explicit truncation metadata.
  - Expose applied preference policy and equivalent-score tie-set summaries for model-only routing decisions.
  - _Requirements: 6.2, 9.5, 11.5, 14.6_

- [ ] 8. Add verification coverage for routing, availability, capability indexing, and B2BUA behavior
- [ ] 8.1 Add unit tests for parser and resolver behavior across all model-addressing variants
  - Cover explicit backend, explicit instance, vendor/model, plain model, and multi-colon cases.
  - Include explicit coverage for OpenRouter-style tier-tag suffixes (for example `backend:vendor/model-name:free`).
  - Include explicit coverage for model-only tier-tag forms (for example `vendor/model-name:free` and `vendor/model-name:free?temperature=0.5`) to confirm no backend misclassification.
  - Cover URI-like selector parameters (`model?temperature=0.5`, `vendor/model?temperature=0.5`) across routing modes.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 8.1, 13.1_

- [ ] 8.2 Add unit tests for capability indexing and runtime refresh behavior
  - Cover startup discovery, fallback hints, canonical key normalization, and atomic refresh.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 7.3_

- [ ] 8.3 Add unit tests for availability filtering and resilience state transitions
  - Cover cooldowns, permanent disablement, provider-normalized model-not-found classification, unsupported-model tracking, and cooldown clearing on success.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 7.1, 7.2_

- [ ] 8.4 Add integration tests for request pipeline and completion flow with B2BUA identity handling
  - Verify A-leg continuity with per-attempt B-leg outbound ids under retries/failover.
  - Verify auxiliary routing session isolation, deterministic derived-identity behavior, and fail-open fallback behavior without identity leakage.
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 10.4, 7.4_

- [ ] 8.5 Add integration tests for API observability and routing errors
  - Verify `/v1/models` canonical output, diagnostics availability summaries (with deterministic ordering/caps/truncation behavior), error differentiation behavior, and reactivation state visibility.
  - _Requirements: 6.1, 6.2, 6.3_

- [ ] 8.6 Run focused tests and quality checks for modified routing and session paths
  - _Requirements: 7.1, 7.2_

- [ ] 8.7 Add unification regression tests covering all outbound call categories
  - Verify regular requests, Random Model Replacement, Quality Verifier, and auxiliary calls all invoke the same routing entry point.
  - Verify a bypass attempt fails both test-time validation and the mandatory CI compliance gate.
  - Verify unregistered discovered outbound call surfaces fail compliance checks.
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

- [ ] 8.8 Add connector-autonomy integration tests for hierarchical routing composition
  - Verify connectors with internal schedulers (for example `gemini-oauth-auto`) preserve internal account rotation/hold behavior under unified proxy routing.
  - Verify precedence between proxy-level attempt budget/cancellation/timeout/failover boundaries and connector-internal wait behavior.
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

- [ ] 8.9 Add configuration validation and migration tests for constrained connector families
  - Verify startup rejects multiple configured proxy instances for `gemini-oauth*`, `antigravity*`, and `qwen-oauth` families.
  - Verify case/alias normalization and explicit-vs-wildcard precedence produce deterministic family matches.
  - Verify validation output provides deterministic consolidation guidance for legacy setups.
  - _Requirements: 12.1, 12.2, 12.3, 12.5_

- [ ] 8.10 Add cross-protocol routing-consistency tests
  - Verify all supported protocol ingress and interactive command surfaces use shared routing semantics (`:` parsing, model-only routing behavior, and unified resolver entry).
  - Verify canonical routing-error classification maps consistently across protocol-specific response adapters.
  - Verify URI-like selector parameters are propagated as effective connector handling parameters across routing modes and protocol surfaces.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 6.3, 8.4, 10.1, 13.1, 13.2, 13.3, 13.4, 13.5_

- [ ] 8.11 Add precedence/override tests for URI parameter inheritance
  - Verify connector-forced settings override inherited URI parameters when applicable.
  - Verify explicit request fields override URI-parameter defaults deterministically.
  - _Requirements: 13.4, 13.5_

- [ ] 8.12 Add reactivation lifecycle tests for permanently disabled instances
  - Verify explicit reactivation transitions backend availability state from disabled to active and appears in diagnostics.
  - Verify reactivation preserves unrelated persistent state unless explicitly reset.
  - _Requirements: 4.3, 6.2_

- [ ] 8.13 Add preference-policy and tie-break regression tests for model-only routing
  - Verify cost-based and priority-based policies rank candidates deterministically.
  - Verify equal-score candidates (for example same cost) are selected using deterministic Round Robin, not first-found pinning.
  - Verify failover walks same top equivalent set first, then lower-preference sets.
  - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6_
