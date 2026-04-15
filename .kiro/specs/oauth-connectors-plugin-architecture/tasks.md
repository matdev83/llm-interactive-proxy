# Implementation Plan

## Phase 1: Core Domain & Interfaces

- [ ] 1. Define Core Plugin Interfaces
- [ ] 1.1 Relocate `ITokenRefresher` and define `ICredentialRotator` and `IOAuthAccountSelector` protocols
  - Relocate existing `ITokenRefresher` from `streaming_executor.py` to `src/core/interfaces/` (e.g., `backend_auth_interfaces.py`). Update all existing imports.
  - Define `ICredentialRotator(ITokenRefresher, Protocol)` with `rotate_credentials_on_rate_limit`, `get_current_access_token`, and `record_rate_limit` methods (see `design.md` for full signatures and migration table).
  - Define `IOAuthAccountSelector` with **methods** `get_selection_strategy()` and `get_available_account_count()` (not `@property`) for reliable `@runtime_checkable` checks. Note: `@runtime_checkable` on `IOAuthAccountSelector` is optional if no polymorphic dispatch is needed.
  - Place definitions in `src/core/interfaces/` (for example `backend_auth_interfaces.py`).
  - Re-export all three protocols (`ITokenRefresher`, `ICredentialRotator`, `IOAuthAccountSelector`) from `src/core/plugin_api.py` for external plugins.
  - _Requirements: 3.1, 3.2_

- [ ] 1.2 Extend `BackendCapabilityDescriptor`
  - Add `requires_personal_auth: bool = False` and `is_oauth_based: bool = False`.
  - Pydantic v2 `model_validate` handles new fields with defaults automatically; explicit `from_dict` changes are not needed.
  - Update YAML backend config templates for **in-repo** backends that are OAuth-based or require personal auth (e.g., `gemini-oauth-plan`, `gemini-oauth-free`, `gemini-cli-cloud-project`, `openai-codex`, `antigravity-oauth`, `qwen-oauth`) to declare the new flags in their `capability_descriptor` sections.
  - _Requirements: 2.1, 2.2, 2.3_

- [ ] 1.3 Extend `BackendPluginDefinition` with registration-time capability hints, CLI hooks, and config hooks
  - Add registration-time booleans aligned with `BackendCapabilityDescriptor` (illustrative names in `design.md`: `is_oauth_based`, `requires_personal_auth`) so entry-point metadata is available **before** connector factories run and can back pre-import logic without hardcoded extracted names. Keep values consistent with each plugin’s YAML `capability_descriptor` where both exist.
  - Add `cli_arguments_hook: Callable[[argparse.ArgumentParser], None] | None = None`.
  - Add `config_applicator_hook: Callable[[argparse.Namespace, AppConfig], AppConfig] | None = None`.
  - Update `src/core/common/backend_discovery_state.py` to store and retrieve these hooks alongside existing `_plugin_post_build_hooks`:
    - Add `_plugin_cli_hooks: dict[str, Callable]` and `_plugin_config_hooks: dict[str, Callable]` module-level dicts (guarded by existing `_lock`).
    - Add `register_plugin_cli_hook` / `get_plugin_cli_hooks` / `clear_plugin_cli_hooks` (mirroring existing post-build hook pattern). Same for config hooks.
  - _Requirements: 2.4, 4.1, 4.2_

- [ ] 1.4 REQ 4.3 — Plugin-owned configuration extension
  - Implement **one** documented approach from `design.md` (narrow config-model hook **or** strict `extra`-only validation in plugins) and wire it from discovery/plugin registration.
  - Document the contract in `docs/development_guide/plugin-api.md` (or equivalent) without expanding core-owned YAML with plugin-specific defaults.
  - _Requirements: 4.3, 4.5_

## Phase 2: Core Refactoring & Decoupling

- [ ] 2. Refactor Core Discovery and Execution Logic
- [ ] 2.1 Remove hardcoded extracted-plugin names from `oauth_detector.py`
  - Refactor `is_oauth_connector` / related classification to rely on declared capability metadata (`BackendCapabilityDescriptor` when available, plus registration-time plugin flags and/or a core manifest per `requirements.md` **Capability signals and discovery timing**) instead of `KNOWN_OAUTH_CONNECTORS` / spelling rules for **in-scope** behavior.
  - Update `src/connectors/__init__.py` (pre-import skip logic) so it stays consistent with the same signals—**no** dependency on extracted logical name literals in core code.
  - _Requirements: 1.1, 1.3, 2.1, 2.2, 2.3, 2.4_

