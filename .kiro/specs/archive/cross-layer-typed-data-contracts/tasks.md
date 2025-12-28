# Implementation Plan

- [x] 1. Phase A: Make request context a typed, explicit contract
- [x] 1.1 Add explicit typed fields to request context and remove reliance on dynamic attributes
  - Add explicit, typed fields for the cross-layer data currently attached dynamically (domain request, raw body, backend, effective model, extensions)
  - Ensure context construction supports correlation identifiers needed for logging and capture (request ID/session ID where available)
  - Preserve existing behavior for callers that do not provide optional fields (remain backward compatible)
  - _Requirements: 2.2, 2.3, 3.1, 4.1 _

- [x] 1.2 Update transport-to-domain adaptation to populate typed context fields end-to-end
  - Populate the explicit context fields during request adaptation instead of post-hoc mutation
  - Ensure raw body bytes are consistently available for capture when provided by the transport
  - Ensure canonical domain request is attached via explicit field for downstream session resolution
  - _Requirements: 2.3, 4.1, 4.2, 7.1 _

- [x] 1.3 Migrate controllers and core services away from dynamic context attributes
  - Replace any dynamic attribute writes with assignments to declared context fields
  - Update session resolution/enrichment logic to read from declared fields and stop writing dynamic attributes
  - Confirm no cross-layer path depends on `type: ignore[attr-defined]` for request context
  - _Requirements: 3.1, 4.2, 4.3, 6.3 _

- [x] 1.4 Add characterization tests for request context propagation and behavior preservation
  - Validate that all supported protocol controllers pass canonical domain requests into the core processor with unchanged client-visible behavior
  - Validate that protocol-specific requests normalize into shared canonical contracts before core processing
  - Validate that raw body capture uses the explicit context field without requiring dynamic attributes
  - Ensure tests cover both streaming and non-streaming paths where context propagation differs
  - _Requirements: 1.1, 1.2, 1.4, 1.5, 2.6 _

- [x] 2. Phase A: Constrain extension payloads and reduce ad hoc dict usage at boundaries
- [x] 2.1 Introduce a single, JSON-serializable extension container and use it consistently
  - Standardize a single extension container type for cross-layer data that must remain flexible
  - Ensure extension values are constrained to JSON-serializable types rather than `Any`
  - Document and apply a promotion rule for frequently-used extension keys (promote to first-class typed fields when stable)
  - _Requirements: 3.2, 3.3, 4.4, 6.1 _

- [x] 2.2 Tighten target-resolution URI parameter typing to JSON-serializable values
  - Ensure resolved URI parameter values are constrained to JSON-serializable types end-to-end
  - Preserve target resolution order and precedence behavior while tightening types
  - _Requirements: 2.4, 3.2, 4.2, 4.3 _

- [x] 2.3 Add type-checking guardrails for Phase A boundary changes
  - Ensure new/changed boundary code does not introduce additional type ignores
  - Run static type checks to confirm boundary signatures remain type-safe under the current mypy configuration
  - _Requirements: 3.4, 6.2 _

- [x] 3. Phase A: Preserve immutability and streaming performance
- [x] 3.1 Enforce copy-on-write mutation behavior for contract changes in the request pipeline
  - Ensure request modifications produce new contract instances rather than mutating in-place
  - Preserve access to the original values needed for accounting, capture, and debugging
  - _Requirements: 5.1, 5.2, 5.3 _

- [x] 3.2 Validate streaming contract choices do not introduce buffering or regressions
  - Keep internal streaming representation lightweight and avoid per-chunk heavy conversions in hot paths
  - Add regression tests to ensure time-to-first-byte is not impacted by buffering-only changes
  - _Requirements: 5.4, 7.3 _

- [x] 4. Phase B primitives: Introduce canonical routing and usage contracts
- [x] 4.1 (P) Introduce a canonical backend target contract and integrate it into target resolution outputs
  - Represent backend, model, and resolved URI parameters in a stable typed contract
  - Use this contract as the canonical handoff between routing/target resolution and completion orchestration
  - _Requirements: 2.1, 2.4, 3.1 _

- [x] 4.2 (P) Introduce a canonical usage summary contract and integrate it into usage recording surfaces
  - Represent standard usage fields with a single extension container for provider-specific usage details
  - Ensure usage contract can be serialized deterministically for debugging and capture metadata
  - _Requirements: 2.2, 5.3, 7.3 _

- [x] 4.3 Align backend completion collaborator boundaries to canonical contracts
  - Replace ad hoc cross-layer payloads at collaborator seams with canonical contracts
  - Preserve failover, retry, and capture behavior while tightening types
  - _Requirements: 2.4, 3.1, 3.2, 6.3 _

