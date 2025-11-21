Pipeline Refactoring Plan (Streaming and Request Processing)
===========================================================

Context and Goals
-----------------
- Reduce fragility across streaming, normalization, middleware, and backend adapters without a full rewrite.
- Enforce clear contracts (SOLID, layered architecture) so changes in one area do not ripple unpredictably.
- Improve error handling, observability, and determinism of tests around streaming and hybrid flows.

Principles
----------
- SRP/OCP: isolate responsibilities (transport, normalization, orchestration, middleware, backend adapters).
- DIP: depend on abstractions (typed contracts) for streaming chunks and backend responses.
- ISP: expose narrow capabilities (stream producer, chunk normalizer, middleware hooks) instead of broad services.
- Determinism: tests must not rely on timing; use fakes/fixed sequences for streaming.
- Guarded observability: TRACE in hot paths with guard checks; metrics over verbose logs.

Phase 0: Baseline and Spec
--------------------------
- Document the streaming contract: chunk shape, metadata fields, explicit end-of-stream marker, error semantics.
- Capture current regressions and log-file/wire-capture findings as concrete scenarios.
- Define KPIs: no stack traces at console, chunk counts match, no reasoning leakage, stable CPU usage under streaming.

Phase 1: Contracts and Types
----------------------------
- Introduce a central `StreamingChunk` dataclass (data bytes, metadata, is_done) and `StreamProducer` protocol used by all backends/adapters.
- Centralize `[DONE]` emission and validation in a shared utility; forbid ad-hoc sentinels in adapters.
- Add lightweight validators for incoming/outgoing chunks (assertions in dev, optional runtime checks in TRACE).

Phase 2: Layered Streaming Pipeline
-----------------------------------
- Split transport adapter into: producer (backend), normalizer (unify provider payloads to contract), assembler (FastAPI Response), and observability hooks.
- Move reasoning/auxiliary filtering into a dedicated normalizer stage; keep transport layer unaware of backend-specific metadata keys.
- Provide a narrow middleware hook interface that can observe/transform chunks without owning logging or backpressure.

Phase 3: Error Handling Hardening
---------------------------------
- Add a single mapping layer from backend/HTTP exceptions to `LLMProxyError` variants; ban raw `HTTPException` from escaping adapters.
- Ensure streaming errors emit a terminal chunk with error metadata, close the stream, and surface structured logs only (no stack traces).
- Verify all middleware uses specific exceptions; add logging with `exc_info` only when rewrapping.

Phase 4: Observability and Performance
--------------------------------------
- Demote hot-path streaming logs to TRACE with `logger.isEnabledFor` guards; add counters/timers via metrics instead of verbose logs.
- Add per-stream metrics: chunks sent, sentinels emitted, middleware mutations, filtered reasoning bytes, error terminations.
- Provide sampling for request/response specimens to aid debugging without re-enabling heavy logs.

Phase 5: Testing Strategy
-------------------------
- Replace timing-based streaming tests with deterministic fakes and fixed chunk sequences.
- Add contract tests per backend: expected chunk count, sentinel presence, metadata filtering (reasoning must not leak), tool-call sequencing.
- Add property-style tests for middleware: transformations are idempotent, do not inject reasoning into main content, and always pass through `[DONE]`.
- Add regression tests for error mapping: backend failures surface as `LLMProxyError` without console stack traces.

Phase 6: Migration Plan
-----------------------
- Parallelize: introduce contract types/utilities first; adapt one backend/adapter pair to the pipeline skeleton; reuse patterns for others.
- Backfill tests at each migrated backend to prevent regressions before moving on.
- Keep feature freeze on streaming changes during migration to stabilize the contract.

Success Criteria
----------------
- All streaming regressions covered by contract-level tests; no console stack traces; `[DONE]` emitted exactly once per stream.
- Reasoning content never appears in main output; metrics show stable chunk counts and reduced CPU/log volume.
- New features can be added via normalizer/middleware hooks without touching transport/assembler layers.