- [ ] 2.2 Remove hardcoded backend name lists from `scope.py`
  - Refactor resilience scoping to use `BackendCapabilityDescriptor.requires_personal_auth` (and related flags) instead of hardcoded backend IDs.
  - _Requirements: 1.1, 1.3, 2.3_

- [ ] 2.3 Decouple `streaming_executor.py`
  - Replace `_is_oauth_auto_refresher` / substring checks with `isinstance(..., ICredentialRotator)` and protocol calls.
  - Remove duck-typed access to `_oauth_credentials` in favor of `ICredentialRotator.get_current_access_token()`.
  - Remove duck-typed access to `_account_selector` in favor of `IOAuthAccountSelector.get_selection_strategy()` and `get_available_account_count()`.
  - Replace `_record_rate_limit` duck-typed access (`getattr(token_refresher, "record_rate_limit", None)`) with `ICredentialRotator.record_rate_limit()`.
  - Refer to migration path table in `design.md` for the full mapping of current access patterns to protocol methods.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

## Phase 3: CLI & Configuration Hooks

- [ ] 3. Implement Dynamic CLI and Configuration Hooks
- [ ] 3.1 Integrate `cli_arguments_hook` into `argument_parser_builder.py`
  - Remove hardcoded extracted-plugin debug flags from `_add_debugging_override_arguments` (or equivalent).
  - Add `_add_plugin_arguments` that reads hooks from `backend_discovery_state` and invokes them.
  - Verify the **default** `cli.py` path: import-time `backend_imports` / `discover_backends()` runs before `parse_cli_args()` → `ArgumentParserBuilder.build()`; document or fixture-test alternate paths that build the parser without importing `cli`.
  - _Requirements: 4.1, 4.4_

- [ ] 3.2 Integrate `config_applicator_hook` into `ConfigurationApplicator`
  - `ConfigurationApplicator` uses a domain-specific applicator delegation pattern (15+ specialized applicators under `src/core/cli_support/applicators/`). Plugin hooks should be invoked as a **post-applicator phase** (after all domain applicators run) via a dedicated `PluginHookApplicator` or inline invocation from `apply_overrides`.
  - Preserve deterministic ordering and immutability expectations of `AppConfig` where applicable (return updated instance as today).
  - _Requirements: 4.2, 4.5_

**Phase parallelism note**: Phase 3 (CLI & Configuration Hooks) has no dependency on Phase 2 (Core Refactoring) — they operate on different modules and can be executed in parallel if resources allow.

## Phase 4: Test Isolation & Verification

- [ ] 4. Enforce Test Isolation
- [ ] 4.1 Remove runtime plugin imports from connector behavior tests
  - Remove `pytest.importorskip("llm_proxy_oauth_connectors...")` and direct imports from connector tests not covered by the **packaging contract exception** in `requirements.md` §5.
  - Affected files: `test_qwen_oauth_retry.py`, `test_vendor_prefix.py` (L127 uses `pytest.importorskip("llm_proxy_oauth_connectors.qwen_oauth")`).
  - Move connector-specific behavior tests (for example `test_qwen_oauth_retry.py`) to `llm-interactive-proxy-oauth-connectors`; coordinate CI as in `design.md` cross-repo note.
  - For `test_vendor_prefix.py`: evaluate whether the OAuth-dependent test case should be moved to the plugin repo or refactored to use a mock.
  - _Requirements: 5.1, 5.2, 5.4_

- [ ] 4.2 Update core tests to use generic mocks
  - Update tests for `backend_plugin_discovery.py`, `streaming_executor.py`, and `argument_parser_builder.py` to use dummy entry points / mock plugins implementing the new protocols and capability flags.
  - Keep packaging contract tests that assert metadata strings without importing `llm_proxy_oauth_connectors`.
  - _Requirements: 5.1, 5.3_

## Phase 5 (Follow-up, outside initial acceptance)

Deferred-scope refactors listed in `requirements.md` (for example `chat_request_preparer.py`, `backends.py` model helpers) — track as a separate milestone after Phases 1–4 are green.
