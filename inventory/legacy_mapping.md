# Legacy → New Architecture Mapping

This file lists legacy artifacts found in the codebase, where they are referenced, and recommended migration actions.

## Summary
- ✅ Removed direct `app.state.<backend>` references in tests and `ApplicationFactory`. All backends are now registered via DI.
- ✅ Removed direct `app.state.session_manager` references in tests. All session access now uses DI.
- Legacy command handler interface `ILegacyCommandHandler` and many parameter handlers remain and are still used by `CommandHandlerFactory`.
- `SessionStateAdapter` and `Session` contain compatibility helpers used by both old and new command implementations.

---

## app.state legacy attributes

- ✅ `app.state.session_manager` (LegacySessionManager)
  - Status: Tests no longer directly access `app.state.session_manager`
  - All tests now use `get_session_service_from_app(app)` helper that resolves `ISessionService` through DI
  - The `LegacySessionManager` wrapper is still created in `ApplicationFactory` for backward compatibility
  - Recommendation: Eventually remove `LegacySessionManager` once all code uses DI

- `app.state.app_config` / `app.state.config`
  - Location: `src/core/app/application_factory.py` (startup)
  - Consumers: legacy modules accessing config from `app.state`.
  - Recommendation: Migrate consumers to accept `AppConfig` via DI; remove aliases after tests updated.

- `app.state.backend_type`, `app.state.command_prefix`, `app.state.force_set_project`, `app.state.*` flags
  - Location: `src/core/app/application_factory.py` (startup)
  - Recommendation: Use `AppConfig`/DI instead of `app.state` globals.

- ✅ `app.state.httpx_client`, `app.state.openai_backend`, `app.state.openrouter_backend`, `app.state.anthropic_backend`, `app.state.gemini_backend`, `app.state.zai_backend`
  - Status: Removed direct assignments to `app.state.<backend>` in `ApplicationFactory._initialize_legacy_backends`
  - All backends are now registered only in `BackendService._backends` via DI
  - Tests have been updated to use `get_backend_instance(app, name)` helper that resolves backends through DI
  
- `app.state.functional_backends`
  - Location: `src/core/app/application_factory.py` -> `_initialize_legacy_backends`
  - Still used to track which backends are functional, but backends themselves are no longer stored in `app.state`

---

## Legacy command system

- `ILegacyCommandHandler` + many concrete `*Handler` classes
  - Location: `src/core/commands/handlers/command_handler.py` and many `src/core/commands/handlers/*`
  - Consumers: `CommandHandlerFactory`, `SetCommand`/`UnsetCommand` (they still create handlers)
  - Recommendation: Choose the domain `BaseCommand` API as authoritative. Port necessary parameter handler logic into domain `SetCommand`/`UnsetCommand` handler pipeline. Remove legacy `ILegacyCommandHandler` after porting and updating tests.

- `CommandHandlerFactory` (creates legacy handlers)
  - Location: `src/core/commands/handler_factory.py`
  - Recommendation: Refactor to produce domain `BaseCommand` objects or separate an adapter that wraps legacy handlers into domain commands until removal.

---

## Session adapter and helpers

- `SessionStateAdapter`, `Session.update_state`, `Session.proxy_state`, mutable setters
  - Location: `src/core/domain/session.py`
  - Consumers: legacy handlers and tests that mutate session state
  - Recommendation: Keep `SessionStateAdapter` as transitional layer but prefer immutable `SessionState` updates via `Session.update_state`. Add tests ensuring adapter semantics remain the same.

---

## Connectors / Backends

- `OpenAIConnector._handle_streaming_response`
  - Location: `src/connectors/openai.py`
  - Issue: Handles many variants of `response.aiter_bytes()` including sync iterators and coroutine results; ensure streaming contract matches tests and `BackendService` expectations.
  - Recommendation: Standardize streaming handling and add tests mocking `httpx` responses used in unit tests.

---

## Tools and docs (for migration)

- `tools/find_legacy_code.py`, `tools/trace_imports.py`, `tools/deprecate_legacy_endpoints.py`
  - Use these to find remaining legacy imports and endpoints.

---

## Next recommended actions (short term)

1. ✅ Create a list of tests that still reference `app.state.<backend>` or `app.state.session_manager` (grep for `app.state.` in `tests/`).
   - Implemented: Added helpers `get_backend_instance` and `get_session_service_from_app` in `tests/conftest.py` and updated all tests to use them.
   - Removed direct `app.state.<backend>` assignments in `ApplicationFactory._initialize_legacy_backends`
   - Updated test fixtures to register backends via `IBackendService._backends` instead of `app.state`

2. ✅ Add adapter methods on `IBackendService` to return concrete backend instances for tests and migrate tests to use `IBackendService` resolution.
   - Implemented: All tests now use `get_backend_instance(app, name)` helper to resolve backends through DI

3. Port core parameter handlers into domain commands used by `CommandRegistry` and update `CommandHandlerFactory` to register domain commands instead of legacy handlers.

4. Add unit tests for `OpenAIConnector._handle_streaming_response` covering: a) `response.aiter_bytes()` async iterator; b) `aiter_bytes()` returns sync iterator; c) `aiter_bytes()` is a coroutine returning an iterable.

---

Created by automated inventory scan.

## Completed Migration Tasks

1. ✅ Removed direct `app.state.<backend>` assignments in `ApplicationFactory._initialize_legacy_backends`
   - All backends are now registered only in `BackendService._backends` via DI
   - The method still exists but no longer creates `app.state.openai_backend` etc.

2. ✅ Updated all tests to use DI-based helpers instead of direct `app.state` access
   - Added `get_backend_instance(app, name)` helper to resolve backends through DI
   - Added `get_session_service_from_app(app)` helper to resolve `ISessionService` through DI
   - Updated test fixtures to register backends via `IBackendService._backends` instead of `app.state`

3. ✅ Removed fallbacks to legacy code in helper functions
   - Updated `get_backend_instance` to require backends to be registered in `IBackendService._backends`
   - Updated `get_session_service_from_app` to require `ISessionService` to be registered in DI


