# Research & Design Decisions: oauth-connectors-plugin-architecture

## Summary
- **Feature**: oauth-connectors-plugin-architecture
- **Discovery Scope**: Extension (brownfield — significant existing OAuth infrastructure)
- **Key Findings** (updated 2026-04-15):
  - `oauth_detector.py` uses a **multi-layered** detection strategy: explicit `KNOWN_OAUTH_CONNECTORS` list + naming patterns (`_oauth_`, `_oauth`) + `has_static_credentials=False` property check.
  - `streaming_executor.py` has evolved to use `ITokenRefresher` protocol (`refresh_token_if_needed(force_reload=True, session_id=..., retry_after_seconds=...)`) but still contains legacy duck-typing paths for `_oauth_credentials`, `_account_selector`, and `_is_oauth_auto_refresher` helper.
  - `resilience/scope.py` maintains a hardcoded `_PERSONAL_BACKEND_TYPES` set and fallback `"oauth"` / `"codex"` substring logic.
  - `argument_parser_builder.py` contains many hardcoded debugging override flags for OAuth backends (e.g. `--enable-gemini-oauth-auto-backend-debugging-override`).
  - Core test suite still imports `llm_proxy_oauth_connectors` in several connector-behavior tests (`test_qwen_oauth_retry.py` and similar), violating desired isolation (except for narrow packaging contract tests).
  - CLI lifecycle (**default** `python -m src.core.cli`): `src/core/cli.py` imports `backend_imports` at module import time, which calls `discover_backends()` (built-in connectors + `discover_plugin_backends()`) **before** `main()` invokes `parse_cli_args()` → `ArgumentParserBuilder.build()`. A later `discover_backends()` from `ApplicationBuilder` is idempotent. **Risk path**: code that builds `ArgumentParserBuilder` without importing `cli` first skips discovery and therefore skips plugin CLI hooks unless tests call `discover_backends()` explicitly.

## Research Log

### Plugin Discovery & Capability Declaration
- **Context**: How to remove hardcoded names from `oauth_detector.py` and `scope.py` while preserving existing multi-layered detection.
- **Sources Consulted**: `src/core/domain/backend_capability_descriptor.py`, `src/core/config/models/backends.py`, `src/core/plugin_api.py`, `src/connectors/oauth_detector.py`, `src/core/common/backend_discovery_state.py`.
- **Findings**: 
  - `BackendCapabilityDescriptor` is the established pattern for declaring capabilities (`supports_streaming`, `supports_tool_calls`, etc.).
  - `oauth_detector.py` already combines naming, explicit list, and `has_static_credentials` property.
  - `backend_discovery_state.py` provides mature plugin metadata and entry-point infrastructure (`llm_proxy_backends` group).
- **Implications**: Extend `BackendCapabilityDescriptor` with `requires_personal_auth: bool = False` and `is_oauth_based: bool = False`. Update `oauth_detector.py` and `scope.py` to consult these flags **in addition to** existing neutral signals. For `connectors/__init__.py` **pre-import** filtering, mirror those semantics using registration-time plugin metadata (`BackendPluginDefinition` fields) and/or a core manifest derived from YAML (see `requirements.md` capability timing section). This removes the need for core to maintain plugin-specific name lists in code.

### Execution Decoupling
- **Context**: How to eliminate remaining duck-typing and name-based decisions in `streaming_executor.py`.
- **Sources Consulted**: `src/connectors/gemini_base/streaming_executor.py` (current `ITokenRefresher` protocol), `src/core/interfaces/`.
- **Findings**:
  - File already defines `ITokenRefresher` with `refresh_token_if_needed(...)`.
  - Legacy helper methods (`_is_oauth_auto_refresher`, `_get_oauth_auto_selection_strategy`, direct `_oauth_credentials` / `_account_selector` access via `getattr`) remain.
  - Existing pattern in codebase favors `@runtime_checkable` Protocols with methods (not properties) for reliable `isinstance()` checks.
- **Implications**: Extend/reconcile with existing `ITokenRefresher` rather than introducing fully parallel `ICredentialRotator` + `IOAuthAccountSelector`. Prefer methods over properties on protocols. Update legacy paths to use protocol methods where possible. Define missing pieces (account selection strategy, credential snapshot) in core interfaces and re-export via `plugin_api.py`.

### CLI Argument Registration & Lifecycle
- **Context**: How to allow plugins to register their own CLI arguments and configuration applicators **without** core knowing plugin names.
- **Sources Consulted**: `src/core/cli_support/argument_parser_builder.py`, `src/core/cli.py`, `src/core/common/backend_discovery_state.py`, `src/core/services/backend_plugin_discovery.py`.
- **Findings**:
  - `backend_imports` runs at **`cli.py` import time** (side effect: `discover_backends()`), which is **before** `parse_cli_args()` in the normal executable path.
  - `ApplicationBuilder` also calls `discover_backends()`; second call is a no-op unless tests reset discovery state.
  - `BackendPluginDefinition` already supports `post_build_hook`. CLI hooks are a natural extension.
  - `ConfigurationApplicator` exists but does not yet invoke plugin hooks.
