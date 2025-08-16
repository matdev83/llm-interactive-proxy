<!-- DEPRECATED: This document has been superseded by dev/solid_refactoring_sot.md. It is kept for historical context. See that file for the authoritative plan and status. -->

# Legacy Code Cleanup Plan

## Overview

This document outlines the plan for cleaning up legacy code after the SOLID architecture migration is complete. The cleanup process will be gradual and controlled to minimize risk while improving code quality.

## Goals

1. Remove deprecated and unused code
2. Simplify the codebase for better maintainability
3. Complete the transition to the new SOLID architecture
4. Improve documentation for the new architecture

## Phase 1: Feature Flag Cleanup

### 1.1 Identify All Feature Flags

```python
# Example feature flags to be removed
USE_NEW_SESSION_SERVICE = os.getenv("USE_NEW_SESSION_SERVICE", "false").lower() == "true"
USE_NEW_COMMAND_SERVICE = os.getenv("USE_NEW_COMMAND_SERVICE", "false").lower() == "true"
USE_NEW_BACKEND_SERVICE = os.getenv("USE_NEW_BACKEND_SERVICE", "false").lower() == "true"
USE_NEW_REQUEST_PROCESSOR = os.getenv("USE_NEW_REQUEST_PROCESSOR", "false").lower() == "true"
ENABLE_DUAL_MODE = os.getenv("ENABLE_DUAL_MODE", "true").lower() == "true"
```

### 1.2 Remove Conditional Code Paths

For each feature flag, identify and clean up conditional code paths:

```python
# Before
if USE_NEW_SESSION_SERVICE:
    # New code path
    session = await session_service.get_session(session_id)
else:
    # Legacy code path
    session = session_manager.get_session(session_id)

# After
# Only keep the new code path
session = await session_service.get_session(session_id)
```

### 1.3 Update Configuration Files

Remove feature flag references from configuration files and documentation.

## Phase 2: Adapter Cleanup

### 2.1 Identify All Adapters

```
src/core/adapters/legacy_session_adapter.py
src/core/adapters/legacy_command_adapter.py
src/core/adapters/legacy_config_adapter.py
src/core/adapters/legacy_backend_adapter.py
```

### 2.2 Remove Adapter Usage

For each adapter, identify where it's used and replace with direct usage of the new components:

```python
# Before
session_adapter = create_legacy_session_adapter(legacy_session)
result = session_adapter.get_state()

# After
from src.core.domain.session import Session
session = Session(session_id=legacy_session.session_id)
result = session.state
```

### 2.3 Remove Adapter Classes

Once all usages are removed, delete the adapter classes and update imports.

## Phase 3: Remove Legacy Endpoints

### 3.1 Identify Legacy Endpoints

Use the `tools/deprecate_legacy_endpoints.py` script to identify all legacy endpoints:

```bash
python tools/deprecate_legacy_endpoints.py --list
```

### 3.2 Apply Deprecation Warnings

Add deprecation warnings to all legacy endpoints:

```bash
python tools/deprecate_legacy_endpoints.py --apply --sunset-date=2024-06-01
```

### 3.3 Create API Versioning Strategy

Define a clear versioning strategy for future API changes:

- Major version change for breaking changes (e.g., `/v3/`)
- Minor version in documentation for compatible changes
- Consider header-based version selection for advanced use cases

## Phase 4: Dead Code Removal

### 4.1 Run Dead Code Detection

Use the `tools/detect_dead_code.py` script to identify dead code:

```bash
python tools/detect_dead_code.py --min-confidence=90
```

### 4.2 Review and Remove Dead Code

For each detected item:
1. Verify it's truly unused (check for reflection, dynamic imports, etc.)
2. Document the removal reason if needed
3. Remove the code
4. Run tests to ensure nothing breaks

### 4.3 Remove Legacy Modules

Remove the following legacy modules when no longer referenced:

```
src/main.py
src/proxy_logic.py
src/session.py
src/command_parser.py
src/command_processor.py
```

## Phase 5: Documentation and Tests Update

### 5.1 Update API Documentation

Ensure all new API endpoints are fully documented:

- Update `docs/API_REFERENCE.md`
- Create examples for all endpoints
- Document any behavior changes

### 5.2 Update Tests

- Remove tests that test legacy functionality
- Update tests to use the new architecture directly
- Add comprehensive tests for the new components

### 5.3 Update Developer Documentation

- Update `docs/DEVELOPER_GUIDE.md` with new architecture details
- Create architectural diagrams for key components
- Document design decisions and patterns used

## Phase 6: Final Cleanup

### 6.1 Update Imports

Simplify import statements now that legacy code is removed:

```python
# Before
from src.core.adapters import create_legacy_session_adapter
from src.session import Session as LegacySession
from src.core.domain.session import Session as NewSession

# After
from src.core.domain.session import Session
```

### 6.2 Format and Lint

Run formatting and linting tools on the entire codebase:

```bash
python -m black src tests
python -m ruff check --fix src tests
python -m mypy src tests
```

### 6.3 Final Code Review

Conduct a comprehensive code review to ensure:
- SOLID principles are followed
- Code is well-documented
- No dead code remains
- All tests pass

## Timeline

| Phase | Estimated Time | Dependencies |
|-------|----------------|--------------|
| 1. Feature Flag Cleanup | 1 week | None |
| 2. Adapter Cleanup | 2 weeks | Phase 1 |
| 3. Remove Legacy Endpoints | 1 week | Phase 1 |
| 4. Dead Code Removal | 2 weeks | Phases 1-3 |
| 5. Documentation and Tests | 1 week | Phases 1-4 |
| 6. Final Cleanup | 1 week | Phases 1-5 |

## Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Breaking changes for clients | Medium | High | Thorough testing, gradual rollout, maintain backward compatibility |
| Removal of still-used code | Medium | High | Comprehensive tests, careful code analysis before removal |
| Performance regression | Low | Medium | Performance testing before/after, monitoring |
| Documentation gaps | Medium | Medium | Documentation review, user feedback |

## Success Criteria

1. No more legacy code or feature flags remain
2. All tests pass with 90%+ coverage
3. Code follows SOLID principles throughout
4. Documentation is complete and accurate
5. No performance regressions compared to legacy code

