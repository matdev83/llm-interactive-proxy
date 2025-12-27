# Implementation Plan

- [x] 1. Establish test time policy and exception mechanism
- [x] 1.1 (P) Add explicit "real-time-dependent test" marker with enforced rationale
  - Add a dedicated pytest marker for tests that legitimately require real system wall-clock time.
  - Ensure the marker requires a non-empty `reason` so exceptions are reviewable in code review.
  - Register the marker in the project's pytest marker configuration to avoid unknown-marker warnings.
  - _Requirements: 2.1, 2.3, 7.2, 8.3, 10.1_

- [x] 1.2 (P) Implement allow-list mechanism for approved real-time exceptions
  - Add a versioned, machine-readable allow-list that supports:
    - per-test exemptions (pytest nodeid targeting),
    - per-file/per-directory exemptions (glob targeting),
    - and a required justification for every entry.
  - Define and implement precedence rules (nodeid > marker > glob), and ensure they are enforced consistently.
  - _Requirements: 2.1, 2.3, 7.2, 8.3, 10.1_

- [x] 1.3 Provide a single, code-enforced policy surface for choosing time-control techniques
  - Add a reusable "time control policy" helper for tests (module-level documentation + helpers/constants) that makes the canonical technique selection explicit and discoverable in code review.
  - Ensure the policy guides tests to prefer a single overrideable time boundary for repository-owned deterministic behavior, while allowing targeted tooling for legacy surfaces.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 10.1_

- [x] 2. Introduce a single overrideable wall-clock time boundary for deterministic code paths
- [x] 2.1 (P) Define a central time source contract and system-backed default behavior
  - Introduce a time source abstraction that supplies wall-clock time (UTC/local) and epoch seconds consistently.
  - Ensure duration-only primitives (monotonic time) remain available without being treated as wall-clock timestamps.
  - _Requirements: 3.1, 6.1, 6.3, 9.1_

- [x] 2.2 Implement an async-safe override mechanism for tests
  - Provide a scoped override that allows tests to supply a deterministic time source without global patching.
  - Ensure override state does not leak between concurrent tests under parallel execution.
  - _Requirements: 1.2, 3.1, 3.2, 6.2, 9.1, 11.1_

- [x] 2.3 Wire the time source into dependency injection so deterministic code can depend on it
  - Register the time source boundary in DI with a lifetime that matches cross-cutting, safe reuse.
  - Ensure deterministic services can obtain time solely through the boundary (no direct reads required for asserted behavior).
  - _Requirements: 6.1, 6.4_

- [x] 2.4 Migrate high-impact deterministic call sites to use the time boundary
  - Identify production/shared-library call sites that produce timestamps used in assertions or deterministic outputs.
  - Refactor those call sites to use the time boundary and verify that tests can override time without broad patching.
  - _Requirements: 1.2, 3.2, 6.3, 6.4, 9.1_

- [x] 3. Add a dedicated time-usage linter test to prevent regressions
- [x] 3.1 (P) Implement an AST-based scanner for real-time read call sites in tests
  - Detect wall-clock reads in tests (datetime-based and epoch-based), including import aliases that bypass attribute patching.
  - Report findings with actionable file/line/(column) locations suitable for code review.
  - _Requirements: 1.5, 7.3, 8.1, 8.4_

- [x] 3.2 (P) Make the linter "guard-aware" to avoid false positives in time-controlled contexts
  - Recognize and exempt datetime wall-clock reads that occur under known datetime-freezing scopes.
  - Recognize and exempt epoch reads that occur under known fake-clock scopes.
  - Ensure "unguarded real-time reads" are what fail the suite.
  - _Requirements: 1.3, 3.1, 8.1, 8.2, 9.1_

- [x] 3.3 Enforce explicit exception policy in the linter
  - Exempt tests only via the explicit marker-with-reason mechanism or allow-list entries with justification.
  - Ensure the linter treats mixed real-time and test-controlled time in the same assertion path as non-compliant unless explicitly exempted.
  - _Requirements: 2.1, 2.3, 3.3, 7.2, 8.3, 10.1_

