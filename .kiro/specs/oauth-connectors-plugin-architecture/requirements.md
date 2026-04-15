# Requirements Document

## Project Description (Input)

oauth-connectors-plugin-architecture — Evolve the split between `llm-interactive-proxy` and `llm-interactive-proxy-oauth-connectors` so OAuth-oriented backends behave as true plugins: the core proxy must not depend on plugin package names, enumerations, hardcoded connector lists, plugin-specific tests, or plugin-private behavior; integration should be modular, discoverable, and self-contained at the plugin boundary.

## Scope and boundaries

**Primary target**: Decouple the **extracted** optional distribution `llm-interactive-proxy-oauth-connectors` and generic OAuth **plugin** behavior from core **discovery**, **resilience scoping**, **streaming/token execution**, and **CLI / debug-flag** wiring. Replace name-based heuristics and duck-typing with `BackendCapabilityDescriptor` metadata and protocols exported from `src/core/plugin_api.py`.

**In-repo backends**: YAML `backend_type` strings for connectors shipped in this repository (for example `gemini-oauth-plan`) remain legitimate identifiers. The requirement is to stop using **spelling-based inference** and **plugin-specific lists** for *classification* and *execution* where capability metadata should drive behavior. Those backends declare the same OAuth-related flags on `BackendCapabilityDescriptor` as extracted plugins.

**In scope (initial implementation)** — aligned with `design.md` / `tasks.md` Phases 1–3:

- `src/connectors/oauth_detector.py` (multi-layered detection: `KNOWN_OAUTH_CONNECTORS` set, naming patterns, dynamic entry-point resolution via `get_extracted_backend_names()`, and `has_static_credentials` property check)
- `src/core/services/resilience/scope.py` (hardcoded `_PERSONAL_BACKEND_TYPES` frozenset with 7 entries + `"oauth" in normalized or "codex" in normalized` substring fallback)
- `src/connectors/gemini_base/streaming_executor.py` (existing `ITokenRefresher` protocol + legacy duck-typing helpers: `_is_oauth_auto_refresher`, `_apply_refreshed_auth_header` accessing `_oauth_credentials`, `_get_oauth_auto_selection_strategy`/`_get_oauth_auto_available_account_count` accessing `_account_selector`, and `_record_rate_limit` duck-typed access)
- `src/core/cli_support/argument_parser_builder.py` and `ConfigurationApplicator` (including the `_add_debugging_override_arguments` section with 9 backend-specific flags)
- Core models and plugin seams: `BackendCapabilityDescriptor`, `BackendPluginDefinition`, `src/core/common/backend_discovery_state.py`, `src/core/plugin_api.py`
- YAML backend config templates: in-repo backends must declare `requires_personal_auth` and `is_oauth_based` flags on their `capability_descriptor` sections

**Deferred scope (follow-up)**: Other `backend_type` string heuristics (for example `startswith("gemini-oauth")`) and name lists still present outside the files above, including but not limited to:

- `src/core/config/models/backends.py`
- `src/connectors/gemini_base/chat_request_preparer.py`
- `src/core/services/backend_request_preparation_service.py`
- `src/core/services/backend_completion_flow/usage_accounting_orchestrator.py`
- `src/connectors/hybrid_backend/orchestration/orchestrator.py`
- `src/connectors/utils/model_capabilities.py`, `src/connectors/gemini_base/backend_compatibility.py`
- Operator-facing copy in `src/core/cli_support/error_handler.py` when it does not affect execution branches

**Deferred CLI flags** (in-repo OAuth backend behavior, not extracted-plugin debug overrides):

- `--disable-gemini-oauth-fallback` (controls in-repo `gemini-oauth-plan`/`gemini-oauth-free` fallback behavior)
- `--disable-gemini-oauth-reasoning-prompt-injection` (controls in-repo prompt injection)
- `--allow-oauth-auto-replacement` (controls replacement safety for multi-account backends)

These flags govern **in-repo** backend connectors that happen to be OAuth-based. They are intentionally deferred from the initial implementation because they control core behavioral policies rather than plugin-specific wiring. Follow-up work should evaluate whether they belong in a plugin hook or remain core flags with capability-based gating.

Follow-up work should converge all deferred sites on the same capability metadata after headline paths are complete.

## Capability signals and discovery timing (normative)

