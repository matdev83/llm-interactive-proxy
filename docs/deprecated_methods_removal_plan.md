# Deprecated Methods and Compatibility Layers Removal Plan

This document outlines the deprecated methods and compatibility layers identified in the codebase, along with a plan for their removal.

## Identified Deprecated Methods

### 1. `src/core/app/test_builder.py`

- **Method**: `_initialize_services(self, app: FastAPI, config: AppConfig) -> Any`
  - **Line**: 154
  - **Marker**: `# Return the service provider for backward compatibility`
  - **Description**: Legacy compatibility method for tests that directly call `_initialize_services`.
  - **Removal Plan**: Update all tests to use the staged initialization approach instead.

- **Method**: `_initialize_backends(self, app: FastAPI, config: AppConfig) -> None`
  - **Line**: ~170
  - **Marker**: `Using deprecated _initialize_backends method`
  - **Description**: Legacy compatibility method for tests that directly call `_initialize_backends`.
  - **Removal Plan**: Update all tests to use the staged initialization approach instead.

- **Export**: `TestApplicationBuilder` (alias)
  - **Line**: 480
  - **Marker**: `# Export TestApplicationBuilder as an alias for backwards compatibility`
  - **Description**: Alias for backward compatibility.
  - **Removal Plan**: Update all imports to use `ApplicationTestBuilder` directly.

### 2. `src/core/app/test_utils.py`

- **Fallback**: Legacy test code fallback
  - **Line**: 42
  - **Marker**: `# Fallback for legacy test code - this will be removed once all code is migrated`
  - **Description**: Fallback for legacy test code that accesses app.state directly.
  - **Removal Plan**: Update all tests to use proper DI instead of direct app.state access.

### 3. `src/core/common/logging.py`

- **Method**: `setup_logging(*args: Any, **kwargs: Any) -> None`
  - **Marker**: `Deprecated: configure logging via application bootstrap`
  - **Description**: No-op function that remains for backward compatibility with legacy entry points.
  - **Removal Plan**: Remove the function and update any code that calls it to use the application bootstrap for logging configuration.

### 4. `src/core/domain/commands/secure_base_command.py`

- **Method**: `_block_direct_state_access(self, context: Any) -> None`
  - **Line**: 157
  - **Marker**: `# This method remains for backwards compatibility`
  - **Description**: Now a no-op since security is handled by SecurityMiddleware.
  - **Removal Plan**: Remove the method and update any code that calls it to use the SecurityMiddleware instead.

### 5. `src/core/domain/responses.py`

- **Import**: Legacy imports
  - **Line**: 57
  - **Marker**: `# importing (some legacy tests refer to these names directly)`
  - **Description**: Imports maintained for backward compatibility with legacy tests.
  - **Removal Plan**: Update tests to use the correct imports directly.

### 6. `src/core/domain/session.py`

- **Methods**: Mutable convenience methods
  - **Line**: 258
  - **Marker**: `# Mutable convenience methods expected by legacy tests`
  - **Description**: Methods maintained for backward compatibility with legacy tests.
  - **Removal Plan**: Update tests to use the proper immutable methods instead.

- **Methods**: Legacy override helpers
  - **Line**: 275
  - **Marker**: `# Legacy override helpers (adapter exposes legacy property names used by tests)`
  - **Description**: Adapter methods that expose legacy property names used by tests.
  - **Removal Plan**: Update tests to use the new property names directly.

### 7. `src/core/interfaces/backend_service.py`

- **Alias**: Legacy alias
  - **Line**: 15
  - **Marker**: `# Legacy alias for backward compatibility`
  - **Description**: Alias maintained for backward compatibility.
  - **Removal Plan**: Update all imports to use the new name directly.

### 8. `src/core/persistence.py`

- **Warning**: Legacy app.state usage
  - **Line**: 133
  - **Marker**: `# Do not use legacy app.state.<backend>_backend attributes; require DI`
  - **Description**: Warning against using legacy app.state attributes directly.
  - **Removal Plan**: Update all code to use proper DI instead of direct app.state access.

