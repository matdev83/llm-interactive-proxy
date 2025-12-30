# Implementation Plan

- [ ] 1. Boundary type guardrails: scope, allowlist, and CI wiring
- [ ] 1.1 (P) Define an explicit boundary surface enforcement scope
  - Introduce a scope configuration that declares which modules are “boundary surfaces” vs internal-only.
  - Start with a Phase 0 scope that uses explicit file pinning for the highest-leverage seams (signature-first), then expand via include globs in later phases.
  - Ensure the scope includes transport adapters, core interfaces, and the connector boundary API without pulling in all connector implementations.
  - Ensure canonical contract carriers remain in-scope even when broader internal modules are excluded.
  - _Requirements: 3.1, 3.2_

- [ ] 1.2 Update the boundary type checker to enforce only the declared scope
  - Load the scope configuration and compute the effective file set deterministically.
  - Preserve actionable violation output including file path, line/column, and a human-readable message.
  - Ensure the check exits with code 0 for a compliant codebase and non-zero when violations exist.
  - Clarify/document Phase 0 capability as signature-first; do not claim full model-field enforcement until explicitly implemented.
  - _Requirements: 3.3, 3.4_

- [ ] 1.3 Implement a time-bounded allowlist mechanism for boundary exceptions
  - Support narrow exceptions with rationale, tracking reference, and an expiration timestamp.
  - Fail the boundary type check when an allowlisted entry is expired.
  - Ensure allowlist usage is confined to the smallest practical surface and has a documented promotion path.
  - _Requirements: 2.7, 3.5_

- [ ] 1.4 Integrate the boundary type check into the required verification workflow
  - Wire the check into the project’s standard verification path so newly introduced non-allowlisted violations fail.
  - Ensure the developer workflow documents the canonical command and remediation process.
  - _Requirements: 3.6, 3.7, 1.5_

- [ ] 1.5 Add automated tests for scope filtering and allowlist behavior
  - Test include/exclude behavior, explicit file pinning, and allowlist expiry handling.
  - Validate that violations report file path + line/column + message consistently.
  - _Requirements: 3.3, 3.4, 3.5_

- [ ] 2. Connector seam hardening: canonical API, invoker, and migration
- [ ] 2.1 (P) Introduce canonical connector-facing contracts and protocol
  - Add `ConnectorRequestContext` as the minimal connector-facing context contract (request/session ids + JSON-safe extensions).
  - Add `ConnectorChatCompletionsRequest` as the canonical connector request payload (includes request + processed messages + context).
  - Add `ICanonicalChatCompletionsBackend` (or equivalent) to define the canonical connector entry point.
  - Ensure connector-facing options and extension values are constrained to JSON-serializable typed values.
  - Ensure connector cancellation uses a stable typed interface (e.g., `ISessionCancellationCoordinator | None`) rather than `Any`.
  - Ensure connector-facing contracts do not import transport framework types.
  - _Requirements: 4.1, 4.2, 4.3, 2.3_

- [ ] 2.2 Implement `ConnectorInvoker` with canonical-first dispatch and legacy fallback
  - Build the canonical connector request payload from core orchestration inputs.
  - Project `RequestContext` into `ConnectorRequestContext` as a shallow, JSON-safe mapping (`request_id`, `session_id`, `client_host`, `extensions`) and pass it only via the canonical connector API.
  - Prefer the canonical connector API when available; otherwise call legacy connector code without converting canonical request/context into dict payloads.
  - Confine any legacy-only kwargs expansion to this invoker and emit structured logs when the legacy path is exercised.
  - Do not require legacy connectors to accept connector context via `**kwargs`; guarantee connector context only on the canonical connector API.
  - _Requirements: 4.4, 2.3, 5.1, 5.3, NFR3.1_

- [ ] 2.3 Wire connector invocation through the invoker without behavior changes
  - Replace direct connector calls in orchestration with invoker-based calls.
  - Preserve failover/retry behavior and any best-effort side effects on the execution path.
  - Preserve client-visible error classification and HTTP mapping when connector execution fails.
  - _Requirements: 1.2, 1.3, NFR2.1, NFR2.3_