`src/connectors/__init__.py` calls `is_oauth_connector(module_name)` **before** `importlib.import_module` for in-repo connector packages when multi-user mode skips OAuth modules. At that moment there is **no** loaded connector class and **no** parsed `BackendCapabilityDescriptor` from YAML, so requirement 1.3’s “capability metadata instead of naming conventions” must be satisfied using **equivalent declared signals** that are available **without** importing connector implementation code.

Acceptable patterns (pick **one** coherent approach per implementation; document the choice in `design.md` and `plugin_api.md`):

1. **Entry-point plugins**: declare OAuth-related booleans on `BackendPluginDefinition` (or an adjacent metadata object registered during `discover_plugin_backends`) so the core never needs extracted logical names inside `oauth_detector.py` for classification.
2. **In-repo connectors**: a **core-owned** lightweight map or small manifest keyed by module / `backend_type`, generated or maintained from the same source as YAML `capability_descriptor` templates, readable before heavy module import; **or** a documented **reorder** of discovery that preserves security expectations if connector code may run before the skip decision.
3. **Neutral structural signals** that are not marketing names (for example `has_static_credentials` on a class) remain valid **only** when the connector is already imported or the signal is exposed through one of the mechanisms above.

Interpretation: requirement 1.3 applies to **behavioral classification** in in-scope modules. Where YAML descriptors are not yet loaded, “declared capability metadata” includes plugin-definition flags and manifest-equivalent data derived from the same templates, **not** ad hoc substring checks on `backend_type` for extracted plugins.

## Requirements

### 1. Core Independence from Plugin Names

**Objective:** As a core system maintainer, I want the core proxy to be free of hardcoded plugin names, so that new plugins can be added or removed without modifying core code.

#### Acceptance Criteria

1. The system shall not contain hardcoded strings referencing specific **extracted** OAuth connector logical names (for example `"opencode-zen"`, `"kiro-oauth-auto"`) in **classification** logic in `oauth_detector.py` or `scope.py`. (User documentation and static help text may continue to mention common `backend_type` examples where they do not encode branching rules.)

2. The core shall not use the optional OAuth plugin **import path** or **module name** as a runtime discriminator in **execution** paths (request processing, streaming, token refresh, backend instance selection). **Allowed**: the centralized string constants in `backend_discovery_state.py` (`_oauth_install_command`, `_optional_oauth_package_name`) used only for **operator-facing** diagnostics (for example “install optional package X”, `pip install …[oauth]`) and for **packaging contract tests** listed under requirement 5; those strings must not drive conditional behavior beyond reporting/discovery diagnostics.

