# Research & Design Decisions

---
**Purpose**: Capture discovery findings, architectural investigations, and rationale that inform the technical design.

**Project Context**: Universal LLM Proxy - FastAPI async, DI containers, staged initialization, adapter pattern.
---

## Summary
- **Feature**: `test-system-time-mocking-fix`
- **Discovery Scope**: Extension (cross-cutting test determinism + minimal production seams)
- **Key Findings**:
  - The repo already uses two complementary time-control techniques in tests: `tests/utils/fake_clock.py` (controls `asyncio.sleep` and `time.time`) and `freezegun` (controls `datetime` wall-clock and is already a declared dependency).
  - There are many direct wall-clock reads in tests (not consistently scoped under controlled time), and there is no unified, verifiable regression guard.
  - Some production modules use `from time import time`, which bypasses patching strategies that replace `time.time` and is a recurring source of “mocked time not respected” issues.

## Research Log

### Existing Codebase Analysis
- **Components Reviewed**:
  - `tests/utils/fake_clock.py` (existing FakeClockContext)
  - Tests using `freezegun` (multiple regression/integration/live suites)
  - `src/services/test_execution_reminder/session_state.py` (uses `from time import time`)
  - `tests/unit/test_test_quality.py` (existing enforcement-style tests)
- **Patterns Identified**:
  - Fake clock is ContextVar-based and patches `asyncio.sleep` and `time.time` only.
  - `freezegun` is used with `freeze_time()` and `frozen_time.tick(...)` for deterministic “wait loops”.
  - Test suite runs with `xdist` by default; global time freezing can have unintended consequences (e.g., time-derived filenames) if applied indiscriminately.
- **Implications**:
  - One technique does not currently cover all time API surfaces; the project needs a clear policy and (ideally) a single central time access boundary so tests don’t depend on patching internals.

### Time-Control Technique Feasibility
- **Context**: User asked whether the suite can use only one time-control pattern.
- **Findings**:
  - `FakeClockContext` does not patch `datetime.now` and therefore does not cover datetime wall-clock semantics.
  - `freezegun` does not provide a native deterministic scheduler for `asyncio.sleep` the same way FakeClockContext does; it is primarily for wall-clock control.
  - Conclusion: the suite cannot realistically standardize on only one of the two existing techniques without introducing a new, unified boundary or expanding one tool’s scope significantly.
- **Implications**:
  - Design should favor a single “source of truth” clock boundary used by code under test, while still allowing targeted tools as transitional mechanisms.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Extend Existing Components | Keep relying on patching (`FakeClockContext` and `freezegun`) and standardize usage + add enforcement | Minimal production impact | Patch coverage gaps remain; patch bypass via imported aliases persists; fragile over time | Useful as a short-term bridge |
| Service + Interface | Introduce a centralized time source abstraction and route time reads through it; override in tests | Strongest long-term determinism; reduces patch brittleness; clearer contracts | Requires incremental migration of callsites; must avoid broad behavior change | Preferred for “don’t repeat this effort” goal |
| Hybrid Approach | Central time source + enforcement + selective patching in legacy tests | Balances migration cost and robustness | More moving parts during transition | Recommended rollout strategy |

## Design Decisions

### Decision: Central Time Source Boundary
- **Context**: Prevent repeated “true time sneaks into tests” cleanups by making time reads controllable and explicit.
- **Alternatives Considered**:
  1. Patch-only approach (FakeClockContext + freezegun).
  2. Central time source boundary used by code under test.
- **Selected Approach**: Central time source boundary with test override capability (plus a transitional hybrid rollout).
- **Rationale**: Reduces reliance on fragile patching; makes determinism a property of contracts rather than incidental monkeypatching; aligns with DI and explicit interfaces patterns in the repo.
- **Trade-offs**: Requires migrating production and shared helpers to use the boundary; some tests remain legitimate exceptions.
- **Follow-up**: Identify high-impact callsites first (tests and code paths that compute timestamps used in assertions).

### Decision: Exception Policy for Legitimate Real-Time Tests
- **Context**: Some tests (live/network/benchmark/time-measurement) legitimately require real time.
- **Alternatives Considered**:
  1. Ad-hoc, undocumented exceptions.
  2. A dedicated marker + required rationale and an allow-list mechanism for enforcement.
- **Selected Approach**: Dedicated marker and explicit rationale, plus an allow-list mechanism used by the regression guard.
- **Rationale**: Reviewable and enforceable, prevents “silent drift”.
- **Trade-offs**: Requires discipline and minor maintenance overhead.
- **Follow-up**: Decide marker naming and rationale format.

### Decision: Regression Guard Location and Scope
- **Context**: Prevent reintroduction of direct wall-clock reads in tests and deterministic code paths.
- **Alternatives Considered**:
  1. CI lint-only checks.
  2. A pytest “quality” test that fails with actionable file/line output.
- **Selected Approach**: pytest-based regression guard aligned with existing “test-as-enforcer” patterns.
- **Rationale**: Consistent with project conventions; produces actionable failures during normal workflows.
- **Trade-offs**: Needs careful allow-listing to avoid blocking legitimate suites.
- **Follow-up**: Define banned patterns list and exempted directories/markers.

## Testing Strategy Research

### Existing Test Patterns
- Unit tests in `tests/unit/` frequently construct timestamped models directly.
- Integration/regression tests use `freezegun` for deterministic “wait loops” (via `frozen_time.tick(...)`).
- Many async regression tests already use `FakeClockContext` to avoid sleeping and speed up deterministic scheduling.

### Risks & Mitigations
- Risk: Global freezing causes collisions for time-derived filenames and brittle cross-suite behavior.  
  Mitigation: Prefer per-test/per-suite scoping; avoid global freeze hooks.
- Risk: Imported aliases (e.g., `from time import time`) bypass patching and make determinism inconsistent.  
  Mitigation: Migrate deterministic paths to the centralized time source boundary.

## References
- `tests/utils/fake_clock.py` - Fake clock utilities
- `pyproject.toml` - `freezegun` dependency and pytest configuration
- `tests/unit/test_test_quality.py` - enforcement-style tests pattern
- `.kiro/specs/test-system-time-mocking-fix/requirements.md` - requirements and IDs