### 9. `src/core/services/backend_config_provider.py`

- **Alias**: Backward compatibility alias
  - **Line**: 165
  - **Marker**: `# Alias for backward compatibility with the interface`
  - **Description**: Alias maintained for backward compatibility with the interface.
  - **Removal Plan**: Update all code to use the new name directly.

### 10. `src/core/services/backend_service.py`

- **Fallback**: Backward compatibility fallback
  - **Line**: 92
  - **Marker**: `# Fallback for backward compatibility - create with app_config`
  - **Description**: Fallback for backward compatibility when creating with app_config.
  - **Removal Plan**: Update all code to use the proper initialization method.

- **Fallback**: Backward compatibility fallback
  - **Line**: 99
  - **Marker**: `# Create a minimal AppConfig for backward compatibility`
  - **Description**: Creates a minimal AppConfig for backward compatibility.
  - **Removal Plan**: Update all code to provide the proper AppConfig.

### 11. `src/core/services/command_service.py`

- **Note**: Legacy static instance access removed
  - **Line**: 125
  - **Marker**: `# NOTE: Legacy static instance access has been removed.`
  - **Description**: Note indicating that legacy static instance access has been removed.
  - **Removal Plan**: No action needed, already removed.

### 12. `src/core/services/command_settings_service.py`

- **Note**: Legacy singleton access removed
  - **Line**: 79
  - **Marker**: `# Legacy singleton access removed. Use DI to resolve CommandSettingsService.`
  - **Description**: Note indicating that legacy singleton access has been removed.
  - **Removal Plan**: No action needed, already removed.

### 13. `src/core/services/rate_limiter.py`

- **Alias**: Backward compatibility alias
  - **Line**: 216
  - **Marker**: `# Alias for backward compatibility`
  - **Description**: Alias maintained for backward compatibility.
  - **Removal Plan**: Update all code to use the new name directly.

### 14. `src/core/services/request_processor_service.py`

- **Method**: `_process_command_result(self, command_result: ProcessedResult, session: Any) -> ResponseEnvelope`
  - **Line**: ~350
  - **Marker**: `DEPRECATED: This method is a legacy compatibility layer and should be removed`
  - **Description**: Compatibility wrapper used by legacy tests to process command-only results.
  - **Removal Plan**: Update all tests to use the proper IResponseManager interface directly.

### 15. `src/core/services/response_parser_service.py`

- **Handler**: Legacy dictionary support
  - **Line**: 96
  - **Marker**: `# Handle dictionary (for legacy support)`
  - **Description**: Handler for dictionary format for legacy support.
  - **Removal Plan**: Update all code to use the new format directly.

### 16. `src/core/services/usage_tracking_service.py`

- **Note**: Legacy context manager
  - **Line**: 185
  - **Marker**: `# DI-managed accounting (no legacy context manager)`
  - **Description**: Note indicating that DI-managed accounting is used instead of legacy context manager.
  - **Removal Plan**: No action needed, already using DI-managed accounting.

## Removal Strategy

1. **Phase 1**: Update all tests to use proper DI instead of relying on legacy compatibility methods.
   - Focus on the test files that use direct app.state access.
   - Use the test_di_utils.py utilities for consistent implementation.
   - Run the full test suite after each batch of changes to ensure no regressions.

2. **Phase 2**: Remove deprecated methods and compatibility layers.
   - Start with the methods that have the fewest dependencies.
   - Update any code that still relies on these methods to use the new approach.
   - Run the full test suite after each removal to ensure no regressions.

3. **Phase 3**: Clean up remaining legacy code markers and comments.
   - Remove all legacy code markers and comments once the associated code has been updated.
   - Run the full test suite after all changes to ensure no regressions.

## Priority Order for Removal

1. Methods that are explicitly marked as deprecated and have clear replacement instructions.
2. Fallbacks and compatibility layers that are no longer needed after test migration.
3. Aliases and convenience methods that have direct replacements.
4. Legacy code markers and comments after all associated code has been updated.
