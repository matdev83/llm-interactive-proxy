# Legacy Adapters Inventory

## Overview

The codebase contains several legacy adapters that bridge between the old architecture and the new SOLID architecture. These adapters need to be removed as part of the migration to the new architecture.

## Legacy Adapter Modules

### 1. `src/core/adapters/legacy_backend_adapter.py`

**Purpose**: Bridges the legacy backend system with the new `IBackendService` interface.

**Class**: `LegacyBackendAdapter`

**Replacement**: Direct usage of concrete implementations of `IBackendService` like `BackendService`.

**Usage in Tests**:
- `tests/integration/test_phase2_integration.py`: Tests the adapter directly
- `tests/regression/test_mock_backend_regression.py`: Uses the adapter for regression testing

### 2. `src/core/adapters/legacy_command_adapter.py`

**Purpose**: Wraps legacy command processing to implement `ICommandService` interface.

**Class**: `LegacyCommandAdapter`

**Replacement**: Direct usage of `CommandService` and command handlers.

**Usage in Tests**:
- `tests/integration/test_phase1_integration.py`: Creates a command adapter for testing

### 3. `src/core/adapters/legacy_config_adapter.py`

**Purpose**: Wraps legacy configuration to implement `IConfig` interface.

**Class**: `LegacyConfigAdapter`

**Replacement**: Direct usage of `AppConfig` and configuration services.

**Usage in Tests**:
- `tests/integration/test_phase1_integration.py`: Creates a config adapter for testing
- `tests/unit/core/test_config.py`: Tests conversion between legacy and new config formats

### 4. `src/core/adapters/legacy_session_adapter.py`

**Purpose**: Wraps a legacy `Session` to implement `ISession` interface.

**Class**: `LegacySessionAdapter`

**Replacement**: Direct usage of new `Session` class.

**Usage in Tests**:
- `tests/integration/test_phase1_integration.py`: Creates a session adapter for testing
- `tests/integration/test_phase2_integration.py`: Tests session migration

## Legacy State Compatibility

### 1. `src/core/app/legacy_state_compatibility.py`

**Purpose**: Provides a bridge between the new SOLID architecture and legacy tests that expect certain attributes to be available on the FastAPI app.state object.

**Classes**:
- `LegacyProxyState`: Adapts new SessionState to old interface
- `SessionCompatibilityWrapper`: Makes new Session object compatible with legacy interface
- `SessionManagerCompatibilityWrapper`: Provides sync interface for async session service
- `LegacyStateProxy`: Provides legacy state attributes by mapping to new architecture
- `EnhancedState`: Custom state class that delegates to both original state and proxy

**Replacement**: Direct usage of new architecture components.

**Usage in Tests**: Used extensively in integration tests to maintain backward compatibility.

### 2. `src/core/integration/legacy_state.py`

**Purpose**: Provides lazy initialization of backends and session manager for legacy code.

**Class**: `LazyLegacyState`

**Replacement**: Direct usage of new architecture components.

**Usage in Tests**: Used in tests that rely on legacy state initialization.

## Integration Bridge

### 1. `src/core/integration/bridge.py`

**Purpose**: Bridges between legacy and new architecture components.

**Methods**:
- `initialize_legacy_architecture()`: Initializes legacy backend objects
- `_setup_legacy_backends()`: Sets up legacy backend objects on app state
- `_setup_legacy_backends_sync()`: Sets up legacy backend objects synchronously
- `ensure_legacy_state()`: Ensures legacy state is initialized

**Replacement**: Direct usage of new architecture components.

**Usage in Tests**: Used extensively in integration tests to initialize both architectures.

### 2. `src/core/integration/hybrid_controller.py`

**Purpose**: Handles requests using both legacy and new architecture components.

**Methods**:
- `_hybrid_legacy_flow_with_new_services()`: Handles request using legacy flow but with selective new services

**Replacement**: Direct usage of new architecture controllers.

**Usage in Tests**: Used in integration tests to test both architectures.

## Session Migration Service

### 1. `src/core/services/session_migration_service.py`

**Purpose**: Handles the migration of session data from legacy format to new SOLID architecture.

**Methods**:
- `migrate_legacy_session()`: Migrates a legacy session to the new format
- `sync_session_state()`: Synchronizes state between legacy and new session formats
- `create_hybrid_session()`: Creates both legacy and new session objects that stay in sync

**Replacement**: Direct usage of new session service.

**Usage in Tests**: Used in integration tests to migrate between session formats.

## Usage Tracking Service

### 1. `src/core/services/usage_tracking_service.py`

**Purpose**: Provides a bridge between the new SOLID architecture and the legacy usage tracking system.

**Methods**:
- `track_llm_request()`: Context manager that tracks LLM request usage

**Replacement**: Direct usage of new usage tracking service.

**Usage in Tests**: Used in tests that verify usage tracking.

## Domain Model Compatibility

### 1. `src/core/domain/chat.py`

**Purpose**: Provides compatibility methods for legacy chat formats.

**Methods**:
- `to_legacy_format()`: Converts to a format compatible with the legacy code
- `from_legacy_response()`: Creates a ChatResponse from a legacy response format
- `from_legacy_chunk()`: Creates a StreamingChatResponse from a legacy chunk format

**Replacement**: Direct usage of new domain models.

**Usage in Tests**: Used in tests that verify compatibility with legacy formats.

### 2. `src/core/domain/multimodal.py`

**Purpose**: Provides compatibility methods for legacy multimodal formats.

**Methods**:
- `to_legacy_format()`: Converts to legacy format for backward compatibility
- `from_legacy_message()`: Creates a MultimodalMessage from a legacy message format

**Replacement**: Direct usage of new domain models.

**Usage in Tests**: Used in tests that verify compatibility with legacy formats.

## Configuration Compatibility

### 1. `src/core/config/app_config.py`

**Purpose**: Provides compatibility methods for legacy configuration formats.

**Methods**:
- `to_legacy_config()`: Converts to the legacy configuration format
- `from_legacy_config()`: Creates AppConfig from the legacy configuration format

**Replacement**: Direct usage of new configuration classes.

**Usage in Tests**: Used in tests that verify compatibility with legacy formats.

## Deprecated Modules

### 1. `src/proxy_logic.py`

**Purpose**: Legacy proxy state class (deprecated).

**Replacement**: New domain models and services.

### 2. `src/proxy_logic_deprecated.py`

**Purpose**: Legacy proxy logic module (deprecated).

**Replacement**: New domain models and services.
