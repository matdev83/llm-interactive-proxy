# Post Code Review Instructions — `non-forwardable-message-tagging`

## Problem Statement
The `non-forwardable-message-tagging` feature is marked complete in `.kiro/specs/non-forwardable-message-tagging/tasks.md`, but implementation validation found **GO-blocking** issues that must be fixed to meet the approved requirements/design and to make the feature verifiably safe:

1. **Single-boundary enforcement is bypassable** (Requirement 7.6): there is at least one production code path that can call a backend adapter directly without passing through the non-forwardable enforcement boundary.
2. **Fail-closed behavior is not consistently upheld** for tag storage capacity (Requirement 14.3): multiple tag-at-source locations swallow exceptions, allowing the request to proceed even when tagging fails (including capacity-exceeded), which breaks session-scoped guarantees and bounded-memory guarantees.
3. **Integration tests for this feature are currently not executable** due to DI resolution errors during test app construction, which prevents validating the intended enforcement behavior end-to-end.

This document instructs the execution agent on what to fix, how to fix it, what to deliver, and what constitutes acceptance.

## Validation Findings (Concrete Evidence)
These were observed during implementation validation:

- **Backend-call bypass (Req 7.6)**
  - Direct backend call exists in: `src/core/app/controllers/__init__.py:792` (`app_state.openrouter_backend.chat_completions(...)`).
- **Tagging failures swallowed (Req 14.3 / fail-closed)**
  - Tagging blocks currently catch `Exception` and continue in:
    - `src/core/commands/service.py:176` (slash command tagging)
    - `src/core/services/response_manager_service.py:99` (command response tagging)
    - `src/core/app/middleware/assessment_middleware.py:259` (assessment steering tagging)
    - (Also review all other `tag_identities(...)` call sites in `src/` for the same pattern.)
- **Integration tests blocked by DI**
  - `tests/integration/test_non_forwardable_backend_flow.py` and `tests/integration/test_non_forwardable_entry_points.py` fail at setup because `IBackendCompletionFlow` cannot be resolved due to `IFailoverStrategy` being unregistered.

## Objectives (What Must Be True When Done)
1. **All remote backend calls** from supported entry points (HTTP, WebSocket, internal workflows) route through the **single enforcement boundary** immediately before backend invocation (Req 7.1–7.6), with **no bypasses**.
2. **Fail-closed semantics** are preserved:
   - If tagging cannot be safely applied (including capacity exceeded), the request must fail **without any remote backend call** (Req 10.1, 14.3).
3. **Feature tests exist and pass**, including unit + integration + property-based tests for this feature, and the integration tests actually run (not skipped/blocked).

## Required Deliverables
The execution agent must deliver:

1. **Code changes** removing backend-call bypasses and enforcing fail-closed tagging behavior.
2. **Test fixes/additions** ensuring:
   - the bypass cannot regress, and
   - capacity-exceeded (and other fatal tagging failures) fail closed before any backend call.
3. **Green test runs** (see Acceptance Criteria + Commands below).

## Acceptance Criteria (Must All Pass)
### A. Boundary enforcement (Req 7.6)
- No production request path can call `*.chat_completions(...)` on a connector/backend adapter without passing through the enforcement boundary.
- Specifically:
  - `src/core/app/controllers/__init__.py` must no longer contain a direct `app_state.openrouter_backend.chat_completions(...)` bypass.
- Verification:
  - Grep-based: `rg -n "\\.chat_completions\\(" src` shows no unintended call sites outside the orchestrator/connector layer.
  - Integration tests: non-forwardable filtering is exercised before capture/invocation.

### B. Fail-closed tagging (Req 14.3, 10.1)
- If `NonForwardableTagLimitExceededError` occurs while tagging (slash command, command response, or steering injection), the request fails and no backend call is performed.
- Tagging failures must not be silently swallowed in a way that permits continuing to a backend call.

### C. Tests (mandatory for GO)
- These must pass:
  - `./.venv/Scripts/python.exe -m pytest tests/unit/test_non_forwardable_*`
  - `./.venv/Scripts/python.exe -m pytest tests/integration/test_non_forwardable_*`
  - `./.venv/Scripts/python.exe -m pytest tests/property/test_non_forwardable_*`
- If this repo policy expects it for “no regressions”, also pass:
  - `./.venv/Scripts/python.exe -m pytest -m di`
  - `./.venv/Scripts/python.exe -m pytest`

### D. Style + type checks for touched files
- For every modified Python file:
  - `./.venv/Scripts/python.exe -m ruff check --fix <file>`
  - `./.venv/Scripts/python.exe -m black <file>`
  - `./.venv/Scripts/python.exe -m mypy <file-or-src-scope>`

## Implementation Guidance (How To Fix)

### 1) Remove backend-call bypass (Req 7.6)
**Goal:** ensure the controller path cannot bypass `BackendService` / `BackendCompletionFlow` enforcement.