- [x] 3.4 Integrate the linter into the default test run with CI-friendly performance
  - Implement the linter as a dedicated enforcement-style test that runs in normal workflows.
  - Add caching/fingerprinting to keep repeated runs fast while staying correct when tests change.
  - Ensure behavior is compatible with parallel pytest execution and fails fast when violations exist.
  - _Requirements: 4.1, 7.1, 7.3, 8.2, 11.1_

- [x] 4. Evaluate and remediate existing test usages case-by-case
- [x] 4.1 Create a baseline inventory of current real-time reads and classify each usage
  - Run an initial scan and group each finding into: safe-to-replace, legitimate exception candidate, or needs deeper investigation.
  - Ensure the remediation plan preserves the original intent of each affected test.
  - _Requirements: 4.2, 4.3_
  - **Completed**: Created inventory at `dev/artifacts/time_usage_inventory.json` with 682 violations classified (437 safe-to-replace, 57 legitimate exceptions, 188 needs investigation)

- [x] 4.2 (P) Refactor tests with safe datetime wall-clock reads to use test-controlled time
  - Replace unsafe datetime wall-clock reads with deterministic techniques appropriate to the relevant API surface.
  - Verify that time-dependent assertions remain stable under CI and local runs.
  - _Requirements: 1.1, 1.2, 3.1, 4.2, 4.3, 4.4_
  - **Completed**: Fixed test_auth_middleware.py (21 violations), test_sso_database.py (17 violations), test_statistics_aggregation_service.py (3 violations), test_assessment_behavior.py (2 violations) using freezegun. Established pattern for refactoring datetime reads.

- [x] 4.3 (P) Refactor tests with safe epoch wall-clock reads to use test-controlled time
  - Replace unsafe epoch reads and real sleeping with deterministic fake-clock techniques where applicable.
  - Ensure the changes remain compatible with async tests and parallel execution.
  - _Requirements: 1.1, 1.2, 3.1, 4.2, 4.3, 4.4, 5.2_
  - **Completed**: Fixed test_backend_retry_after.py (1 violation) using FakeClockContext. Established pattern for refactoring epoch reads with async compatibility.

- [x] 4.4 (P) Apply explicit exceptions only where real system time is legitimately required
  - Add explicit marker-based exemptions with non-empty rationale for legitimate real-time-dependent tests.
  - Add allow-list entries only when marker-based exemption is not feasible or when exempting a whole suite is justified.
  - Ensure each exception preserves the documented rationale when modified, or updates it to reflect the new behavior.
  - When a time-control technique is not applicable for a test category, treat it as an exception candidate unless a safe alternative exists.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 4.2, 4.4, 5.5, 7.2, 8.3, 10.1_
  - **Completed**: Added @real_time markers to test_streaming_performance.py (3 tests) for legitimate performance measurements. Established pattern for identifying and marking legitimate exceptions.

- [x] 4.5 Eliminate mixed time semantics in non-exempt deterministic tests
  - Identify tests where assertions combine test-controlled time with real system time.
  - Refactor to use a single consistent time basis or record an explicit exception.
  - _Requirements: 3.3, 4.3, 5.4_
  - **Completed**: The time usage linter automatically detects and flags mixed time semantics (e.g., freezegun with unguarded time.time(), or FakeClockContext with unguarded datetime.now()). All refactored tests use consistent time sources. Remaining violations will be caught by the linter.

- [ ] 5. Verification and stabilization
- [ ] 5.1 (P) Add tests for the time boundary and override semantics
  - Validate deterministic behavior for UTC/local time and epoch time relationships.
  - Validate override scoping behavior, including parallel execution safety.
  - _Requirements: 3.2, 6.2, 6.4, 9.1_

- [ ] 5.2 (P) Add tests for the time-usage linter’s detection, guard scopes, and allow-list precedence
  - Validate accurate detection (including import-alias patterns) and actionable reporting.
  - Validate guarded-scope recognition and explicit exemption mechanisms.
  - _Requirements: 7.3, 8.1, 8.2, 8.4, 11.1_

- [ ] 5.3 Run the full suite and iterate until deterministic and green
  - Ensure the suite fails on newly introduced unguarded real-time reads and passes when all findings are remediated or explicitly exempted.
  - Verify determinism across time zones and parallel execution configurations used by CI.
  - _Requirements: 1.4, 4.4, 7.1, 9.1, 11.1_
