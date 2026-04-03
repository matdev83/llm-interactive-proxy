# Coding Conventions

**Analysis Date:** 2026-04-04

## Naming Patterns

**Files:**
- Use `snake_case.py` for source and test modules, with `test_` prefix for most tests (for example `src/core/services/request_transform_pipeline.py`, `tests/unit/core/services/test_request_transform_pipeline.py`).
- Keep package directories domain-oriented and lowercase (for example `src/core/services/`, `src/core/transport/fastapi/`, `tests/property/`).
- Keep connector family suites grouped by directory and file name prefix (for example `tests/unit/openrouter_connector_tests/test_non_streaming_success.py`).

**Functions:**
- Use `snake_case` for functions and methods in production and tests (for example `load_config` in `src/core/config/app_config.py`, `test_transform_pipeline_preserves_ordering` in `tests/unit/core/services/test_request_transform_pipeline.py`).
- Prefix internal helpers with `_` (for example `_resolve_translation_service_from_provider` in `src/core/app/controllers/chat_controller.py`, `_ensure_windows_selector_event_loop_policy` in `tests/conftest.py`).

**Variables:**
- Use lowercase `snake_case` for local variables and module state (for example `transformation_order` in `tests/unit/core/services/test_request_transform_pipeline.py`, `_model_health` in `src/core/services/quality_verifier_service.py`).
- Keep constants uppercase (for example `TEST_OPENROUTER_API_BASE_URL` in `tests/unit/openrouter_connector_tests/test_non_streaming_success.py`).

**Types:**
- Use PascalCase for classes, dataclasses, and domain models (for example `AppConfig` in `src/core/config/app_config.py`, `ChatMessage` in `src/core/domain/chat.py`, `_ModelHealth` in `src/core/services/quality_verifier_service.py`).
- Prefer explicit union and generic type hints (`X | Y`, `list[T]`, `dict[str, Any]`) across source and tests (for example `src/core/services/backend_executor.py`, `tests/conftest.py`).

## Code Style

**Formatting:**
- Tool used: Black (`black==24.8.0`) configured via `pyproject.toml`.
- Key settings: line length `88` and 4-space indentation via Ruff/Black alignment in `pyproject.toml`.
- Write module and function docstrings for non-trivial units (for example `src/core/cli.py`, `src/core/services/request_transform_pipeline.py`).

**Linting:**
- Tool used: Ruff (`ruff==0.5.6`) configured in `pyproject.toml`.
- Enabled rule families: `F`, `E9`, `I`, `N`, `UP`, `B`, `SIM`, `C4`, `PIE`, `C90`, `RUF`.
- Complexity rule is active with `max-complexity = 50`, with explicit per-file debt exceptions in `pyproject.toml`.
- Type checking uses MyPy (`mypy==1.10.0`) with non-strict baseline and targeted overrides in `pyproject.toml`.

## Import Organization

**Order:**
1. Standard library imports
2. Third-party imports
3. First-party imports from `src...` (and `tests...` in tests)

**Path Aliases:**
- Not detected.
- Use absolute package imports from project root modules (for example `from src.core...` in `src/core/cli.py`, `from tests.utils...` in `tests/integration/commands/test_integration_help_command.py`).

## Error Handling

**Patterns:**
- Raise domain-specific exceptions derived from `LLMProxyError` for service/domain failures (see hierarchy in `src/core/common/exceptions.py`).
- Map domain exceptions to transport errors in adapters instead of ad-hoc controller mapping (`src/core/transport/fastapi/exception_adapters.py`).
- Use fail-open handling for non-critical middleware/transforms: catch, log with `exc_info=True`, continue pipeline (`src/core/services/request_transform_pipeline.py`).
- Prefer targeted `except` clauses first, then defensive broad fallback only where boundary safety requires it (`src/core/app/controllers/chat_controller.py`).

## Logging

**Framework:** logging (`logging.getLogger(__name__)` pattern)

**Patterns:**
- Define module-level logger in each module (for example `src/core/services/backend_executor.py`, `src/core/services/quality_verifier_service.py`).
- Guard expensive or verbose logs with `logger.isEnabledFor(...)` (for example `src/core/services/request_transform_pipeline.py`, `src/core/config/app_config.py`).
- Include structured context values in messages (for example `session_id`, model spec) rather than opaque messages (`src/core/services/backend_executor.py`, `src/core/services/quality_verifier_service.py`).

## Comments

**When to Comment:**
- Add short rationale comments for compatibility behavior, performance-sensitive paths, and defensive guards (for example backward-compatibility comments in `src/core/cli.py`; xdist/order comments in `tests/conftest.py`).
- Prefer comments explaining intent or risk, not restating obvious statements.

**JSDoc/TSDoc:**
- Not applicable.
- Python docstrings are used for public modules, classes, fixtures, and tests (for example `src/core/config/app_config.py`, `tests/integration/conftest.py`).

## Function Design

**Size:**
- Keep simple helpers short; allow larger orchestration functions in controllers/adapters/services where flow coordination is required (for example `src/core/services/backend_executor.py` vs. large controller flow in `src/core/app/controllers/chat_controller.py`).

**Parameters:**
- Prefer typed parameters with explicit domain objects (for example `ChatRequest`, `RequestContext`) and optional dependencies injected via constructor (for example `src/core/services/backend_executor.py`).

**Return Values:**
- Return typed domain envelopes/models rather than raw dicts across service boundaries (for example `ResponseEnvelope | StreamingResponseEnvelope` in `src/core/services/backend_executor.py`).

## Module Design

**Exports:**
- Use explicit `__all__` in many modules and package `__init__.py` files to define stable public surfaces (for example `src/core/services/__init__.py`, `src/core/config/app_config.py`).

**Barrel Files:**
- Use package-level `__init__.py` barrels for grouped exports (for example `src/core/commands/handlers/__init__.py`, `src/core/services/tool_call_reactor/__init__.py`).

---

*Convention analysis: 2026-04-04*
