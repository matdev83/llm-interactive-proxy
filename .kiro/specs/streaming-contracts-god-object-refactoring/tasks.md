# Implementation Plan

## 1. Baseline characterization and safety net

- [ ] 1.1 Inventory the public import surface and usage sites
  - Identify all symbols imported from `src.core.ports.streaming_contracts` across source and tests.
  - Record which imports are runtime-critical vs test-only.
  - Confirm the design’s facade re-exports cover every observed symbol.
  - _Requirements: 3.1_

- [ ] 1.2 Capture byte-level streaming invariants as characterization tests
  - Ensure coverage exists for: exact done marker bytes, “no duplicate done”, and SSE framing for dict and string chunks.
  - Ensure coverage exists for StopChunkWithUsage: wrapper preservation and top-level usage serialization.
  - Ensure coverage exists for tool-call sanitization (internal markers removed before client emission).
  - _Requirements: 3.3, 4.1, 4.3, 4.4, 6.2_

- [ ] 1.3 Confirm the intended `from_raw` supported-input matrix matches real upstream shapes
  - Validate which shapes actually reach the canonical chunk conversion entry point in current pipelines.
  - Identify any provider-specific event shapes that must be handled by provider normalizers instead of shared parsing.
  - _Requirements: 2.2, 3.1_

## 2. Extract domain semantics (stop chunk + done markers)

- [ ] 2.1 Extract StopChunkWithUsage and usage leak prevention behavior
  - Preserve “no accidental stringification/implicit serialization” behavior for usage-bearing stop chunks.
  - Ensure usage-bearing stop chunks remain detectable as a protected type through the pipeline.
  - _Requirements: 3.2, 4.1_

- [ ] 2.2 Extract done-marker construction and detection utilities
  - Preserve done marker detection/emission behavior and exact marker bytes.
  - Ensure terminal “done-only” output does not emit spurious payload content.
  - _Requirements: 4.4, 6.2_

- [ ] 2.3 Preserve backward compatible imports through the facade
  - Keep callers importing from `src.core.ports.streaming_contracts` working without requiring widespread rewrites.
  - Ensure the facade remains vendor/transport-library free.
  - _Requirements: 2.1, 3.1_

## 3. Build the transport serializer and services error mapping

- [ ] 3.1 Implement the core SSE framing and done-marker rules
  - Preserve exact SSE framing (`data: ...`) and terminal marker bytes across the main streaming output paths.
  - Ensure “no duplicate done” behavior when upstream already emits a terminal done marker.
  - _Requirements: 3.3, 4.4_

- [ ] 3.2 Implement StopChunkWithUsage serialization and tool-call sanitization in the serializer
  - Serialize usage-bearing stop chunks with usage at the correct top-level location and the correct terminal marker.
  - Preserve tool-call sanitization behavior by removing internal-only markers and `extra_content` before emission.
  - _Requirements: 4.1, 4.3, 4.4_

- [ ] 3.3 Implement streaming error mapping outside of the contracts layer
  - Map vendor exceptions into consistent domain error types and structured terminal chunk metadata.
  - Ensure ports/contracts code does not import vendor libraries to support boundary enforcement.
  - _Requirements: 2.1, 3.3, 4.4_

- [ ] 3.4 Wire legacy entry points to delegate to the extracted serializer and mapper
  - Keep existing signatures stable while moving complex logic behind extracted collaborators.
  - Ensure the output remains byte-compatible where tests assert exact bytes.
  - _Requirements: 3.1, 3.3, 6.2_

## 4. Decompose raw chunk parsing without embedding provider parsing

- [ ] 4.1 Implement parsing for transport-neutral input shapes
  - Support SSE bytes/strings, JSON strings, and plain strings with stable done-marker detection.
  - Ensure whitespace-only deltas are treated as non-empty content when appropriate.
  - _Requirements: 1.3, 1.4, 4.2, 4.4_

- [ ] 4.2 Implement parsing for structured input shapes
  - Support streaming chunk dict payloads and wrapped response envelopes while preserving usage-bearing stop chunk behavior.
  - Ensure unsupported shapes are handled conservatively (opaque content) without introducing provider semantics.
  - _Requirements: 1.3, 3.3, 4.1_

- [ ] 4.3 Enforce the provider-parsing boundary in the shared parsing entry point
  - Ensure provider-specific event schemas are normalized in provider normalizers rather than shared parsing logic.
  - Ensure unknown provider-shaped dicts are treated as opaque content rather than being interpreted.
  - _Requirements: 2.2, 2.3_

- [ ] 4.4 Update internal adapters/parsers to rely on the shared parsing entry point
  - Remove duplicate partial parsing logic where it causes drift or inconsistent behavior.
  - Keep externally observable behavior unchanged.
  - _Requirements: 3.3, 6.2_

## 5. Extract streaming ABIs into ports-only interfaces (and avoid naming collisions)

- [ ] 5.1 Introduce ports-layer streaming ABIs with explicit naming to avoid collisions
  - Define a ports-layer provider-normalizer interface name distinct from the services pipeline normalizer.
  - Preserve the legacy import surface by re-exporting under the historical name in the facade.
  - _Requirements: 2.1, 3.1_

- [ ] 5.2 Update provider normalizers and assemblers to consume the ports-layer ABIs
  - Ensure provider normalizers remain responsible for provider event parsing and normalization.
  - Ensure ports-level code does not depend on backend connector modules.
  - _Requirements: 2.2, 2.3, 3.1_

- [ ] 5.3 Validate new collaborators remain stateless or introduce DI seams when needed
  - If stateful behavior is introduced, define interfaces in the DI boundary layer and wire implementations through the DI composition root.
  - Avoid fallback construction patterns for newly introduced collaborators.
  - _Requirements: 5.1, 5.2_

## 6. Convert streaming contracts module into a compatibility facade and enforce boundaries

- [ ] 6.1 Convert the streaming contracts module into re-exports only
  - Keep the file under the size threshold and ensure it does not accumulate new logic.
  - Preserve all public symbols used by callers and tests.
  - _Requirements: 1.1, 3.1_

- [ ] 6.2 Remove vendor/transport dependencies from the contracts layer
  - Ensure contracts/ports code does not import vendor libraries or transport framework types.
  - _Requirements: 2.1_

## 7. Add enforceable complexity and size guardrails (scoped)

- [ ] 7.1 Implement a scoped metrics gate for LOC and cyclomatic complexity
  - Enforce per-file size limits and per-function/per-module complexity thresholds for the streaming-contracts refactor surface area.
  - Ensure the gate is scoped to avoid unrelated failures elsewhere in the repository.
  - _Requirements: 1.2, 1.3, 1.4, 1.5, 6.3_

- [ ] 7.2 Add a test entry point to prevent “complexity relocation” regressions
  - Fail CI if thresholds are violated for any module in the refactor scope.
  - _Requirements: 1.3, 1.5, 6.1_

## 8. End-to-end verification and regression fixing

- [ ] 8.1 Run focused streaming tests and fix regressions
  - Run unit/regression/property tests tied to streaming serialization, done markers, stop chunk usage, and error propagation.
  - Fix failures without changing external behavior.
  - _Requirements: 6.1, 6.2_

- [ ] 8.2 Run the full test suite and confirm refactor scope metrics gates pass
  - Confirm refactor scope remains within LOC/CC thresholds and that the full suite remains green.
  - _Requirements: 6.1_