- [ ] 2.4 Migrate connectors exercised by CI to the canonical connector API
  - Update first-party connectors used by existing tests to implement the canonical connector protocol.
  - Ensure connectors consume typed processed messages and canonical request payloads consistently.
  - Ensure provider-specific options are consumed from a JSON-safe options container in the canonical path.
  - _Requirements: 4.1, 4.2, 4.3, 1.5_

- [ ] 2.5 Migrate remaining first-party connectors incrementally and contain exceptions
  - Migrate remaining first-party connectors in small batches to reduce risk and review load.
  - Where a connector must temporarily rely on permissive behavior, document and time-bound the exception with a promotion path.
  - _Requirements: 2.7, 4.4, 1.2_

- [ ] 2.6 Add tests for connector seam compatibility and error mapping
  - Validate canonical connectors receive the canonical request payload and typed processed messages.
  - Validate legacy connectors remain compatible via the invoker without dict payload leakage into core services.
  - Validate options handling remains JSON-safe and does not regress connector behavior.
  - _Requirements: 1.1, 1.2, 1.3, 4.4, 1.5_

- [ ] 3. Response and streaming seam hardening: processed chunks, usage, and metadata
- [ ] 3.1 (P) Harden `ProcessedResponse` contract and boundary signatures
  - Align `ProcessedResponse` (and related boundary interfaces) on a single shared `ProcessedChunkContent` union (no `Any` in boundary signatures).
  - Ensure `ProcessedResponse.metadata` uses JSON-safe values (`dict[str, JsonValue]`) and avoids mutable class-level defaults.
  - Ensure the contract remains transport-agnostic and efficient to construct per chunk.
  - _Requirements: 2.5, 6.1, 6.2, NFR1.2_

- [ ] 3.2 Tighten core response processing to emit boundary-safe processed responses
  - Normalize connector outputs into `ProcessedChunkContent` before handing off to transport adapters (no provider-specific objects crossing seams).
  - Ensure per-chunk transformations remain shallow and do not introduce buffering.
  - Preserve copy-on-write behavior for any enrichment of contracts during processing.
  - _Requirements: 2.5, 6.3, NFR1.2, NFR1.3_

- [ ] 3.3 Update transport streaming adapters to consume typed processed responses
  - Serialize processed chunk payloads without introducing per-chunk deep parsing or extra buffering.
  - Preserve ordering, flush semantics, and time-to-first-byte behavior for streaming responses.
  - Preserve client-visible error mapping when streaming serialization fails.
  - _Requirements: 1.1, 1.2, 1.3, 2.5, NFR1.2_

- [ ] 3.4 Tighten non-streaming response envelopes to typed usage and JSON-safe metadata
  - Ensure non-streaming results crossing boundaries use canonical usage and JSON-safe metadata end-to-end.
  - Ensure protocol/vendor-specific extras cross boundaries only through a documented extension container.
  - _Requirements: 2.4, 2.6, 6.1, 6.2_

- [ ] 3.5 Add regression coverage for streaming performance and copy-on-write behavior
  - Add tests that guard against time-to-first-byte regressions on streaming paths.
  - Add tests that validate no deep-copy behavior is introduced for large payloads in common paths.
  - Add tests that validate contract updates preserve copy-on-write behavior.
  - _Requirements: NFR1.1, NFR1.2, NFR1.3, 1.5_

- [ ] 3.6 Add integration tests for protocol response behavior and usage/capture invariants
  - Cover supported protocols for streaming and non-streaming response flows.
  - Validate response shapes remain compatible and usage/metadata propagation remains correct.
  - Ensure capture-enabled paths remain inspectable and replayable using existing tooling.
  - _Requirements: 1.1, 1.2, 1.4, 1.5, NFR3.2_

- [ ] 4. Centralize conversions and remove legacy dict leaks across boundaries
- [ ] 4.1 Remove remaining dict acceptance from core boundary interfaces
  - Identify core interfaces/services that accept dict alternatives for canonical contracts and refactor them to accept canonical contracts only.
  - Introduce explicitly named compatibility wrappers only at boundary adapter conversion points.
  - _Requirements: 5.1, 5.3_

- [ ] 4.2 Centralize legacy coercion at explicit adapter boundaries only
  - Ensure any dict-to-contract coercion occurs only at explicit transport/controller adapters and the connector invoker legacy path.
  - Eliminate internal “best-effort coercion” that allows legacy shapes to persist inside core orchestration.
  - _Requirements: 5.2, 5.3_

