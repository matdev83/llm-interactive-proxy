# Implementation Plan

- [x] 1. Define tagging contracts, errors, and configuration
- [x] 1.1 Define non-forwardable tag contracts and scope values
  - Introduce a domain representation for non-forwardable scope with `never_forward` and `client_history_only`.
  - Define a fixed-size, content-independent identity representation suitable for bounded in-memory storage.
  - Define a compact tag record structure that can be stored per session without retaining message content.
  - Ensure the domain contracts do not rely on any client-provided metadata for correctness.
  - _Requirements: 1.1, 1.7, 1.8, 14.1_

- [x] 1.2 Define service interfaces for identity, registry, and enforcement
  - Define an identity computation contract that is deterministic for canonical domain messages and excludes client metadata.
  - Define a registry contract that supports session-scoped append-only tagging and tag lookups.
  - Define an enforcement contract that filters a message list and reports filtered counts while preserving order.
  - Specify fail-closed behavior for indeterminate matches or internal errors (raise before any backend call).
  - _Requirements: 1.2, 1.3, 1.4, 1.9, 1.10, 7.3, 10.1, 12.1_

- [x] 1.3 Define error types and API error mapping for enforcement failures
  - Add a domain error for internal enforcement failures that must fail closed without backend calls.
  - Add a client-visible error for “no forwardable content remains” after filtering.
  - Add a client-visible error for “non-forwardable tag capacity exceeded” (bounded memory protection).
  - Ensure error responses are structured and do not leak filtered message content.
  - _Requirements: 5.3, 6.2, 7.3, 10.1, 14.3_

- [x] 1.4 Add configuration for per-session non-forwardable tag capacity limit
  - Add a configuration field for maximum stored non-forwardable identities per session.
  - Ensure configuration precedence is respected (CLI > ENV > YAML).
  - Provide a default limit of 10,000 identities when not configured.
  - _Requirements: 14.3, 14.4_

- [x] 2. Implement deterministic message identity
- [x] 2.1 Implement identity computation with compaction-stable rules
  - Compute identity from canonical message attributes only (no transport wrappers, no client metadata).
  - Normalize textual fields for hashing without mutating messages (line-ending normalization only).
  - Ensure tool result identities do not depend on tool output content so identities survive history compaction rewrites.
  - Add request-local caching/batching to avoid unnecessary repeated hashing under normal workloads.
  - _Requirements: 1.2, 1.9, 1.10, 1.12, 1.13, 5.2, 9.1_

- [x] 2.2 (P) Add unit tests for identity determinism and compaction stability
  - Verify deterministic identities for equivalent canonical messages across repeated computations.
  - Verify identities ignore client metadata/transport-only fields.
  - Verify tool result identity remains stable when tool output content is rewritten by compaction.
  - _Requirements: 1.2, 1.10, 1.12, 1.13_

- [x] 3. Implement session-scoped tag registry with bounded memory
- [x] 3.1 Implement registry persistence, deduplication, and per-session limit enforcement
  - Persist tags per session as append-only and immutable for the session lifetime.
  - Store only fixed-size identities and compact scope/tag records (no message content retention).
  - Deduplicate repeated tagging of the same identity+scope so stored state does not grow from repeats.
  - Enforce the configured per-session tag capacity limit and fail the request before any backend call when exceeded.
  - _Requirements: 1.1, 1.3, 8.3, 8.4, 14.1, 14.2, 14.3, 14.4_

- [x] 3.2 (P) Add unit tests for registry immutability, dedupe, and limit exceeded behavior
  - Verify tags are monotonic (append-only) and cannot be removed within a session lifetime.
  - Verify re-tagging the same identity+scope does not increase stored state.
  - Verify exceeding the configured limit produces the correct error and prevents backend calls.
  - _Requirements: 1.3, 10.1, 14.2, 14.3_