**What to change**
- Remove the branch in `src/core/app/controllers/__init__.py` that calls:
  - `app_state.openrouter_backend.chat_completions(domain_request)`

**How to keep tests working**
- Do not use `app.state.openrouter_backend` as a test hook.
- Instead, patch via DI seams used in existing integration tests:
  - Patch `IBackendInvoker.acquire_backend(...)` to return a mock backend whose `chat_completions(...)` captures the outbound request.
  - Or override the backend registry/backends in `MockBackendStage` / test builder rather than storing a backend instance on `app.state`.

**Add a regression test**
- Add/adjust an integration test that would have used the bypass and now asserts:
  - backend call is routed through orchestrator, and
  - non-forwardable filtering is applied (or at minimum, no direct adapter call path exists).

### 2) Make tag-at-source fail closed (Req 14.3 + correctness)
**Goal:** tagging must be reliable; if it cannot be recorded safely, the request must not proceed to a backend call.

**What to change**
- Find all tag-at-source call sites (search for `tag_identities(`).
- For each call site:
  - Do **not** swallow `NonForwardableTagLimitExceededError`.
  - Prefer to treat all tagging/identity failures as fatal (raise), because failing to tag breaks future recognition and can cause leakage on history re-submission.

**Suggested pattern**
- Replace `except Exception` blocks with:
  - `except NonForwardableTagLimitExceededError: raise`
  - For other exceptions:
    - raise a fail-closed domain error (e.g., `NonForwardableEnforcementError` or another `LLMProxyError` subclass) so the request fails before any backend call.

**Add a regression test**
- Add an integration test that:
  1. configures `non_forwardable_tagging.max_identities_per_session` to a very small value (e.g., 1–2),
  2. triggers tagging that exceeds the limit (slash command + steering injection is ideal),
  3. asserts:
     - response is an error (HTTP 400 from `NonForwardableTagLimitExceededError`), and
     - the backend mock is not called.

### 3) Unblock feature integration tests (DI error)
**Goal:** `build_test_app(create_test_config())` must be able to resolve `IBackendCompletionFlow` so the integration tests can execute.

**Current observed failure**
- DI resolution crashes on optional resolution of `IFailoverStrategy`.

**Fix options (pick one; keep changes minimal and consistent)**
- Option A (minimal/local): in the failover planner factory, treat optional services as optional:
  - wrap `provider.get_service(IFailoverStrategy)` in `try/except` / `contextlib.suppress(Exception)` and set to `None` when missing.
  - do the same for any other optional `get_service(...)` calls that currently crash app construction.
- Option B (systemic): change `ServiceProvider.get_service(...)` semantics to actually return `None` when not registered (matching its docstring), and keep error enrichment working for `get_required_service(...)`.

**Required test**
- Add/adjust a test that asserts the test app can resolve `IBackendCompletionFlow` without raising.

## Task List (Phased, Toggleable)

### Phase 1 — Security/correctness blockers
- [ ] Remove the backend-call bypass in `src/core/app/controllers/__init__.py` and route all calls through the shared orchestrator/enforcement boundary (Req 7.6).
- [ ] Update tag-at-source call sites to fail closed (at minimum: never swallow `NonForwardableTagLimitExceededError`) and ensure no backend call occurs when tagging fails (Req 14.3, 10.1).
- [ ] Add/adjust regression tests for bypass removal and tag-capacity fail-closed behavior.

### Phase 2 — Make integration tests runnable
- [ ] Fix DI resolution so `IBackendCompletionFlow` is resolvable in the test app (address the `IFailoverStrategy` missing-registration crash).
- [ ] Add/adjust a DI regression test that fails if `IBackendCompletionFlow` cannot be resolved in the test builder configuration.

### Phase 3 — Feature test suite green
- [ ] Run and fix the feature suites until green: unit + integration + property tests for non-forwardable tagging.
- [ ] Run and fix DI suite (`pytest -m di`) if required by repo policy for “no regressions”.
- [ ] Verify grep-based enforcement invariants (no new bypasses; no legacy non-forwardable regex filtering reintroduced).

### Phase 4 — Regression and spec hygiene
- [ ] Run `./.venv/Scripts/python.exe -m pytest` and resolve any failures attributable to these changes (or document baseline failures with justification if they pre-existed).
- [ ] If everything is green and the feature is truly complete, reconcile spec state (update `spec.json` and/or move spec to `.kiro/specs/archive/` per `.kiro/specs/AGENTS.md`).

## Validation Commands (Copy/Paste)
Use Windows venv interpreter:

```powershell
# Focused feature suites
./.venv/Scripts/python.exe -m pytest tests/unit/test_non_forwardable_*
./.venv/Scripts/python.exe -m pytest tests/integration/test_non_forwardable_*
./.venv/Scripts/python.exe -m pytest tests/property/test_non_forwardable_*

# DI integrity (if required)
./.venv/Scripts/python.exe -m pytest -m di

# Full regression (if required)
./.venv/Scripts/python.exe -m pytest
```