- [x] 5. Phase B+: Tighten backend completion and connector-facing boundary types
- [x] 5.1 Replace collaborator interface `Any` signatures with canonical types and add compatibility shims where required
  - Update cross-layer boundaries to accept canonical request/context/target contracts
  - Maintain backward compatibility for existing call sites during the migration window
  - _Requirements: 1.2, 3.1, 3.2, 4.2 _

- [x] 5.2 Make response envelope metadata and usage surfaces typed and JSON-serializable
  - Reduce reliance on ad hoc `dict[str, Any]` for usage and metadata at cross-layer envelope boundaries
  - Preserve external response content and controller adaptation behavior
  - _Requirements: 2.5, 3.2, 4.2, 7.3 _

- [x] 5.3 Add integration tests for collaborator wiring and connector compatibility
  - Validate that connectors continue to receive canonical domain requests
  - Validate that failover, capture, and usage tracking behavior is unchanged for supported protocols
  - _Requirements: 1.1, 1.4, 1.5 _

- [x] 6. (P) Capture and replay: Best-effort round-trip into canonical contracts
- [x] 6.1 (P) Implement best-effort decoding of captured traffic into canonical request/response contracts for simulation
  - Treat raw capture bytes as source-of-truth while supporting decoded, typed inspection paths
  - Ensure decoding failures are non-blocking and produce actionable diagnostics
  - _Requirements: 7.2, 7.3 _

- [x] 6.2 (P) Add tests for capture decoding determinism and round-trip invariants
  - Validate decoded contracts are stable enough for diff-based debugging
  - Ensure replay tooling can reconstruct the canonical contracts where the capture contains structured JSON payloads
  - _Requirements: 7.2, 7.3 _

- [x] 7. (P) Contributor guidance and enforcement
- [x] 7.1 (P) Add developer guidance describing canonical contracts and conversion points
  - Document the canonical contract set and allowed boundary conversion points
  - Document extension-field policy and the promotion process from extension keys to typed models
  - _Requirements: 8.1, 8.2 _

- [x] 7.2 (P) Add lightweight enforcement guardrails to prevent regression toward `Any` at boundaries
  - Add a simple, fast check that flags new boundary `Any` / ad hoc `dict` usage early
  - Ensure guardrails are practical for contributor workflows and do not block legitimate internal contexts
  - _Requirements: 3.2, 8.1 _

- [x] 8. Final verification and regression safety
- [x] 8.1 Run focused unit and integration suites for touched layers and fix regressions
  - Validate streaming and non-streaming paths for all supported protocol controllers
  - Validate wire capture continues to produce compatible CBOR captures
  - _Requirements: 1.5, 7.1 _

- [x] 8.2 Run formatting, linting, and type checking for touched modules
  - Ensure the updated boundaries remain type-safe without introducing new unsafe casts or ignores
  - _Requirements: 3.4, 6.2 _

- [x] 8.3 Fix boundary type violations related to introduced canonical contracts
  - Replace `Any` and `dict[str, Any]` in interfaces that exchange canonical contracts (RequestContext, BackendTarget, UsageSummary, ResponseEnvelope)
  - Focus on cross-layer seams: backend completion collaborators, request/response processors, transport adapters
  - Preserve backward compatibility where needed with compatibility overloads
  - **Note**: `IContractCoercionService` was deemed unnecessary as request adapters and controllers now handle coercion directly to `CanonicalChatRequest`.
  - _Requirements: 3.1, 3.2, 3.4 _

- [x] 9. Phase B+: Narrow ResponseEnvelope.content type
- [x] 9.1 Narrow ResponseEnvelope.content from Any to specific union
  - Changed `ResponseEnvelope.content` from `Any` to `dict[str, Any] | str | bytes | None`
  - Changed `ProcessedResponse.content` to match the same type
  - Updated documentation in typed-data-contracts.md to reflect the change
  - _Requirements: 2.5, 3.1, 3.2 _

- [x] 9.2 Update documentation to reflect Phase B+ completion
  - Updated typed-data-contracts.md to document the narrowed ResponseEnvelope.content type
  - Updated all Phase B+ deliverables to reflect completion status
  - _Requirements: 8.1, 8.2 _

  - **Note**: `IContractCoercionService` was deemed unnecessary as request adapters and controllers now handle coercion directly to `CanonicalChatRequest`.
  - **Note**: Narrowing `ResponseEnvelope.content` from `Any` is deferred to Phase B+ as documented in design.

