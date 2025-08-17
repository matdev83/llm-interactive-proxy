# Legacy Adapter Removal Plan

## Overview

This document outlines the plan for removing legacy adapters from the codebase. The goal is to completely remove all legacy adapters and replace them with direct usage of the new SOLID architecture components.

## Removal Strategy

1. **Identify All Usages**: For each adapter, identify all places in the codebase where it is used.
2. **Replace Usages**: Replace each usage with direct usage of the new architecture components.
3. **Remove Adapter**: Once all usages are replaced, remove the adapter class.
4. **Update Tests**: Update tests to use the new architecture components directly.

## Adapter Removal Order

To minimize dependencies and ensure a smooth transition, we'll remove the adapters in the following order:

1. **Legacy Config Adapter**: This adapter has the fewest dependencies and is used primarily for configuration.
2. **Legacy Session Adapter**: This adapter is used for session management and depends on the config adapter.
3. **Legacy Command Adapter**: This adapter is used for command processing and depends on the session adapter.
4. **Legacy Backend Adapter**: This adapter is used for backend communication and depends on all other adapters.

## Detailed Plan for Each Adapter

### 1. Legacy Config Adapter

**File**: `src/core/adapters/legacy_config_adapter.py`

**Usages**:
- `tests/integration/test_phase1_integration.py`: Creates a config adapter for testing
- `tests/unit/core/test_config.py`: Tests conversion between legacy and new config formats

**Replacement Strategy**:
- Update tests to use `AppConfig` directly
- Remove the adapter class
- Update imports to use the new architecture components

### 2. Legacy Session Adapter

**File**: `src/core/adapters/legacy_session_adapter.py`

**Usages**:
- `tests/integration/test_phase1_integration.py`: Creates a session adapter for testing
- `tests/integration/test_phase2_integration.py`: Tests session migration

**Replacement Strategy**:
- Update tests to use the new `Session` class directly
- Remove the adapter class
- Update imports to use the new architecture components

### 3. Legacy Command Adapter

**File**: `src/core/adapters/legacy_command_adapter.py`

**Usages**:
- `tests/integration/test_phase1_integration.py`: Creates a command adapter for testing

**Replacement Strategy**:
- Update tests to use `CommandService` and command handlers directly
- Remove the adapter class
- Update imports to use the new architecture components

### 4. Legacy Backend Adapter

**File**: `src/core/adapters/legacy_backend_adapter.py`

**Usages**:
- `tests/integration/test_phase2_integration.py`: Tests the adapter directly
- `tests/regression/test_mock_backend_regression.py`: Uses the adapter for regression testing

**Replacement Strategy**:
- Update tests to use concrete implementations of `IBackendService` directly
- Remove the adapter class
- Update imports to use the new architecture components

## Legacy State Compatibility Removal

**File**: `src/core/app/legacy_state_compatibility.py`

**Usages**:
- Used extensively in integration tests to maintain backward compatibility

**Replacement Strategy**:
- Update tests to use the new architecture components directly
- Remove the compatibility layer
- Update imports to use the new architecture components

## Integration Bridge Cleanup

**File**: `src/core/integration/bridge.py`

**Usages**:
- Used extensively in integration tests to initialize both architectures

**Replacement Strategy**:
- Remove legacy initialization methods
- Update tests to use the new architecture components directly
- Simplify the bridge to only use new architecture components

## Hybrid Controller Cleanup

**File**: `src/core/integration/hybrid_controller.py`

**Usages**:
- Used in integration tests to test both architectures

**Replacement Strategy**:
- Remove legacy flow methods
- Update tests to use the new architecture controllers directly
- Simplify the controller to only use new architecture components

## Session Migration Service Cleanup

**File**: `src/core/services/session_migration_service.py`

**Usages**:
- Used in integration tests to migrate between session formats

**Replacement Strategy**:
- Update tests to use the new session service directly
- Remove migration methods
- Simplify the service to only use new architecture components

## Timeline

1. **Day 1**: Remove Legacy Config Adapter
2. **Day 2**: Remove Legacy Session Adapter
3. **Day 3**: Remove Legacy Command Adapter
4. **Day 4**: Remove Legacy Backend Adapter
5. **Day 5**: Remove Legacy State Compatibility
6. **Day 6**: Clean up Integration Bridge
7. **Day 7**: Clean up Hybrid Controller
8. **Day 8**: Clean up Session Migration Service

## Success Criteria

1. All legacy adapters are removed from the codebase
2. All tests pass using only new architecture components
3. No references to legacy adapters remain in the codebase
4. Code quality metrics show improvement
