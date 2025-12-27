# Requirements Document

## Introduction
This specification ensures the project test suite is deterministic with respect to wall-clock time by replacing unsafe reads of real system date/time with test-controlled time where appropriate, while allowing explicitly justified exceptions where real time is legitimately required.

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Contributors maintaining tests and CI reliability
- Maintainers reviewing and approving test changes
- Operators relying on stable CI signals for releases

## Validation Notes (Non-Requirements)
- The test suite currently uses multiple time-control techniques: a fake clock utility that controls epoch time and async sleeping, and a datetime freezing utility used by several test areas.
- These mechanisms cover different time APIs (async sleep/epoch seconds vs. datetime wall-clock), so a single technique may not fully replace the other without additional work. The requirements below therefore focus on a single, consistent policy (and minimizing distinct techniques where feasible).

## Project Description (Input)
chore: fix tests using calls to get true system date/time while mocked/freezed time should be used instead

## Requirements

### Requirement 1: Eliminate Unsafe Real-Time Reads in Tests
**Objective:** As a contributor, I want tests to avoid reading real system date/time when it is not necessary, so that test outcomes are deterministic and reliable.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1. The Test Suite shall not depend on real system wall-clock date/time for expected values where a test-controlled time can be used instead.
2. When a time-dependent test is executed, the Test Suite shall obtain wall-clock date/time values from a test-controlled time source where real system time is not required to validate the behavior under test.
3. If a test contains a direct call that reads real system wall-clock date/time, then the Test Suite shall treat that usage as non-compliant unless it is explicitly documented as an approved exception.
4. When tests are run in CI, the Test Suite shall produce the same pass/fail result for time-dependent assertions given the same inputs and configured test-controlled time.
5. The Test Suite shall provide a verifiable way to identify remaining non-compliant usages of real system wall-clock date/time in tests.

#### Technical Constraints
- Must remain compatible with the existing pytest-based test runner configuration and markers.
- Must not reduce the proxy’s ability to run tests under parallel or incremental test execution modes configured in the repository.

### Requirement 2: Explicit Exceptions for Legitimate Real-Time Usage
**Objective:** As a maintainer, I want legitimate uses of real system time in tests to be explicitly identified, so that exceptions are intentional, reviewable, and limited.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1. If a test legitimately requires real system time to validate its intent, then the Test Suite shall explicitly identify the test as real-time-dependent and include a rationale.
2. When a real-time-dependent test is executed, the Test Suite shall not require frozen or mocked wall-clock time for correctness.
3. The Test Suite shall not allow implicit or undocumented real-time dependency to remain in tests.
4. When a real-time-dependent test is modified, the Test Suite shall preserve its documented rationale or update it to reflect the new behavior.

#### Technical Constraints
- Exceptions must be reviewable in code review without requiring access to CI logs or external systems.

### Requirement 3: Consistent Test-Controlled Time Semantics
**Objective:** As a contributor, I want time-controlled tests to behave consistently, so that time-dependent behavior can be asserted without flakiness.

**Priority:** P1 (High)

#### Acceptance Criteria
1. When a test uses test-controlled wall-clock time, the Test Suite shall ensure that all time reads relevant to the assertion observe the test-controlled time value.
2. While a test-controlled time context is active, the Test Suite shall ensure that time-dependent outputs produced by the system under test reflect the active test-controlled time.
3. If a test mixes test-controlled time with real system time in the same assertion path, then the Test Suite shall treat the test as non-compliant unless it is an approved exception under Requirement 2.

#### Technical Constraints
- Must not change production runtime behavior; changes are limited to tests and test seams.

### Requirement 4: Evaluate and Remediate Existing Usages Case-by-Case
**Objective:** As a maintainer, I want each existing usage of real system wall-clock date/time in tests to be evaluated individually, so that only safe and meaningful replacements are performed.

**Priority:** P1 (High)

#### Acceptance Criteria
1. The Test Suite shall not introduce new direct dependencies on real system wall-clock date/time in tests unless they meet the explicit exception criteria in Requirement 2.
2. When an existing direct real-time usage is identified in the test suite, the Test Suite shall either replace it with test-controlled time or record it as an approved exception.
3. The Test Suite shall preserve the intent of each affected test after remediation.
4. When the remediation is complete, the Test Suite shall have no undocumented direct reads of real system wall-clock date/time in tests.

#### Technical Constraints
- Must remain compatible with Windows-first development workflows and the in-repo virtual environment interpreter conventions.

### Requirement 5: Standardize Test Time Control Approach
**Objective:** As a contributor, I want a consistent and minimal set of time-control techniques for tests, so that time-dependent tests are easy to write, review, and maintain.

**Priority:** P1 (High)

#### Acceptance Criteria
1. The Test Suite shall define a single documented policy for how tests obtain test-controlled time for both wall-clock datetimes and epoch-based timestamps.
2. When a test requires test-controlled time, the Test Suite shall use the canonical technique defined by the policy for the relevant time API surface.
3. If more than one time-control technique is required to cover different time API surfaces, then the Test Suite shall document why and define clear selection criteria so tests do not choose arbitrarily.
4. The Test Suite shall minimize the number of distinct time-control techniques used for equivalent purposes.
5. When a time-control technique is not applicable to a specific test category, the Test Suite shall treat that category as a candidate for an explicit exception under Requirement 2 unless a safe alternative exists.

#### Technical Constraints
- Must be compatible with async test execution and parallel test runs.

## Non-Functional Requirements

### NFR 1: Determinism
1. The Test Suite shall produce repeatable results for time-dependent tests across different machines and time zones when using test-controlled time.

### NFR 2: Maintainability
1. The Test Suite shall make time-dependency explicit in time-dependent tests (either via test-controlled time usage or an approved exception rationale).

### NFR 3: CI Compatibility
1. When tests are run under the default CI configuration, the Test Suite shall not exhibit flakiness attributable to wall-clock date/time changes.

## Glossary
| Term | Definition |
|------|------------|
| Real system wall-clock time | Date/time value read from the executing machine’s actual clock (for example, “now” or “today”). |
| Test-controlled time | Date/time value controlled by the test environment so it can be frozen, set, or otherwise made deterministic. |
| Real-time-dependent test | A test whose intent requires using real system time (for example, measuring elapsed time in an environment-dependent way). |
| Approved exception | A documented, intentional allowance for a test to read real system time under Requirement 2. |
