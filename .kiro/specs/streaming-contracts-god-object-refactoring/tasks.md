# Implementation Plan

This plan assumes the initial refactor is already implemented and committed. The remaining work is strictly the delta required to align the current implementation with the updated requirements and design decisions (notably boundary enforcement and typed cross-layer contracts).

## 1. Align cross-layer streaming data contracts with strong typing

- [ ] 1.1 Introduce standardized typed contracts for streaming payload, metadata, usage, and error envelopes
  - Define a single canonical representation for chunk payload and metadata using Pydantic v2 models.
  - Provide a compatibility bridge so existing callers can continue using the legacy streaming chunk façade without behavior change.
  - Ensure tool-call representations use the existing typed tool-call domain model rather than ad-hoc payload shapes.
  - _Requirements: 3.1, 3.3, 4.1, 4.3 _

- [ ] 1.2 Update streaming serialization and error shaping to use the typed contracts end-to-end
  - Ensure done markers, stop-chunk usage handling, and tool-call sanitization behave identically after typed-contract adoption.
  - Ensure error chunks remain structured and terminal while using typed error envelopes.
  - _Requirements: 3.3, 4.1, 4.3, 4.4 _

- [ ] 1.3 Add characterization tests that lock typed-contract compatibility to existing byte-level behavior
  - Capture “byte-identical” SSE output for representative chunks (normal text deltas, whitespace-only deltas, tool calls, stop-chunk usage, errors, done-only).
  - Ensure tests demonstrate that typed contracts do not alter whitespace handling or completion semantics.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 6.2 _

## 2. Enforce provider-parsing boundary in shared chunk normalization

- [ ] 2.1 Remove provider-specific interpretation from the shared raw-chunk normalization entry point
  - Restrict shared normalization to transport-neutral shapes and conservative wrapping of unknown structured inputs.
  - Ensure provider-specific event parsing occurs only in provider-specific normalizers/adapters.
  - _Requirements: 2.2, 2.3, 3.3 _

- [ ] 2.2 Update upstream call sites that depended on shared provider parsing to use provider normalizers instead
  - Ensure each provider’s raw stream inputs are normalized via the correct provider normalizer before they enter shared processing.
  - Preserve all existing streaming semantics, including error propagation and done-marker behavior.
  - _Requirements: 2.2, 3.3, 4.4, 6.2 _

- [ ] 2.3 Add regression tests that prove provider parsing is isolated to provider normalizers
  - Verify shared normalization does not interpret provider-shaped structured payloads.
  - Verify provider normalizers still accept and normalize provider-specific raw formats correctly.
  - _Requirements: 2.2, 6.2, 6.3 _

## 3. Apply the interface naming and typing rules to avoid cross-layer ambiguity

- [ ] 3.1 Introduce a distinct provider-normalizer interface name and preserve the legacy import surface through re-exports
  - Ensure the provider-normalizer contract name cannot be confused with the services-layer stream normalizer contract.
  - Preserve existing imports from the public streaming contracts façade.
  - _Requirements: 2.1, 3.1 _

- [ ] 3.2 Tighten public-facing streaming interfaces to avoid untyped “Any” across boundaries
  - Ensure request objects and raw stream items are treated as strongly typed domain models at boundaries, and opaque data is explicitly wrapped.
  - Avoid broad unions as cross-domain contracts; normalize at boundaries and pass typed models internally.
  - _Requirements: 2.1, 2.2, 3.1 _

- [ ] 3.3 Ensure new collaborators remain DI-friendly and avoid implicit fallback construction
  - If any new stateful collaborators are introduced to support typed contracts or boundary enforcement, define interfaces at the DI boundary and register implementations explicitly.
  - Avoid “construct a default when dependency is missing” patterns in production code paths; prefer explicit wiring through the existing composition root.
  - _Requirements: 5.1, 5.2 _

## 4. Add enforceable scoped size/complexity guardrails for the refactor surface area

- [ ] 4.1 Implement a scoped gate for file size and cyclomatic complexity for the streaming-contracts surface area
  - Enforce per-file size and per-function/per-module complexity thresholds over the defined refactor surface area only.
  - Ensure failures clearly identify violating modules/functions and do not flag unrelated repository code.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5 _

- [ ] 4.2 Add an automated test entry point that fails when the scoped guardrails are violated
  - Ensure the guardrail check runs as part of the unit suite and prevents complexity relocation regressions.
  - _Requirements: 1.3, 1.5, 6.1 _

## 5. Verification and stabilization (delta-only)

- [ ] 5.1 Run focused streaming tests and fix any regressions introduced by the delta work
  - Validate stop-chunk usage protection, whitespace deltas, tool-call sanitization, error shaping, and done markers remain compatible.
  - _Requirements: 3.2, 4.1, 4.2, 4.3, 4.4, 6.1 _

- [ ] 5.2 Run the full test suite and confirm the scoped guardrails pass
  - Confirm the full suite is green and the refactor surface area stays within thresholds.
  - _Requirements: 6.1 _
