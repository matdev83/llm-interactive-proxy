# Concurrency Hardening Task List

Tracked follow-ups to validate there are no cross-session leaks or unintended global state in the proxy:

- [x] Session lifecycle services (`src/core/services/turn_counter_service.py`, `src/core/repositories/assessment_repository.py`) — verify state cleanup and per-session scoping.
- [x] Wire capture stack (`buffered_wire_capture_service.py`, `structured_wire_capture_service.py`, `wire_capture_service.py`) — confirm buffers are keyed and cleared per request/session.
- [x] Request processor / command context caches (`src/core/services/request_processor_service.py`) — audit dictionaries or caches retained between requests (reviewed; no persistent caches discovered).
- [x] Streaming processors and middleware (loop breaking, loop detection, think-tags, pytest detectors) — ensure any per-stream buffers or trackers reset correctly and add concurrency tests where missing.
- [x] Tool call reactor & history tracker — validate per-session scoping and locking, plus add isolation tests if needed.
- [x] Response envelope wrappers in connectors (usage calculators, streaming wrappers) — check closures for shared mutable state (OpenAI/OpenRouter identity scoping hardened with regression tests).
- [x] DI singletons that hold mutable state — review registration in `src/core/di/services.py` to confirm shared instances are safe under concurrency (cache access guarded, new concurrency tests added).
- [x] Logging / telemetry components (pytest compression, loop detection metrics) — inspect for retained session-specific data (policy metrics now computed under lock).
- [x] Dangerous command / policy services — double-check caching or normalization helpers for cross-session safety (ToolAccessPolicyService cache isolation enforced).
- [x] OAuth/token-based connectors (Qwen, ZAI, etc.) — ensure token refresh and cached data remain isolated to intended scope (connector identity handling reviewed and updated for per-call isolation).
- [x] End-to-end concurrency integration tests — add coverage that runs two simultaneous streams/requests to catch regressions.