- **Implications**:
  1. **Default path**: Preserve import-time discovery so `ArgumentParserBuilder.build()` can iterate registered `cli_arguments_hook`s without reordering `main()`.
  2. **Non-default paths / tests**: Document that consumers must import `src.core.cli` (or call `discover_backends()`) before building the parser when hooks matter; optionally add a thin test helper if duplication becomes noisy.
  3. Add `cli_arguments_hook` and `config_applicator_hook` to `BackendPluginDefinition` (extending existing post-build pattern).
  4. Document lifecycle contract clearly in `plugin_api.py` and `docs/development_guide/plugin-api.md`.

### Test Isolation
- **Context**: How to ensure the core test suite does not depend on the plugin package.
- **Sources Consulted**: `tests/unit/connectors/test_qwen_oauth_retry.py`, etc.
- **Findings**: Tests explicitly import `llm_proxy_oauth_connectors`.
- **Implications**: These tests must be moved to the `llm-interactive-proxy-oauth-connectors` repository. Core tests for plugin discovery should use generic mock plugins.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Capability Flags + Hooks | Extend `BackendCapabilityDescriptor` and add hooks to `BackendPluginDefinition`. | Aligns with existing plugin architecture; minimal new concepts. | Requires modifying core CLI builder. | Recommended approach. |
| Event Bus | Introduce an event system for plugins to subscribe to events (e.g., `on_cli_build`). | Highly decoupled. | Over-engineered for the current requirements; introduces significant complexity. | Rejected. |

## Design Decisions

### Decision: Capability-Based Filtering
- **Context**: Removing hardcoded plugin names from `oauth_detector.py`.
- **Alternatives Considered**:
  1. Maintain a registry of OAuth plugins.
  2. Use capability flags in `BackendCapabilityDescriptor`.
- **Selected Approach**: Use capability flags (`requires_personal_auth`, `is_oauth_based`).
- **Rationale**: Aligns with the existing capability declaration pattern and removes the need for the core to know about specific plugins.
- **Trade-offs**: Plugins must be updated to declare these capabilities.

### Decision: Dynamic CLI Argument Registration
- **Context**: Removing hardcoded CLI flags for plugins.
- **Alternatives Considered**:
  1. Parse arbitrary extra arguments.
  2. Add a `cli_arguments_hook` to `BackendPluginDefinition`.
- **Selected Approach**: Add `cli_arguments_hook` to `BackendPluginDefinition`.
- **Rationale**: Allows plugins to seamlessly integrate with the existing `argparse` setup while keeping the core clean.
- **Trade-offs**: Requires the CLI builder to iterate over plugins, which is acceptable since discovery happens before CLI building.

### Decision: Interface-Based Execution Decoupling
- **Context**: Removing duck-typing in `streaming_executor.py`.
- **Alternatives Considered**:
  1. Define explicit interfaces (`ICredentialRotator`, `IOAuthAccountSelector`).
  2. Use a generic `execute_action` method on the backend.
- **Selected Approach**: Define explicit interfaces in `src/core/interfaces/`.
- **Rationale**: Provides strong typing and clear contracts for plugin developers.
- **Trade-offs**: Requires refactoring `streaming_executor.py` and updating plugins to implement the interfaces.

## Risks & Mitigations
- **Risk**: Plugins not updated to declare capabilities or implement new interfaces.
  - **Mitigation**: Provide fallback behavior or clear error messages for legacy plugins during the transition period.
- **Risk**: CLI argument conflicts between plugins.
  - **Mitigation**: Document best practices for plugin developers to namespace their CLI arguments (e.g., `--plugin-name-feature`).

## Spec hygiene notes (2026-04-15, updated)

- **Packaging strings**: Centralized optional-distribution names (`llm-interactive-proxy-oauth-connectors`) and `pip install …[oauth]` text may remain **for diagnostics and packaging contract tests only** (see `requirements.md` §1.2 and §5). They must not drive execution or classification logic.
- **Interface reconciliation**: Proposed `ICredentialRotator`/`IOAuthAccountSelector` must be reconciled with existing `ITokenRefresher` protocol in `streaming_executor.py`. Prefer extending current patterns.
- **CLI lifecycle**: Default entry point already discovers plugins before parser build; spec text previously contradicted this. Remaining work is **hook wiring** plus **documentation/test discipline** for alternate imports (see `design.md`).
- **Deferred coupling**: Many `gemini-oauth` / name-based substring checks remain outside headline in-scope files. These stay as explicit follow-up work.
- **Steering alignment**: New plugin contracts (`BackendCapabilityDescriptor` extensions, CLI hooks, protocol usage) should be captured in `.kiro/steering/tech.md` and/or `structure.md`.
- **Cross-repo note**: Codex connector redesign (active in `dev/codex_connector_fixes_2026-04-15.md`) is a major OAuth backend. Coordination with this work is required.
