# Implementation Plan

- [x] 1. Define compaction policy and resource identity rules (P)
  - Specify correlation keys for tool outputs (file path, command signature, call id fallback) and handling for missing identities; document allow/deny tool types per config.
  - Capture invariants: latest result per resource remains unmodified; compaction skipped when identity missing.
  - _Requirements: 1.1, 1.2, 1.3, 3.3, 3.4_

- [x] 2. Implement HistoryCompactionService logic
- [x] 2.1 Traverse history and detect stale tool results (P)
  - Single-pass correlation map to mark older tool results stale when newer resource matches arrive; bypass user/system/assistant reasoning.
  - Preserve message order and metadata; prepare compaction decisions without mutating originals yet.
  - _Requirements: 1.1, 1.2, 1.4, 2.2_
- [x] 2.2 Apply stub replacement and fail-open behavior
  - Replace stale tool contents with explicit stub text including resource identity and "newer output exists"; keep most recent full result intact.
  - On stub generation or logic error, forward original messages unchanged and log with `exc_info=True`.
  - _Requirements: 2.1, 2.3, 2.5, 4.4_

- [x] 3. Integrate token-budget governance (P)
  - Wire token estimation; trigger iterative compaction when estimated outbound tokens exceed configured threshold until below target or no stale entries remain.
  - Enforce allow/deny per tool type and disable compaction when flag off; log when residual overflow risk remains.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 4. Wire service through DI and register processing stage (P)
  - Export `IHistoryCompactionService` interface and register `HistoryCompactionService` in `src/core/di/services.py`.
  - _Requirements: 3.1, 4.1_
- [x] 4.2 Invoke compaction before connector translation
  - Call service in request processing path, passing full history and current config; ensure connectors receive compacted history in order.
  - _Requirements: 2.2, 2.4, 3.1_

- [x] 5. Observability and redaction safeguards (P)
  - Emit metrics (compacted count, bytes/tokens saved, per-tool stats) and structured logs with feature flag state; redact sensitive fields per existing rules.
  - Include compaction summary metadata in CBOR/log context without storing removed content.
  - _Requirements: 4.1, 4.2, 4.3, 4.5_

- [x] 6. Testing and verification
- [x] 6.1 Unit tests for policy and compaction logic (P)
  - Cover staleness detection, stub replacement, identity-missing skip, fail-open behavior, and per-tool allow/deny.
  - _Requirements: 1.1, 1.3, 1.5, 2.1, 2.5, 3.3, 3.5, 4.4_
- [x] 6.2 Integration tests for pipeline wiring
  - Verify compaction invoked in request flow, connectors see compacted history, and metrics/log hooks fire; include threshold-triggered compaction scenario.
  - _Requirements: 2.4, 3.1, 3.2, 4.1, 4.2_