- [ ] 4.3 Add deterministic boundary validation, errors, and structured logs
  - Ensure invalid boundary inputs fail deterministically with structured errors consistent with the existing error hierarchy.
  - Preserve existing fail-open semantics for best-effort side effects where applicable.
  - Emit structured logs with correlation identifiers when boundary conversion or validation fails.
  - _Requirements: NFR2.2, NFR2.3, NFR3.1, 1.3_

- [ ] 4.4 Verify transport-to-core request context and routing outputs remain canonical
  - Ensure all supported protocol controllers attach canonical inbound request contracts to a canonical request context before core processing.
  - Ensure routing outputs are represented using canonical target contracts and JSON-safe URI parameters across seams.
  - Add focused tests to prevent regressions toward ad hoc dict shapes at these seams.
  - _Requirements: 2.1, 2.2, 1.1, 1.5_

- [ ] 5. Capture and replay alignment with canonical contracts
- [ ] 5.1 Tighten capture collaborator boundaries to canonical contracts and JSON-safe metadata
  - Replace capture collaborator boundary inputs/outputs that use `Any` or ad hoc dicts for usage and structured metadata.
  - Preserve raw byte capture as the source of truth while enabling deterministic typed views for debugging.
  - _Requirements: 7.1, 6.1, 6.2, 1.4_

- [ ] 5.2 Ensure deterministic serialization and secret-safe logging for canonical contracts
  - Ensure serialization used for logging and capture is stable enough for diff-based debugging and replay workflows.
  - Preserve existing redaction and secret-handling behavior and avoid emitting sensitive content unless existing configuration permits it.
  - _Requirements: 7.3, NFR4.1, NFR4.2_

- [ ] 5.3 Harden decode/replay tooling to return typed contracts with structured diagnostics
  - Ensure best-effort decoding produces typed canonical contracts when possible.
  - Ensure decode failures return structured diagnostics without raising exceptions.
  - Add tests for decode determinism and diagnostic structure.
  - _Requirements: 7.2, 7.3, NFR3.2_

- [ ] 6. Contributor guidance for typed contract boundaries
- [ ] 6.1 Update developer guidance on boundary surfaces, rules, and enforcement workflow
  - Document the canonical contract set and the allowed boundary conversion points.
  - Document the boundary type check command and expected remediation workflow, including allowlist policy.
  - _Requirements: 8.1, 3.6_

- [ ] 6.2 Document extension container and connector options policy with promotion guidance
  - Document how vendor/protocol-specific data crosses boundaries via the extension container and JSON-safe values.
  - Define “approved extension mechanisms” vs “legacy extension mechanisms” and forbid new ad hoc boundary extension fields.
  - Document how connector option keys are promoted from permissive surfaces into typed fields/contracts over time.
  - _Requirements: 8.2, 2.6, 2.7_

- [ ] 6.3 Document `Any` policy: internal-only allowance vs boundary prohibition
  - Document where `Any` is permitted (internal-only) and where it is forbidden (boundary surfaces).
  - Document how and when to add or remove time-bounded allowlist entries.
  - _Requirements: 8.3, 3.5, 3.6_

- [ ] 7. Final verification and regression safety
- [ ] 7.1 Drive boundary checker violations to zero within the declared scope
  - Fix boundary type violations in-scope by tightening signatures and boundary payload types.
  - Use allowlist entries only when a time-bounded exception is required and a promotion path exists.
  - _Requirements: 3.3, 3.5, 3.7_

- [ ] 7.2 Run targeted unit/integration suites for touched flows and fix regressions
  - Validate all supported protocol controllers for streaming and non-streaming paths.
  - Validate connector invocation, failover/retry, capture, and usage behavior remain unchanged.
  - _Requirements: 1.1, 1.2, 1.4, 1.5, NFR2.1_

- [ ] 7.3 Run formatting, linting, and type checks for touched modules
  - Ensure boundary hardening changes remain type-safe and do not introduce new ignores.
  - Ensure the repository’s required verification workflow is green end-to-end.
  - _Requirements: 1.5, 3.7_
