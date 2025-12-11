# Implementation Plan: Test Suite Fixes

## Task List

- [x] 1. Fix missing logging imports




  - Add `import logging` to turn_counter_service.py
  - Add `import logging` to structured_wire_capture_service.py
  - Verify mypy passes on these files
  - _Requirements: 1.1, 1.2, 1.3_
- [x] 2. Fix structlog mock compatibility




- [ ] 2. Fix structlog mock compatibility

  - Update test_logging_utils.py mock to use `isEnabledFor` instead of `is_enabled_for`
  - Run test to verify it passes
  - _Requirements: 2.1, 2.2, 2.3_
-

- [x] 3. Fix assessment service tests




  - Review failing assessment tests for common patterns
  - Fix async handling in turn counter tests
  - Fix state isolation in session tests
  - Fix steering message injection tests
  - _Requirements: 3.1, 3.2, 3.3, 3.4_
-

- [x] 4. Fix minor quality issues




  - Run ruff on src and fix any linting errors
  - Remove unapproved markdown files from project root (keep only README.md, LICENSE, CHANGELOG.md, CONTRIBUTING.md, AGENTS.md)
  - Fix tool call reactor deduplication issues
  - _Requirements: 4.1, 4.2, 4.3_
-

- [x] 5. Verify all fixes




  - Run full test suite
  - Confirm 43 fewer failures
  - Ensure no new failures introduced
  - _Requirements: All_
