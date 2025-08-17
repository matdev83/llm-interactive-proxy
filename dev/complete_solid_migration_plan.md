# Complete SOLID Migration Plan

## Overview

Despite significant progress in migrating to a SOLID architecture, there are still several legacy components and compatibility layers that need to be removed. This document outlines a comprehensive plan to complete the migration by removing all remaining legacy code and ensuring the codebase fully adheres to SOLID principles.

## Priority 1: Core Domain Model Migration

These tasks focus on completing the migration of core domain models and eliminating compatibility layers:

1. **Create Command Domain Models**
   - Create `src/core/domain/command_results.py` to replace imports from `src.commands.base`
   - Create `src/core/domain/command_context.py` to replace imports from `src.commands.base`

2. **Migrate Remaining Commands**
   - Migrate all remaining commands to new architecture in `src/core/domain/commands/`
   - Ensure all command handlers use the new domain models

## Priority 2: Remove Core Compatibility Layers

These tasks focus on removing compatibility layers that bridge between legacy and new code:

1. **Remove ProxyState Adapter**
   - Remove `src/core/domain/proxy_state_adapter.py`
   - Update any code that depends on it to use the new domain models directly

2. **Remove Config Adapter**
   - Remove `src/core/config_adapter.py`
   - Update application factory to use `AppConfig` directly

3. **Remove Session Compatibility**
   - Remove `src/session.py` compatibility wrapper
   - Update any code that depends on it to use the new session service directly

4. **Remove Proxy Logic**
   - Remove `src/proxy_logic.py` compatibility wrapper
   - Update any code that depends on it to use the new domain models directly

## Priority 3: Clean Up Integration Components

These tasks focus on cleaning up integration components that still have legacy references:

1. **Clean Up Integration Bridge**
   - Remove legacy initialization methods from `src/core/integration/bridge.py`
   - Remove legacy state synchronization methods

2. **Remove Legacy State**
   - Remove `src/core/integration/legacy_state.py`
   - Update any code that depends on it to use the new domain models directly

3. **Update Session Migration Service**
   - Update session migration service to work without legacy session references
   - Simplify to only handle migration between different versions of the new architecture

4. **Fix Anthropic Converters**
   - Fix `anthropic_converters.py` to remove legacy dependencies
   - Ensure it works with the new domain models directly

## Priority 4: Clean Up Application Factory

These tasks focus on cleaning up the application factory:

1. **Refactor Application Factory**
   - Remove legacy config loading from `src/core/app/application_factory.py`
   - Remove legacy state setup
   - Simplify configuration loading

2. **Remove Deprecated Adapters**
   - Remove deprecated adapter references in `src/core/adapters/`
   - Update any code that depends on them to use the new domain models directly

3. **Remove Main.py**
   - Ensure `main.py` is completely removed and not referenced
   - Update any code that depends on it to use the new entry points directly

## Priority 5: Update Tests

These tasks focus on updating tests to work with the new architecture:

1. **Remove Legacy Fixtures**
   - Remove `legacy_client` fixture from `tests/conftest.py`
   - Update any tests that depend on it to use the new test client directly

2. **Fix Regression Tests**
   - Update regression tests to not compare legacy vs new implementations
   - Simplify to just verify the new implementation works correctly

3. **Remove Test Legacy State**
   - Remove `tests/test_legacy_state.py` file
   - Update any tests that depend on it to use the new domain models directly

4. **Update All Tests**
   - Update all tests to use new architecture directly without legacy fixtures
   - Ensure all tests pass with the new architecture

## Priority 6: Final Verification

These tasks focus on final verification:

1. **Verify Imports**
   - Verify no imports reference legacy modules or components
   - Update any remaining imports to use the new domain models directly

2. **Update Documentation**
   - Update all documentation to reflect new architecture without legacy references
   - Ensure README, ARCHITECTURE, and other docs are up to date

3. **Run Full Test Suite**
   - Run full test suite to verify all functionality works with new architecture
   - Fix any remaining issues

## Implementation Strategy

1. **Incremental Approach**
   - Work on one component at a time
   - Ensure each component works before moving to the next

2. **Test-Driven Development**
   - Write tests for new components before implementing them
   - Ensure tests pass after implementation

3. **Dependency Management**
   - Start with components that have fewer dependencies
   - Work outward to components with more dependencies

4. **Continuous Integration**
   - Run tests after each change
   - Ensure code quality checks pass

## Success Criteria

1. **No Legacy Code**
   - No references to legacy modules or components
   - No compatibility layers

2. **All Tests Pass**
   - All tests pass without legacy dependencies
   - No deprecated warnings

3. **Clean Architecture**
   - Clear separation of concerns
   - Dependency injection throughout
   - Interface-based design

4. **Documentation**
   - Updated documentation reflecting the new architecture
   - No references to legacy components