3. When filtering or categorizing connectors for behavior described in this spec’s **in-scope** modules, the system shall rely on declared capability metadata: primarily `BackendCapabilityDescriptor` where configuration is loaded, and **equivalent** capability signals described under [Capability signals and discovery timing](#capability-signals-and-discovery-timing-normative) where descriptors are not yet available (for example pre-import discovery). The system shall not use naming conventions (for example `-oauth-` suffixes) or static lists of **extracted** connector logical names for that purpose.

### 2. Capability Declaration

**Objective:** As a plugin developer, I want to declare my plugin's capabilities through a standard interface, so that the core proxy can interact with it correctly without knowing its specific type.

#### Acceptance Criteria

1. The system shall provide a standardized metadata structure by extending `BackendCapabilityDescriptor` so backends declare capabilities (including `requires_personal_auth`, `is_oauth_based`).

2. When a plugin is loaded, the system shall read its capability declarations to determine how to manage its lifecycle and authentication for in-scope flows.

3. If a backend requires personal authentication, the system shall use the generic capability flag to trigger the appropriate auth flows for in-scope flows, rather than checking the backend’s marketing name or module slug.

4. For entry-point plugins, OAuth-related capability flags needed for in-scope discovery or filtering shall be readable from the plugin’s **registration-time** metadata (for example fields on `BackendPluginDefinition` populated when the entry point is evaluated), so core code does not infer OAuth behavior from optional package import paths or connector nicknames.

### 3. Execution Decoupling

**Objective:** As an architect, I want core execution logic to interact with plugins via generic interfaces, so that the core remains agnostic to plugin-specific implementations.

**Existing infrastructure**: `streaming_executor.py` already defines `ITokenRefresher` (a `@runtime_checkable` Protocol with `refresh_token_if_needed(force_reload, session_id, retry_after_seconds) -> bool`). The spec extends/reconciles with this existing protocol rather than creating fully parallel alternatives. The `ITokenRefresher` protocol should be relocated from `streaming_executor.py` to `src/core/interfaces/` and re-exported via `plugin_api.py`.

#### Acceptance Criteria

1. The system shall define generic interfaces (for example `ICredentialRotator`, `IOAuthAccountSelector`) for behaviors currently accessed via duck-typing. Where an existing protocol covers the same concern (for example `ITokenRefresher` for credential refresh), the system shall extend or reconcile rather than create parallel interfaces. The `record_rate_limit` duck-typed access pattern must also be covered by a **synchronous** protocol method on `ICredentialRotator` (callers invoke it without `await`; implementations perform fast bookkeeping only).

2. The system shall expose these generic interfaces through the stable plugin API (`src/core/plugin_api.py`) to prevent circular dependencies.

3. When executing a request in in-scope execution paths (including `streaming_executor.py`), the system shall interact with the backend connector only through these generic interfaces for those behaviors.

4. The system shall not access private attributes or state (for example `_oauth_credentials`, `_account_selector`) of any backend connector via duck-typing or `getattr` in those paths.

5. Where a connector implements a specific interface (for example `ICredentialRotator`), the system shall invoke the interface methods without checking the connector's specific type (for example without substring checks on `backend_type` for that decision).

### 4. Configuration and CLI Independence

**Objective:** As a system operator, I want plugins to manage their own configuration and CLI flags, so that the core proxy's configuration remains clean and focused on core features.

#### Acceptance Criteria

1. The system shall provide a hook or mechanism for plugins to dynamically register their own CLI arguments (for example into `argparse`) during the startup phase.

2. The system shall provide a hook or mechanism for plugins to apply their parsed CLI arguments to the application configuration (for example via `ConfigurationApplicator`).

3. The system shall provide a mechanism for plugins to supply **additional** typed configuration fragments for their own backends (for example registering Pydantic models or JSON Schema fragments merged under each plugin backend’s config subtree, or documented extension fields validated by the plugin at construction). The core remains responsible for loading the shared `AppConfig` shell; plugins own validation of their private sections.

4. The core system shall not define CLI flags specific to individual extracted OAuth plugins (for example `--enable-gemini-oauth-auto-backend-debugging-override` in `argument_parser_builder.py`).

5. The core system shall not ship **default YAML instances** or **schemas** dedicated to individual extracted OAuth plugins under core-owned config templates beyond neutral placeholders; plugin-owned defaults live with the plugin or under documented `extra` keys applied via hooks.

### 5. Test Isolation

**Objective:** As a developer, I want the core proxy's test suite to avoid **runtime** coupling to the OAuth plugin package for connector behavior tests, so that tests can run without importing optional connector code while packaging remains verifiable.

#### Packaging contract exception

The following **do not** violate acceptance criterion 1 below when they **do not** import `llm_proxy_oauth_connectors`: tests that assert optional-dependency wiring, install command strings, or discovery-state constants against `pyproject.toml` / metadata. Examples: `tests/unit/core/common/test_oauth_packaging_contract.py`, `tests/unit/core/common/test_backend_discovery_state.py` (install hint assertions), `tests/unit/core/services/test_backend_discovery.py` / `test_backend_discovery_service.py` when only string expectations for packaging metadata are involved. Discovery unit tests may use **string** module names and fake entry points to simulate a plugin without importing the real package.

#### Acceptance Criteria

1. Except for the **packaging contract exception** above, the core test suite shall not import or attempt to import `llm_proxy_oauth_connectors` (including `pytest.importorskip("llm_proxy_oauth_connectors...")`) for connector behavior, streaming, or retry logic.

2. The core test suite shall not contain tests that specifically target the **behavior** of individual extracted OAuth connectors (for example `test_qwen_oauth_retry.py`, `test_vendor_prefix.py` when it uses `pytest.importorskip("llm_proxy_oauth_connectors.qwen_oauth")`); those belong in `llm-interactive-proxy-oauth-connectors`.

3. When testing plugin discovery or execution logic in core, tests shall use generic mock or dummy plugins.

4. The system shall ensure tests that assert extracted OAuth connector **runtime behavior** reside in the `llm-interactive-proxy-oauth-connectors` repository (coordinated releases; see `design.md` cross-repo note).
