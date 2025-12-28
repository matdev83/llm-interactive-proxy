## Backend Service Refactoring — Code Review Validation

This document is the spec-aligned review record for the `backend-service-refactoring` feature. It includes a validation pass against the claim that previously reported issues were fixed.

### Validation summary (what was actually executed)

Targeted tests executed and passing:

- `./.venv/Scripts/python.exe -m pytest -q tests/unit/core/services/streaming/test_stream_formatting_service.py::TestStreamAsSSEBytes::test_stop_chunk_with_usage_emits_single_done`
- `./.venv/Scripts/python.exe -m pytest -q tests/unit/core/services/test_backend_lifecycle_manager.py::TestBackendLifecycleManagerDiscard::test_discard_with_session_id_purges_all_variants`
- `./.venv/Scripts/python.exe -m pytest -q tests/unit/core/services/test_exception_normalizer.py::TestHTTP429Translation::test_http_429_includes_headers_in_details`
- `./.venv/Scripts/python.exe -m pytest -q tests/unit/core/services/test_backend_service_api_stability.py`
- `./.venv/Scripts/python.exe -m pytest -q tests/property/core/test_backend_service_api_preservation.py`
- `./.venv/Scripts/python.exe -m pytest -q tests/property/core/test_backend_lifecycle_manager_properties.py`
Full suite verification (reported by maintainer):
- `./.venv/Scripts/python.exe -m pytest -m "unit or integration" -v` → `0 failed, 9380 passed, 93 skipped in 149.52s (0:02:29)`

#### 1) Executive verdict

- **Verdict:** Ship-with-followups
- **Top reasons:**
  - Previously reported P0/P1 issues are fixed and validated by targeted tests.
  - Legacy `_stream_as_sse_bytes` no longer instantiates formatting services inline (uses a cached instance), reducing divergence vs DI.
  - API hygiene follow-up (BackendError re-export) is fixed and validated by a stability test.
- **Highest-risk area:** SSE termination / usage-bearing stop chunks on the wire (now guarded by direct tests).

#### 2) Spec alignment

- **Spec artifacts:** `.kiro/specs/backend-service-refactoring/spec.json`, `.kiro/specs/backend-service-refactoring/requirements.md`, `.kiro/specs/backend-service-refactoring/design.md`, `.kiro/specs/backend-service-refactoring/tasks.md`
- **Traceability summary:** Requirements 1/2 are satisfied via extracted services + DI registration; Requirement 3 is enforced by signature stability tests; Requirement 11/12 behavior is enforced by unit/property tests.
- **Behavior changes vs prior implementation:** No intentional externally observable behavior changes found in the validated areas beyond fixing the previously reported bugs.

#### 3) Findings (prioritized)

- **Severity:** P0 (Resolved)
  - **Where:** `src/core/services/stream_formatting_service.py` — `StreamFormattingService.stream_as_sse_bytes` (~L24–L85)
  - **Issue (was):** `StopChunkWithUsage` could produce duplicate `[DONE]` markers because `StreamingContent.to_bytes()` already appends `[DONE]`.
  - **Fix validated:** `StopChunkWithUsage` now short-circuits after emitting `StreamingContent.to_bytes()` (`src/core/services/stream_formatting_service.py` ~L49–L62).
  - **How verified:** `tests/unit/core/services/streaming/test_stream_formatting_service.py::TestStreamAsSSEBytes::test_stop_chunk_with_usage_emits_single_done`.

- **Severity:** P1 (Resolved)
  - **Where:** `src/core/services/backend_lifecycle_manager.py` — `BackendLifecycleManager.discard` (~L178–L218)
  - **Issue (was):** When called with `session_id`, discard could fail to purge global/per-session variants, leaking instances and notifications.
  - **Fix validated:** Discard now permanently disables by `backend_type` and purges:
    - global cache key `backend_type`
    - all per-session variants `f"{backend_type}:*"`
    and unregisters/shuts down removed instances.
  - **How verified:** `tests/unit/core/services/test_backend_lifecycle_manager.py::TestBackendLifecycleManagerDiscard::test_discard_with_session_id_purges_all_variants` + `tests/property/core/test_backend_lifecycle_manager_properties.py`.

- **Severity:** P2 (Resolved)
  - **Where:** `src/core/services/exception_normalizer.py` — `ExceptionNormalizer.normalize` (~L40–L102)
  - **Issue (was):** 429 normalization copied arbitrary headers into `details`, risking information disclosure.
  - **Fix validated:** Details now include only allowlisted headers (currently `Retry-After`) (`src/core/services/exception_normalizer.py` ~L86–L97).
  - **How verified:** `tests/unit/core/services/test_exception_normalizer.py::TestHTTP429Translation::test_http_429_includes_headers_in_details`.

- **Severity:** P2 (Resolved)
  - **Where:** `src/core/services/backend_service.py` — legacy `_stream_as_sse_bytes` (~L338–L352) and `_legacy_stream_formatting_service` (~L68–L71)
  - **Issue (was):** Requirement 2.4 (“remove inline imports/instantiation from method bodies”) was violated by the legacy static helper constructing a new service.
  - **Fix validated:** `_stream_as_sse_bytes` now delegates to a cached instance (`_legacy_stream_formatting_service()`), avoiding inline instantiation in the method body.
  - **How verified:** Code inspection + `tests/unit/core/services/test_backend_service_api_stability.py`.

- **Severity:** P3 (Resolved)
  - **Where:** `src/core/interfaces/backend_service.py` / `src/core/interfaces/backend_service_interface.py`
  - **Issue (was):** `backend_service_interface.py` re-exported a different `BackendError` type than the runtime service raises (`src/core/common/exceptions.BackendError`), which could cause external callers to catch the wrong exception type.
  - **Fix validated:** `src/core/interfaces/backend_service.py` now imports and re-exports `BackendError` from `src/core/common/exceptions.py` (no local class).
  - **How verified:** `tests/unit/core/services/test_backend_service_api_stability.py::TestIBackendServiceSignatureStability::test_backend_error_reexport_is_canonical`.

#### 4) Tests & verification plan

- **Already executed (passing):** See “Validation summary”.
- **Full unit/integration suite:** Reported passing by maintainer (see “Validation summary”).

#### 5) Operational & rollout notes

- No migrations in scope.
- Streaming `[DONE]` semantics are now explicitly guarded by tests; monitor wire captures for unexpected duplicate termination markers during rollout.

#### 6) Final checklist

- [x] Spec requirements satisfied (validated for the issues reviewed here)
- [x] No known P0/P1 outstanding
- [x] Targeted tests passing
- [x] Full unit/integration suite passing (reported by maintainer)
- [x] Security review completed (header allowlisting validated)
- [ ] Observability sufficient for production (optional: add metric/log for duplicate-done detection)
- [x] Migration/rollback safe (no DB/format migrations in these fixes)
