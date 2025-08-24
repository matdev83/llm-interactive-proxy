# Legacy Modules Crosswalk

This document maps legacy modules to their modern replacements in the new SOLID-based architecture.

## Top-Level Legacy Modules

| Legacy Module | Modern Replacement | Status | Notes |
|---------------|-------------------|--------|-------|
| `src/anthropic_router.py` | `src/core/app/controllers/anthropic_controller.py` | Ready for removal | Used only in `src/core/app/controllers/__init__.py` for backward compatibility endpoints. |
| `src/command_parser.py` | `src/core/services/command_processor_service.py` | Not ready for removal | Still imported by many test files. Provides compatibility layer for tests. |
| `src/command_processor.py` | `src/core/services/command_processor_service.py` | Not ready for removal | Imported by `src/command_parser.py` and test files. |
| `src/anthropic_converters.py` | `src/core/transport/adapters/anthropic_adapters.py` | Not ready for removal | Used by `anthropic_router.py` and potentially other modules. |
| `src/anthropic_models.py` | `src/core/domain/anthropic_models.py` | Not ready for removal | Used by `anthropic_router.py` and potentially other modules. |

## Legacy Interface Modules

| Legacy Module | Modern Replacement | Status | Notes |
|---------------|-------------------|--------|-------|
| `src/core/interfaces/backend_service_interface.py` | `src/core/interfaces/backend_service.py` | Consolidated | Now re-exports from canonical interface. |
| `src/core/interfaces/configuration_interface.py` | `src/core/interfaces/configuration.py` | Consolidated | Now re-exports from canonical interface. |

## Legacy Bridge Components

| Legacy Component | Modern Replacement | Status | Notes |
|------------------|-------------------|--------|-------|
| `LegacyCommandAdapter` in `src/core/services/secure_command_factory.py` | Direct DI usage | Removed | Was unreferenced and removed. |
| `CommandRegistry.get_instance()` in `src/core/services/command_service.py` | DI-managed CommandRegistry | Modified | Softened to internal test hook. |
| Legacy usage tracking bridge in `src/core/services/usage_tracking_service.py` | Direct `llm_accounting_utils` | Removed | Replaced with DI-managed service. |

## Migration Plan

1. **Phase 1: Consolidate Interfaces** (Completed)
   - Consolidate duplicate interfaces
   - Fix interface implementations
   - Update imports to use canonical interfaces

2. **Phase 2: Remove Bridge Components** (Completed)
   - Remove `LegacyCommandAdapter`
   - Refactor `CommandRegistry.get_instance()`
   - Replace usage tracking bridge

3. **Phase 3: Migrate Tests** (In Progress)
   - Migrate tests off `build_app_compat`
   - Update tests to use new interfaces and services

4. **Phase 4: Remove Legacy Modules** (Pending)
   - Remove `anthropic_router.py` once controllers are updated
   - Remove `command_parser.py` and `command_processor.py` once tests are updated
   - Remove other legacy modules once dependencies are resolved

5. **Phase 5: Clean Configuration** (Pending)
   - Clean `AppConfig` and loader of legacy flags/shapes
   - Tighten `ChatController` to strict `ChatRequest` inputs

## Next Steps

1. Update `src/core/app/controllers/__init__.py` to use `AnthropicController` instead of importing from `anthropic_router.py`
2. Create compatibility shims for test files that import from `command_parser.py` and `command_processor.py`
3. Gradually migrate tests to use the new interfaces and services