- [x] 4. Implement the non-forwardable enforcer (single filtering policy)
- [x] 4.1 Implement scope-aware filtering with preserved order and no content mutation
  - Filter messages recognized as non-forwardable for the session and exclude them from outbound payloads.
  - Always exclude `never_forward` messages regardless of whether they originated from the client or the proxy.
  - Preserve relative ordering of remaining forwardable messages and do not mutate their content.
  - Support filtering across roles/content variants present in canonical message contracts.
  - Ignore client attempts to mark messages as non-forwardable and rely solely on server-tagged recognition within the session.
  - If all forwardable user-provided content is removed, return a client-visible "nothing forwardable" error without backend calls.
  - _Requirements: 1.4, 1.5, 1.6, 1.7, 1.11, 3.2, 4.3, 5.1, 5.2, 5.3, 10.1, 12.1_

- [x] 4.2 Implement injected-message provenance boundary and client-history-only semantics
  - Accept an internal provenance boundary that splits client-submitted history from proxy-injected messages for a call.
  - Filter client history against both scopes (`never_forward`, `client_history_only`).
  - Filter injected messages against `never_forward` only so proxy-injected steering remains included for that call.
  - Validate boundary inputs and fail closed on invalid provenance before any backend call.
  - _Requirements: 1.8, 1.11, 4.1, 4.2, 4.4, 7.2, 7.3_

- [x] 4.3 Implement structured telemetry for filtering decisions
  - Emit a structured log entry when messages are filtered, including correlation id and filtered count.
  - Avoid logging message contents by default while still supporting request-level correlation.
  - Ensure telemetry remains accurate when wire capture is enabled and filtering is applied.
  - _Requirements: 6.1, 6.2, 11.1_

- [x] 4.4 (P) Add unit tests for enforcer invariants and fail-closed behavior
  - Verify order preservation and no mutation for remaining messages.
  - Verify `never_forward` and `client_history_only` semantics, including injected-message boundary behavior.
  - Verify invalid boundary provenance and internal lookup errors fail closed without backend calls.
  - _Requirements: 1.4, 1.5, 1.6, 1.8, 4.4, 7.3, 10.1_

- [x] 5. Tag non-forwardable messages at the sources (commands, responses, steering)
- [x] 5.1 (P) Tag slash commands as never-forward and ensure server-side handling
  - When a client message is identified as a slash command, tag it as `never_forward` for the session.
  - Execute supported commands server-side and return the command response without calling a remote backend.
  - Return an error response for invalid/unsupported commands without calling a remote backend.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [x] 5.2 (P) Tag server-generated command responses as never-forward
  - Tag the server-generated command response message as `never_forward` for the session at creation time.
  - Ensure the tag is persisted for the session lifetime as soon as the response is generated and before it is returned to the client.
  - Ensure recognition does not rely on client-preserved metadata if the client resubmits the response in history.
  - _Requirements: 3.1, 3.2, 3.3_

- [x] 5.3 (P) Tag server-injected steering/internal messages as client-history-only
  - When the proxy injects steering/internal messages for a backend workflow, tag them as `client_history_only`.
  - Provide the injected-message provenance boundary for the current backend call so filtering semantics are correct.
  - Ensure client echo of these messages is excluded from future backend payloads within the same session.
  - _Requirements: 4.1, 4.2, 4.4_

- [x] 6. Wire enforcement into backend orchestration (single authoritative boundary)
- [x] 6.1 Register identity, registry, and enforcer services in staged initialization
  - Register new services with appropriate lifetimes and dependency wiring.
  - Ensure configuration values (tag capacity limit) are available to the registry at runtime.
  - Confirm services are available to command handling, steering injection, and backend orchestration in staged initialization order.
  - _Requirements: 1.1, 1.2, 1.3, 14.3_

- [x] 6.2 Integrate enforcement into backend completion flow before capture and invocation
  - Apply optional history compaction (if enabled) before enforcement so filtering runs on the final outbound message list.
  - Invoke enforcement immediately before backend request translation, outbound wire capture, and backend invocation.
  - Update the canonical request message list to the filtered list so downstream processing and captures are consistent.
  - Ensure no remote backend call occurs without passing through this enforcement boundary.
  - _Requirements: 5.4, 6.3, 7.1, 7.4, 7.6_

