# Quick Refactoring Checklist

Use this checklist to track progress through the refactoring.

## Pre-Flight
- [ ] Read `follow-up-refactoring-plan.md` completely
- [ ] Understand the "MUST Follow" principles
- [ ] Create feature branch: `git checkout -b fix/di-services-loc-compliance`

## Phase 1: Infrastructure (30 min)
- [ ] `mkdir src/core/di/registrations/streaming && touch __init__.py`
- [ ] `mkdir src/core/di/registrations/resilience && touch __init__.py`
- [ ] `mkdir src/core/di/registration_helpers/request_processing && touch __init__.py`

## Phase 2: streaming.py (3h)
- [ ] Extract `_session_lifecycle.py` (lines 585-955)
- [ ] Extract `_pipeline.py` (lines 75-583)
- [ ] Extract `_response.py` (lines 420-477)
- [ ] Rewrite `streaming.py` as facade
- [ ] Test: `pytest tests/unit/core/di/registrations/test_streaming_registrar.py -v`
- [ ] Verify: `wc -l streaming.py` → < 600
- [ ] Verify: `wc -l streaming/_*.py` → all < 600

## Phase 3: resilience.py (2h)
- [ ] Extract `_coordination.py` (lines 69-248)
- [ ] Extract `_backend_flow.py` (lines 20-43, 250-670)
- [ ] Rewrite `resilience.py` as facade
- [ ] Test: `pytest tests/unit/core/di/registrations/ -k resilience -v`
- [ ] Verify: `wc -l resilience.py` → < 600
- [ ] Verify: `wc -l resilience/_*.py` → all < 600

## Phase 4: core_processing.py (5h) ⚠️ COMPLEX
- [ ] Extract `_orchestration_core.py` (lines 52-310, 669-752)
  - [ ] **Refactor** `_backend_request_manager_factory()` → < 50 CC
- [ ] Extract `_backend_components.py` (lines 311-668)
  - [ ] **Refactor** `_loop_detector_factory()` → < 50 CC
- [ ] Extract `_phase_components.py` (lines 776-942)
- [ ] Rewrite `core_processing.py` as facade
- [ ] Test: `pytest tests/unit/core/di/ -v`
- [ ] Verify: `wc -l core_processing.py` → < 600
- [ ] Verify: `wc -l request_processing/_*.py` → all < 600
- [ ] Verify CC: `ruff check` → no C901 violations

## Phase 5: Quality Gates (30 min)
- [ ] Edit `dev/scripts/analyze_complexity.py` line 218: `MAX_LOC = 600`
- [ ] Edit `dev/scripts/analyze_complexity.py` lines 457-461: Delete exclusions
- [ ] Edit `pyproject.toml`: Remove `core_processing.py` C901 exclusion
- [ ] Run: `./.venv/Scripts/python.exe dev/scripts/analyze_complexity.py --validate-di-services-scope`
- [ ] **MUST** see: `[PASS] VALIDATION PASSED: All XX files meet thresholds`

## Phase 6: Final Validation (1h)
- [ ] Lint: `ruff check --fix src/core/di/`
- [ ] Format: `black src/core/di/`
- [ ] Type: `mypy src/core/di/`
- [ ] Unit tests: `pytest tests/unit/core/di/ -v` → 100% pass
- [ ] Integration: `pytest tests/integration/test_di_container_integrity.py -v` → 100% pass
- [ ] Regression: `pytest tests/regression/test_backend_service_di_regression.py -v` → 100% pass

## Phase 7: Documentation (1h)
- [ ] Update `.kiro/specs/archive/di-services-god-object-refactoring/spec.json`
  - [ ] Confirm: `"implementation_status": "complete"` is now accurate
- [ ] Add completion note to `tasks.md`
- [ ] Commit changes: `git commit -m "fix: DI services LOC compliance - split streaming/resilience/core_processing"`
- [ ] Mark this spec as **TRULY COMPLETE** ✅

## Success Metrics
- [ ] All 10 completion criteria met (see `REFACTORING_SUMMARY.md`)
- [ ] Zero test modifications required
- [ ] Zero functional changes
- [ ] Quality gate validation passes

---

**Time tracking**: Start: _____ | Finish: _____ | Total: _____h (Target: 13-16h)
