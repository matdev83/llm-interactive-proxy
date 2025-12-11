# Requirements Document: Test Suite Fixes

## Introduction

This spec addresses the 43 failing tests in the test suite. The failures fall into three main categories:
1. Missing `logging` import in two service files (12 mypy errors)
2. Incorrect mock method name `is_enabled_for` vs `isEnabledFor` (structlog compatibility)
3. Assessment/turn counter service integration issues (30+ tests)
4. Minor issues (ruff linting, project root cleanliness)

## Glossary

- **Mypy**: Static type checker for Python
- **Structlog**: Structured logging library
- **Mock**: Test double that simulates real objects
- **Turn Counter Service**: Service that tracks conversation turns for assessment triggering
- **Assessment Service**: Service that evaluates conversation quality

## Requirements

### Requirement 1: Fix Missing Logging Imports

**User Story:** As a developer, I want the codebase to pass type checking, so that I can catch type errors early.

#### Acceptance Criteria

1. WHEN mypy runs on the source code THEN the system SHALL report zero type errors
2. WHEN the turn_counter_service module is imported THEN the system SHALL have access to the logging module
3. WHEN the structured_wire_capture_service module is imported THEN the system SHALL have access to the logging module

### Requirement 2: Fix Structlog Mock Compatibility

**User Story:** As a developer, I want tests to use the correct structlog API, so that mocks match the actual library behavior.

#### Acceptance Criteria

1. WHEN a test mocks a structlog logger THEN the mock SHALL provide the `isEnabledFor` method
2. WHEN code calls `isEnabledFor` on a logger THEN the system SHALL not raise AttributeError
3. WHEN tests run THEN the system SHALL use structlog's actual method names consistently

### Requirement 3: Fix Assessment Service Integration

**User Story:** As a developer, I want assessment and turn counter tests to pass, so that the feature works correctly.

#### Acceptance Criteria

1. WHEN assessment middleware processes requests THEN the system SHALL correctly trigger assessments at configured thresholds
2. WHEN turn counter service methods are called THEN the system SHALL execute without blocking
3. WHEN multiple sessions exist THEN the system SHALL maintain isolated state per session
4. WHEN steering messages are injected THEN the system SHALL preserve conversation context

### Requirement 4: Fix Minor Issues

**User Story:** As a developer, I want the codebase to pass all quality checks, so that the project maintains high standards.

#### Acceptance Criteria

1. WHEN ruff linter runs on src THEN the system SHALL report zero linting errors
2. WHEN checking project root THEN the system SHALL contain only approved markdown files
3. WHEN tool call reactor processes streams THEN the system SHALL deduplicate tool calls correctly
