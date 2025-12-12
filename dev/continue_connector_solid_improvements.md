# Gemini Base Connector — Next-Round Improvement Plan

## Purpose
We stabilized the connector (401/429 handling, thought_signature errors) and passed the full test suite. This document captures what still needs refinement to reach a cleaner, more SOLID, and maintainable design in a fresh session.

## Quick Pointers for a Fresh Session
- Primary code paths: `src/connectors/gemini_base/connector.py`, `streaming_executor.py`, `token_manager.py`, `chat_request_preparer.py`, `thought_signature_manager.py`, plus protocols in `connector_context.py`.
- Known-good baseline: tests last ran green (`./.venv/Scripts/python.exe -m pytest -q --maxfail=1`, 8629 passed, 94 skipped). Current behavior: 401 triggers a forced credential reload and retry; 429 triggers a single retry-after wait (no model fallbacks); thought signatures inject only cached values (no placeholders) with a tool_call_id secondary index.

## Why This Refactor / Fundamental Problems to Solve
- Connector remains a large orchestration monolith; SRP/SOLID gaps make it hard to evolve safely.
- Retry/auth handling is inlined and implicit; policies are not explicit or reusable, which weakens resilience.
- Thought signature handling needs a single cohesive surface and clear guarantees (no placeholders, session/tool-call correctness).
- Observability for latency/retries is weak; hard to tell backend slowness from proxy-induced delays.
- Dependency boundaries are loose; helpers reach into connector state instead of consuming small interfaces.

## Current State Snapshot
- Connector works for streaming/non-streaming; retries 429 once after `retry_after`; forces credential reload on 401.
- Thought signatures no longer inject placeholders; secondary index by tool_call_id avoids missing-signature 400s when session IDs change.
- StreamingExecutor handles SSE parsing, token refresh, retry delay extraction; RequestPreparer handles auth session + translation + prompt limits.
- Tests green: `pytest -q --maxfail=1` (8629 passed, 94 skipped).

## High-Level Goals
1) Reduce orchestration bulk in `src/connectors/gemini_base/connector.py`.
2) Clarify retry/backoff and auth-refresh policies via small strategy components.
3) Tighten DI boundaries (interfaces over concrete, remove lingering backward-compat glue where safe).
4) Make thought_signature handling cohesive and documented.
5) Improve observability for latency/retries without cluttering code paths.

## Proposed Work Items

### 1) Split Connector Orchestration
- Extract a “CodeAssistOrchestrator” (or similar) that owns the linear flow: prepare → execute (StreamingExecutor) → accumulate (for non-stream) → post-process. Keep the connector as a thin facade/adaptor to DI and stateful concerns (token manager, config).
- Move VTC wrapping and prefetch logic into a dedicated helper to shrink `_chat_completions_code_assist_streaming`.
- Ensure all helpers take narrow interfaces (IConnectorContext, IRequestPreparer, IStreamingExecutor, IResponsePostProcessor).

### 2) Retry/Backoff Strategy
- Create a small `IRetryPolicy` (or rate-limit handler) that:
  - Parses `retry_after` and optional jitter; exposes `should_retry(error, attempt)` and `sleep_seconds(error, attempt)`.
  - Handles non-streaming vs streaming consistently (one place).
  - Emits metadata for metrics (attempt count, wait time).
- Wire connector to use this policy instead of inline `retry_after` logic.

### 3) Auth Refresh Strategy
- Formalize an `IAuthRefreshPolicy` that:
  - Decides when to force reload vs normal refresh (handles 401s).
  - Centralizes the 30s timeout behavior and logging.
  - Exposes a clear return path for “auth hard failure” so callers can surface a clean error chunk in streaming.

### 4) Thought Signature Cohesion
- Keep a single service responsible for:
  - Injection (session-aware, tool_call_id-aware).
  - Storage from streaming tool calls.
  - Logging/telemetry about presence/absence.
- Ensure translation layer and the service share a small interface; document that placeholders are forbidden and only cached signatures are injected.
- Consider persisting the secondary index across requests if needed, but avoid cross-session leakage.

### 5) Observability for Latency & Retries
- Add lightweight timing logs/metrics around the streaming executor call: queue time, backend RTT, accumulate duration.
- Include retry metadata in logs (attempt, sleep seconds, retry_after).
- Keep logging at DEBUG/INFO; avoid noisy per-chunk logs.

### 6) Cleanup & DI Hardening
- Remove remaining backward-compat-only attributes if no longer needed (e.g., legacy caches) once tests confirm.
- Prefer constructor injection for services (token estimator, translation, auth provider) and avoid accessing connector state from deep helpers.
- Make sure protocols in `connector_context.py` cover the refined needs (force_reload flag already added).

## Edge Cases to Watch
- Streaming prefetch must still surface immediate errors for Resilience Layer handling; ensure the refactor preserves this behavior.
- Deduplication window: avoid re-sending identical requests; no hidden amplification loops.
- Rate-limit handling: still only one retry; do not reintroduce model fallbacks (must not failover to Flash/etc.).
- Thought signatures: never inject placeholders; only inject when cached.

## Quick Commands (for future session)
- Full tests: `./.venv/Scripts/python.exe -m pytest -q --maxfail=1`
- Targeted lint/format/mypy on touched files:
  - `./.venv/Scripts/python.exe -m ruff check --fix <files>`
  - `./.venv/Scripts/python.exe -m black <files>`
  - `./.venv/Scripts/python.exe -m mypy <files>`

## Suggested Refactor Order
1) Introduce retry/auth strategy classes (no behavior change) and wire connector to them.
2) Extract streaming orchestration helper and non-stream orchestrator; keep tests passing.
3) Consolidate thought signature service interface and update injection/storage call sites.
4) Add latency/retry observability hooks (guarded by log level).
5) Remove obsolete glue/fields after confirming tests.

## Deliverables
- Refactored connector stack with:
  - Extracted orchestration helpers and explicit retry/auth policies.
  - Consolidated thought-signature service/interface (no placeholders).
  - Added latency/retry observability hooks.
  - Tightened DI boundaries (protocol-driven).
- Updated tests (unit/integration) where behavior changes; full suite still green.
- Short summary of design changes and how to configure/extend retry/auth policies.

## Acceptance Criteria
- Full test suite passes (`./.venv/Scripts/python.exe -m pytest -q --maxfail=1`).
- No model fallbacks/failovers reintroduced; resilience layer expectations unchanged.
- 401 handling: single forced-reload retry path present and covered by tests.
- 429 handling: single retry-after wait via explicit policy; retry metadata logged at DEBUG/INFO.
- Thought signatures: only cached signatures injected; no placeholders; interface consolidated.
- Code structure: connector shrinks (orchestration extracted); policies encapsulated; helpers consume narrow interfaces.
