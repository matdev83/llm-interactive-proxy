# Implementation Plan

- [ ] 1. Resource identity extraction hardening
- [ ] 1.1 (P) Write unit tests for file-read identity normalization and slice parameters
  - Cover stable identities across argument encodings (JSON string vs object) and numeric strings vs integers.
  - Cover file path normalization for platform variants (path separators, drive letter casing).
  - Treat each unique combination of file path and slice parameters as distinct (including `offset`, `limit`, `start_line`, `end_line`, `index`, `page`, `cursor`, `chunk_size`, `length`).
  - Confirm different slices of the same file are never marked stale due to each other.
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [ ] 1.2 Implement expanded resource identity extraction for slice-based tools
  - Include all identity-relevant parameters for file-read style tools, including mixed “slice schemes” when multiple slice parameters are present.
  - Apply conservative “missing vs explicit default” semantics unless a tool’s contract is explicitly known.
  - Preserve tool outputs unchanged when identity cannot be determined reliably.
  - Record ambiguity diagnostics when correlation cannot be determined.
  - _Requirements: 1.1, 1.3, 1.5, 1.6, 7.4_

- [ ] 1.3 (P) Write unit tests for search and directory identity rules
  - Ensure search identities combine query + scope and do not treat scope as the query.
  - Ensure directory/listing identities combine directory + filter parameters that materially change results.
  - Ensure uncorrelatable outputs are preserved unchanged.
  - _Requirements: 7.2, 7.3, 7.4, 7.5_

- [ ] 2. Stub format, idempotency, and safe detection
- [ ] 2.1 (P) Write unit tests for stub recognition across legacy and versioned formats
  - Recognize legacy stubs that start with `[COMPACTED]` even when message metadata is absent.
  - Recognize versioned stubs (v1+) and ensure they remain stable and unambiguous.
  - Verify stubbed messages are never compacted again (idempotency).
  - _Requirements: 2.5, 2.6, 3.6_

- [ ] 2.2 Implement versioned stub format while preserving legacy compatibility
  - Emit a versioned stub marker for new stubs while continuing to recognize legacy stubs.
  - Include enough identity detail to distinguish different slices of the same primary resource.
  - Ensure stub generation failures preserve original tool outputs unchanged and record diagnostics.
  - _Requirements: 3.1, 3.2, 3.3, 3.5, 3.6_

- [ ] 2.3 Update compaction flow to enforce idempotency without relying on metadata
  - Skip already-stubbed tool result messages even if metadata is missing or stripped by client round-tripping.
  - Preserve message order and tool call linkage fields required for downstream connector compatibility.
  - _Requirements: 2.4, 2.5, 2.6_

- [ ] 3. Eligibility policy defaults and configuration surface
- [ ] 3.1 (P) Write unit tests for conservative policy evaluation and per-tool controls
  - When compaction is enabled, require explicit permits before compacting any tool results.
  - Preserve tool outputs unchanged when no permits exist, when a tool is unknown, or when explicitly denied.
  - Validate category-based and tool-name-based allow/deny precedence and per-request evaluation.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

- [ ] 3.2 Implement policy semantics and configuration updates
  - Add tool-name allow/deny configuration support and define deterministic precedence.
  - Add an explicit compatibility toggle for “empty allowlist” meaning, defaulting to conservative behavior.
  - Update validation surfaces (schema and example config) to reflect the new policy fields.
  - _Requirements: 5.1, 5.2, 5.5, 5.6_

- [ ] 4. Compaction algorithm correctness and token budget governance
- [ ] 4.1 Write unit tests for staleness detection and preservation limits
  - Mark older tool results stale only when a newer result exists for the same identity.
  - Always preserve the most recent tool result per identity unmodified.
  - Enforce preservation limits (preserve last N results; cap stubs per identity).
  - Preserve non-tool messages unchanged and preserve history ordering.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.7, 3.4_

- [ ] 4.2 Implement incremental compaction selection under threshold semantics
  - Apply the “greater than or equal to threshold” boundary rule when deciding whether compaction may run.
  - Compact additional eligible stale tool results while the estimate remains above threshold and eligible stale candidates remain.
  - Select candidates in a way that minimizes edits while achieving reductions (for example, largest estimated savings first).
  - Clamp negative savings estimates to zero when stub overhead exceeds the removed content.
  - _Requirements: 4.1, 4.2, 4.3, 6.4_

- [ ] 4.3 Write integration tests for request preparation compaction behavior
  - Verify compaction is skipped below threshold and is permitted at or above threshold.
  - Verify iterative compaction behavior and configured preservation limits in a realistic request flow.
  - Verify overflow warnings occur when token estimates remain above maximum after compaction.
  - Verify fail-open behavior forwards original histories on errors.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 6.5_

- [ ] 5. Observability and redaction safety
- [ ] 5.1 (P) Write unit tests for diagnostics safety and identifier redaction
  - Ensure diagnostics contain counts and savings estimates without including removed tool output content.
  - Ensure identifiers are redacted in both stubs and diagnostics when redaction is enabled.
  - Ensure no unredacted identifiers can leak via structured log context or metrics fields.
  - _Requirements: 6.1, 6.2, 6.3_

- [ ] 5.2 Implement diagnostics redaction and fail-open observability contracts
  - Apply identifier redaction consistently in all diagnostics surfaces intended for logs/metrics.
  - Ensure errors record the error condition and preserve original history unchanged.
  - _Requirements: 6.2, 6.3, 6.5_

- [ ] 6. Additional tool types compaction support
- [ ] 6.1 Implement safe compaction support for non-file-read tool result types
  - Enable identity-based staleness compaction for search and directory listing tools when explicitly permitted by policy.
  - Preserve outputs unchanged for tool results that cannot be safely correlated to an identity.
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

- [ ] 6.2 Write integration tests for permitted non-file tool types
  - Verify that search/list-directory tool results compact only when explicitly permitted and correctly correlated by query+scope or directory+filters.
  - _Requirements: 7.1, 7.2, 7.3_

- [ ] 7. Verification and quality gates
- [ ] 7.1 Run targeted unit and integration tests and fix failures
  - Ensure coverage includes legacy stub idempotency, slice identity correctness, conservative policy defaults, threshold boundaries, and redaction safety.
  - _Requirements: 1.3, 2.6, 4.1, 6.3_

- [ ] 7.2 Run linting, formatting, and type checks and fix findings
  - Validate that changes preserve async correctness and do not introduce blocking work in the request path.
  - _Requirements: 4.3, 6.5_
