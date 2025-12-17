# Implementation Plan

## Selected Strategy

This spec is executed using **Option B (Create New Components)**:
- Create new layered modules (domain/ports/transport/services) and move responsibilities out of `src/core/ports/streaming_contracts.py`.
- Convert `src/core/ports/streaming_contracts.py` into a small **compatibility facade** that only re-exports the public surface.
- Preserve **byte-level SSE semantics** where tests require exact output (`data: [DONE]\n\n`, stop-chunk-with-usage framing, and “no duplicate [DONE]” behavior). See `.kiro/specs/streaming-contracts-god-object-refactoring/research.md`.

## Decomposition and Compatibility

- [ ] 1. Baseline characterization and dependency map (P)
  - Inventory the current public surface of `src.core.ports.streaming_contracts` and confirm all symbols used in `src/` + `tests/` remain available.
  - Capture current behavioral invariants from tests around stop-chunk usage, SSE framing, done markers, error propagation, and tool-call sanitization.
  - _Requirements: 3.1, 6.2_

- [ ] 2. Define the target module boundary map in code (create folders and module skeletons)
  - Create the new module layout described in `design.md` (domain/ports/services/transport) with minimal initial implementations.
  - Ensure each new module is designed to remain < 600 LOC.
  - _Requirements: 1.2, 2.2, 6.3_

- [ ] 3. Convert `src/core/ports/streaming_contracts.py` into a compatibility facade
  - Replace implementation-heavy code with re-exports of the relocated symbols, preserving import paths used by callers/tests.
  - Remove any transport/vendor imports from the facade (including `httpx`).
  - _Requirements: 1.1, 2.1, 3.1_

## Domain Decomposition (Pure Semantics)

- [ ] 4. Extract usage stop-chunk protection into domain module
  - Move `StopChunkWithUsage` and `UsageChunkLeakError` into a dedicated domain module and keep behavior identical.
  - Ensure “no accidental stringification/implicit JSON serialization” behavior remains covered by tests.
  - _Requirements: 3.2, 4.1_

- [ ] 5. Extract sentinel handling into a focused utility
  - Move `SentinelManager` into a small module and preserve done-marker semantics (`create_done_chunk`, detection, SSE done marker bytes).
  - _Requirements: 4.4, 6.2_

- [ ] 6. Refactor `StreamingContent` into a thin domain model with delegating adapters
  - Keep dataclass fields/invariants and metadata synchronization in the domain model.
  - Keep `StreamingContent.from_raw` and `StreamingContent.to_bytes` signatures stable but delegate to dedicated parser/serializer modules.
  - _Requirements: 1.3, 3.3, 4.2_

## Parsing Decomposition (Provider/Format Heuristics)

- [ ] 7. Introduce raw-chunk parsing strategies (P)
  - Implement a parser chain/strategy set for: bytes/SSE fragments, OpenAI dict chunks, Anthropic event dicts, Gemini JSON objects, `ProcessedResponse`, and passthrough `StreamingContent`.
  - Ensure parsers preserve whitespace-only delta handling and do not drop usage-bearing stop chunks.
  - _Requirements: 1.3, 4.1, 4.2_

- [ ] 8. Update call sites to use the delegated parsing entry point (internal only)
  - Update internal modules that currently re-parse or partially parse chunks to rely on the shared parsing entry point where appropriate, without changing their external behavior.
  - _Requirements: 2.2, 6.2_

## Transport Decomposition (SSE Serialization)

- [ ] 9. Introduce an SSE serializer responsible for framing and sanitization (P)
  - Move SSE framing decisions and tool-call sanitization logic out of the domain model and into a transport module.
  - Preserve: usage-bearing stop chunk top-level serialization, terminal done markers, and removal of internal-only markers/`extra_content`.
  - _Requirements: 3.3, 4.1, 4.3, 4.4_

- [ ] 10. Align assembler/orchestrator integration with the new serializer
  - Ensure `SSEAssembler` and any other streaming output path continues to produce byte-identical framing where expected (or semantically identical where tests assert semantics).
  - Keep the orchestrator pipeline behavior unchanged.
  - _Requirements: 3.3, 6.1_

## Error Mapping Decomposition (Vendor Exceptions)

- [ ] 11. Move vendor/transport-specific exception mapping out of ports
  - Relocate `httpx`-specific exception mapping into a services-layer module and ensure ports/contracts no longer import `httpx`.
  - Preserve existing error normalization behavior and error metadata fields in terminal chunks.
  - _Requirements: 2.1, 3.3, 6.2_

## Interfaces and DI

- [ ] 12. Extract streaming interfaces into a ports-only module
  - Move `StreamProducer`, `IStreamNormalizer`, `BaseStreamNormalizer`, `IStreamProcessor`, and `IStreamAssembler` into a focused ports module with no vendor/transport dependencies.
  - Preserve existing normalizer implementations by updating their imports only.
  - Ensure the ports/contracts layer does not import from `src/connectors/` and remains adapter-agnostic.
  - _Requirements: 2.2, 2.3, 3.1_

- [ ] 13. (Optional) Introduce DI seams for stateful collaborators (P)
  - If new stateful components are introduced (serializer, parser registry, error mapper), define interfaces under `src/core/interfaces/` and register them in the existing DI composition root.
  - _Requirements: 5.1, 5.2_

## Verification and Guardrails

- [ ] 14. Add enforceable complexity/LOC checks for the refactor scope (P)
  - Extend `scripts/analyze_complexity.py` (or add a focused script) to report CC + MI + LOC for the new streaming modules and fail the build when thresholds are violated.
  - Include checks that prevent “complexity relocation” by applying constraints to all extracted modules, not just `streaming_contracts.py`.
  - _Requirements: 1.2, 1.3, 1.4, 1.5_

- [ ] 15. Run targeted tests and fix regressions
  - Run streaming-focused unit/property/integration/regression tests and ensure they pass under default pytest markers.
  - Add characterization tests where coverage is missing for invariants in Requirements 4.x.
  - _Requirements: 6.1, 6.2_
