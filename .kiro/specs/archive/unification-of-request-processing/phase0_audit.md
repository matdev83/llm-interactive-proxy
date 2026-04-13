# Phase 0 Audit - Manager Cut Line and Feature Classification

This document records the Phase 0 audit required before canonical convergence work.

## 1.1 Manager/Handler Cut-Line Characterization

## Scope Baseline

- The canonicalization cut line starts in `BackendRequestManager.process_backend_request()` **after** `IBackendProcessor.process_backend_request()` returns.
- Dedup short-circuit and preflight retry-limit checks remain above the cut line.
- Transport adaptation remains below the cut line (`response_adapters` layer).

## Current Responsibility Inventory

| Area | Current owner | Notes for migration |
|---|---|---|
| Dedup registration + duplicate short-circuit | `BackendRequestManager` | Must remain pre-backend and pre-gate. |
| Streaming completion classification (disconnect/terminal/error) | `BackendRequestManager` stream wrapper | Must remain preserved until canonical equivalent is proven. |
| Non-streaming post-processing and retry orchestration | `BackendNonStreamingResponseHandler` | Candidate for coordinator convergence. |
| Streaming post-processing, loop controls, verifier buffering | `BackendStreamingResponseHandler` | Candidate for coordinator convergence with explicit safeguards. |
| Tool-call retry coordination | `ToolCallRetryCoordinator` + handlers | Mode-sensitive cases must remain explicit until unified safely. |
| Empty-response/empty-stream recovery | `EmptyResponseFeature` + handlers | Cannot be treated as generic chunk logic during migration. |
| Quality-verifier control flow | request processor + streaming verifier + handlers | Keep parity-sensitive behavior pinned with tests. |

## Phase 1 Boundary Decision

- **In scope for first convergence:** post-backend-response handling branch currently split by requested mode.
- **Out of scope for Phase 1:** backend processor contract replacement, connector stream-first bridge, transport response object changes.
- **Fallback policy:** legacy split handlers stay available for rollback while gate is default-off.

## Explicit Migration Exceptions (Phase 0)

- Tool-call retry and empty-response recovery remain mode-sensitive until canonical feature/context migration.
- Completion-state classification remains in existing stream wrapper until tested canonical equivalent exists.

## 1.2 Response-Processing Feature Audit and Migration Classification

## Classification Rules

- `chunk-safe`: can run on canonical chunk stream with no end-of-stream assumptions.
- `terminal-sensitive`: depends on terminal chunk markers or finish reason.
- `full-response-sensitive`: requires accumulated response materialization.
- `explicit-exception`: temporary bounded mode-specific behavior during migration.

## Feature Inventory and Strategy

| Feature / behavior | Classification | Canonical strategy |
|---|---|---|
| Response logging / content filtering | chunk-safe | Bridge through canonical stream-first feature pipeline. |
| Empty-response recovery | terminal-sensitive | Keep explicit safeguard path until canonical coordinator feature parity is proven. |
| Tool-call retry coordination | terminal-sensitive | Keep explicit collaborator; migrate only with dedicated adapter coverage. |
| Loop detection / cancellation chunk emission | terminal-sensitive | Preserve dedicated streaming behavior; migrate with explicit tests. |
| Structured output enforcement | full-response-sensitive | Use canonical adapter path for non-streaming accumulation context. |
| Quality-verifier stream verification and recall behavior | terminal-sensitive | Keep dedicated verifier collaborator during early migration. |
| Usage/metadata propagation | full-response-sensitive | Preserve envelope metadata via canonical handle before adapter conversion. |

## Bridge Eligibility Summary

- **Bridge-safe now:** response logging, content filtering (chunk-safe).
- **Dedicated canonical adapter required:** structured output enforcement.
- **Explicit temporary exception required:** empty-response recovery, loop detection, tool-call retry, quality-verifier flow.

## Phase 0 Exit Preconditions

- Cut line is fixed at manager post-backend-response branch.
- Feature classifications above are treated as migration constraints for tasks `4.1` and `4.2`.
- New gate defaults remain off; diagnostics expose active path and stage (`migration_stage`, `canonical_path_used`, `feature_canonical_used`, `connector_stream_first_used`).
