# Design Document: Test Suite Fixes

## Overview

This design addresses 43 failing tests by fixing:
1. Missing `logging` imports (12 mypy errors)
2. Structlog mock method name mismatch
3. Assessment service integration issues
4. Minor quality issues

The fixes are straightforward and localized - no architectural changes needed.

## Architecture

No architectural changes. All fixes are localized to specific files:
- Add missing imports to two service files
- Update mock specifications in test files
- Fix assessment service test setup/teardown
- Clean up project root files

## Components and Interfaces

### Affected Components

1. **turn_counter_service.py**: Missing `import logging`
2. **structured_wire_capture_service.py**: Missing `import logging`
3. **test_logging_utils.py**: Mock uses wrong method name
4. **Assessment test files**: Need proper async handling and state isolation
5. **Project root**: Contains unapproved markdown files

### No Interface Changes

All fixes are internal - no public APIs change.

## Data Models

No data model changes required.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Import completeness
*For any* Python module that uses `logging`, importing that module should not raise NameError
**Validates: Requirements 1.2, 1.3**

### Property 2: Mock method compatibility
*For any* test that mocks a structlog logger, calling `isEnabledFor` on the mock should not raise AttributeError
**Validates: Requirements 2.1, 2.2**

### Property 3: Test isolation
*For any* test in the assessment suite, running tests in any order should produce the same results
**Validates: Requirements 3.3**

## Error Handling

All fixes address existing errors:
- Missing imports cause NameError at runtime
- Wrong mock methods cause AttributeError in tests
- Assessment tests fail due to async/state issues

No new error handling needed - we're fixing the errors.

## Testing Strategy

### Verification Approach

1. Run mypy on src - should pass with zero errors
2. Run specific failing tests - should all pass
3. Run full test suite - should have 43 fewer failures

### Unit Testing

The fixes themselves are verified by the existing failing tests passing.

### Property-Based Testing

Not applicable - these are simple fixes to existing code.
