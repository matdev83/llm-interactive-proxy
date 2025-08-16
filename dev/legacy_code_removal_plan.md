# Legacy Code Removal Plan

This document outlines the plan for completely removing legacy code from the codebase, following the timeline specified in the migration guide.

## Timeline

| Phase | Date | Description |
|-------|------|-------------|
| 1. Preparation | July 2024 | Add deprecation warnings and prepare for removal |
| 2. Feature Flag Removal | September 2024 | Remove all feature flags and conditional code paths |
| 3. Adapter Removal | October 2024 | Remove all adapter classes |
| 4. Legacy Code Removal | November 2024 | Remove all legacy code |
| 5. Final Cleanup | December 2024 | Final cleanup and verification |

## Phase 1: Preparation (July 2024) - COMPLETED

- ✅ Add deprecation warnings to legacy code
- ✅ Update documentation with migration timeline
- ✅ Create tests to verify new architecture works correctly
- ✅ Ensure all new code uses the new architecture

## Phase 2: Feature Flag Removal (September 2024)

### 2.1 Remove Environment Variable Checks

- Remove all environment variable checks for feature flags:
  - `USE_NEW_SESSION_SERVICE`
  - `USE_NEW_COMMAND_SERVICE`
  - `USE_NEW_BACKEND_SERVICE`
  - `USE_NEW_REQUEST_PROCESSOR`
  - `ENABLE_DUAL_MODE`

### 2.2 Remove Conditional Code Paths

- Remove all conditional code paths that check feature flags
- Update `IntegrationBridge` to always use new services
- Remove `_hybrid_legacy_flow_with_new_services` method from `hybrid_controller.py`

### 2.3 Update Tests

- Update all tests to use the new architecture directly
- Remove tests that test feature flag behavior

## Phase 3: Adapter Removal (October 2024)

### 3.1 Remove Adapter Usage

- Remove all imports of adapter classes
- Replace any remaining adapter usage with direct service usage

### 3.2 Remove Adapter Classes

- Remove all adapter class files:
  - `src/core/adapters/legacy_backend_adapter.py`
  - `src/core/adapters/legacy_command_adapter.py`
  - `src/core/adapters/legacy_config_adapter.py`
  - `src/core/adapters/legacy_session_adapter.py`

### 3.3 Remove Adapter Package

- Remove `src/core/adapters/__init__.py`
- Remove `src/core/adapters/` directory

## Phase 4: Legacy Code Removal (November 2024)

### 4.1 Remove Legacy Modules

- Remove `src/proxy_logic.py`
- Remove `src/command_parser.py`
- Remove `src/command_processor.py`
- Remove `src/session.py`

### 4.2 Update Main Module

- Remove legacy endpoints from `src/main.py`
- Update `src/main.py` to use new architecture directly or replace it entirely with `src/core/cli.py`

### 4.3 Update Imports

- Update all imports to use new modules
- Remove any remaining imports of legacy modules

## Phase 5: Final Cleanup (December 2024)

### 5.1 Code Quality

- Run linting and formatting tools on the entire codebase
- Fix any issues identified by the tools

### 5.2 Documentation

- Update all documentation to reflect the new architecture
- Remove any references to legacy code or migration

### 5.3 Testing

- Run all tests to ensure everything still works
- Add new tests for any edge cases

## Verification Steps

After each phase, the following verification steps should be performed:

1. Run all tests to ensure they pass
2. Manually test key functionality
3. Verify that no legacy code is being used
4. Check for any remaining references to removed code

## Rollback Plan

In case of issues, the following rollback plan should be followed:

1. Revert the changes made in the current phase
2. Run all tests to ensure they pass
3. Fix the issues identified
4. Try again with a more gradual approach

## Conclusion

This plan provides a clear path for completely removing legacy code from the codebase, following the timeline specified in the migration guide. By following this plan, we can ensure a smooth transition to the new architecture without disrupting existing functionality.