- [x] 6.3 Add integration tests for backend flow filtering and compaction compatibility
  - Verify wire captures and outbound payloads exclude non-forwardable messages.
  - Verify filtering still matches and excludes tagged messages when tool-result history is compacted/rewritten.
  - Verify "no forwardable content" and tag-capacity errors fail before any backend call.
  - _Requirements: 1.12, 1.13, 6.3, 7.1, 7.4, 14.3_

- [x] 6.4 Add property-based tests for identity and filtering invariants (deferrable)
  - Generate diverse canonical message shapes (role/content/tool variants) and assert identity determinism.
  - Assert filtering invariants (order preserved; removed messages are always tagged for the session and scope).
  - Include cases covering tool-result messages whose content is rewritten by compaction.
  - _Requirements: 1.2, 1.5, 5.2_

- [x] 7. Ensure coverage across entry points and session identity propagation (Option B)
- [x] 7.1 (P) Refactor WebSocket-based backend call paths to use the shared orchestrator
  - Remove direct calls to backend adapters from WebSocket features and route via the shared backend-call service.
  - Ensure a session id is resolved/created for the interaction and reused across multiple backend calls in a turn.
  - Confirm the shared enforcement boundary is invoked for these calls.
  - _Requirements: 7.5, 7.6, 8.1, 8.2, 8.3_

- [x] 7.2 (P) Refactor internal multi-phase backend workflows to use the shared orchestrator
  - Remove direct calls to backend adapters from internal multi-phase executors and route via the shared backend-call service.
  - Ensure nested backend calls reuse the same session id for the logical interaction.
  - Confirm the shared enforcement boundary is invoked for these calls.
  - _Requirements: 7.5, 7.6, 8.1, 8.2, 8.3_

- [x] 7.3 Ensure internal retry/steering workflows propagate session id and injection provenance
  - Reuse the same session id across multiple backend calls made within a single logical interaction.
  - Provide the injected-message provenance boundary for every backend call that appends steering/internal messages.
  - Confirm internal workflows never bypass the shared enforcement boundary.
  - _Requirements: 7.2, 8.2, 8.3_

- [x] 7.4 Add integration tests for session scoping and non-leakage across entry points
  - Verify tags are applied only within the resolved session id and do not leak across sessions.
  - Verify a non-HTTP entry point reuses the same session id across multiple backend calls in a single interaction.
  - Verify concurrent interactions do not cross-apply tags between different session identifiers.
  - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 8. Remove legacy regex-based enforcement and legacy code paths (alpha finality)
- [x] 8.1 Remove regex-based non-forwardable filtering mechanisms and all wiring
  - Delete legacy regex-based mechanisms previously used for command stripping and prompt redaction related to non-forwardable behavior.
  - Remove any remaining "compatibility" toggles or fallback paths that preserve legacy semantics.
  - Ensure the tagging + single-boundary enforcement mechanism is the only remaining implementation.
  - _Requirements: 13.1, 13.2, 13.3_

- [x] 8.2 Update tests to remove legacy regex expectations and assert final behavior only
  - Remove or rewrite tests that depended on legacy regex stripping and replace with tagging/enforcement assertions.
  - Add regression coverage that fails if legacy regex-based non-forwardable filtering is reintroduced.
  - Remove obsolete helpers/fixtures that existed only to support legacy regex-based enforcement tests.
  - _Requirements: 13.1, 13.3_

- [x] 8.3 Run the full unit and integration suites for this feature and fix failures
  - Ensure unit tests for identity/registry/enforcer pass.
  - Ensure integration tests for backend flow, compaction compatibility, and entry point coverage pass.
  - Ensure static checks pass for modified modules (lint, formatting, type checks).
  - _Requirements: 9.1, 10.1, 11.1_

- [x] 8.4 Ensure final state of the implementation and legacy paths removed
  - Ensure all new functionalities from this effort are actually and properly wired in via the DI.
  - This is an Alpha stage project. We don't need to maintain any backward compability. All implementations made during this effort should be the only active implementations of the features being in scope of this effort. No legacy code superseded by the new one created during this session should remain. Check it.
  - Ensure no fallbacks to legacy code
  - Ensure legacy code unwired, removed and fully replaced by the code created during this session
