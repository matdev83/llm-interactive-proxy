# Design Document: oauth-connectors-plugin-architecture

## Overview

**Purpose**: This feature evolves the architecture of `llm-interactive-proxy` to treat OAuth-oriented backends as true, decoupled plugins. It removes hardcoded references, implicit contracts, and test dependencies that currently bind the core proxy to the `llm-interactive-proxy-oauth-connectors` package.

**Users**: Core system maintainers and plugin developers will utilize this to build and maintain independent, modular backend connectors.

**Impact**: Changes the current system state by replacing string-matching and duck-typing with explicit capability declarations and strongly-typed interfaces, ensuring the core remains agnostic to plugin-specific implementations in the **in-scope** paths listed under [Scope](#scope-and-deferred-work).

### Goals

- Eliminate hardcoded extracted-plugin identifiers and implicit contracts from **in-scope** core logic and from connector-behavior tests.
- Introduce a standardized capability declaration mechanism (`BackendCapabilityDescriptor`).
- Decouple **in-scope** execution logic by extending existing `ITokenRefresher` protocol and removing remaining duck-typing.
- Enable dynamic CLI argument registration and configuration application for plugins.
- Ensure **runtime** test isolation from the OAuth plugin package, with a narrow **packaging contract** exception (see `requirements.md` §5).

### Non-Goals

- Large refactors of business logic inside the OAuth plugin repository **except** what is required to adopt the new protocols, capability flags, CLI hooks, and relocated tests.
- Rewriting routing/failover globally, except where it directly reads plugin-private state or duplicate name checks called out in scope.
- In a single pass, eliminating every `backend_type` substring heuristic in the [Deferred scope](#scope-and-deferred-work) list; those are tracked as follow-up unless explicitly pulled into a task.

### Scope and deferred work

**In scope** matches `requirements.md`: `oauth_detector.py`, `scope.py`, `streaming_executor.py` (remaining duck-typing paths), CLI builder + `ConfigurationApplicator` integration, `BackendCapabilityDescriptor`, `BackendPluginDefinition` hooks, `backend_discovery_state`, `plugin_api.py` re-exports.

**Deferred (follow-up phases)**: Additional modules that still use OAuth-ish **string heuristics** are listed in `requirements.md` under “Deferred scope”. Implementation of this spec should not silently expand into those files unless a task is added.

### Cross-repository coordination

Moving connector-specific tests and any new hook implementations into `llm-interactive-proxy-oauth-connectors` requires:

- **Versioning**: Align minimum core version expected by the plugin (and optionally maximum) with existing `PluginMetadataRecord` / entry-point metadata patterns.
- **CI**: Core CI drops optional imports; plugin repo CI installs the published or editable core and runs migrated tests. Document expected checkout layout for local joint development (side-by-side clones) without encoding personal paths in the spec.
- **Release ordering**: Land capability defaults + protocols in core first where possible so plugins can adopt behind feature flags or minor bumps; document any ordering dependency in the plugin changelog.

## Architecture

### Existing Architecture Analysis

The core already has substantial OAuth infrastructure:
- `oauth_detector.py` uses **multi-layered** detection: explicit `KNOWN_OAUTH_CONNECTORS` set (6 hardcoded + dynamically resolved extracted backends via `get_extracted_backend_names()`), naming patterns (`_oauth_`, `_oauth`), substring matching against known names, and `has_static_credentials=False` property check. The module already has **partial** dynamic capability through entry-point discovery, but still unions static names.
- `streaming_executor.py` defines `ITokenRefresher` protocol (`refresh_token_if_needed(force_reload, session_id, retry_after_seconds) -> bool`) but retains legacy duck-typing helpers: `_is_oauth_auto_refresher` (checks `"oauth-auto" in backend_type` via `getattr`), `_apply_refreshed_auth_header` (accesses `_oauth_credentials` dict via `getattr`), `_get_oauth_auto_selection_strategy` / `_get_oauth_auto_available_account_count` (access `_account_selector` via `getattr`), and `_record_rate_limit` (duck-typed `getattr(token_refresher, "record_rate_limit", None)`).
- `resilience/scope.py` uses hardcoded `_PERSONAL_BACKEND_TYPES` frozenset with **7 entries** (`antigravity-oauth`, `gemini-cli-cloud-project`, `gemini-oauth-free`, `gemini-oauth-plan`, `openai-codex`, `opencode-zen`, `qwen-oauth`) plus a fallback `"oauth" in normalized or "codex" in normalized` substring heuristic. Also supports runtime config overrides via `resilience.shared_backend_types` / `resilience.personal_backend_types`.
- `argument_parser_builder.py` contains **9 hardcoded** backend-specific debugging override flags in `_add_debugging_override_arguments` (e.g. `--enable-gemini-oauth-auto-backend-debugging-override`, `--enable-kiro-oauth-auto-backend-debugging-override`). Additionally has 3 in-repo OAuth behavior flags: `--disable-gemini-oauth-fallback`, `--disable-gemini-oauth-reasoning-prompt-injection`, `--allow-oauth-auto-replacement` (deferred — see `requirements.md`).
- CLI parsing runs before full plugin discovery in the staged initialization path.
- Test suite has `pytest.importorskip("llm_proxy_oauth_connectors...")` in `test_qwen_oauth_retry.py` and `test_vendor_prefix.py`.

This spec formalizes and cleans up the remaining implicit contracts.

### Architecture Pattern & Boundary Map

**Architecture Integration**:

- **Selected pattern**: Plugin architecture with **capability flags** on `BackendCapabilityDescriptor` + **explicit `typing.Protocol` interfaces** (building on existing `ITokenRefresher`).
- **Domain/feature boundaries**: Core defines/extends contracts in `src/core/interfaces/` and re-exports stable versions via `src/core/plugin_api.py`. Plugins declare capabilities and implement protocols. Core interacts only via these contracts in in-scope paths.
- **New components rationale**: 
  - Extend `BackendCapabilityDescriptor` (`requires_personal_auth`, `is_oauth_based`) to replace name-based classification.
  - Reconcile/extend existing `ITokenRefresher` instead of creating parallel `ICredentialRotator`/`IOAuthAccountSelector` where possible.
  - Add `cli_arguments_hook` and `config_applicator_hook` to `BackendPluginDefinition` (natural extension of existing `post_build_hook`).
- **CLI lifecycle note (critical)**: Plugin discovery must complete before `ArgumentParserBuilder.build()` or a two-phase parsing strategy is required.

### Technology Stack

| Layer | Choice / Version | Role in Feature | Notes |
|-------|------------------|-----------------|-------|
| Backend / Services | Python 3.10+ | Core proxy and plugin execution | `typing.Protocol`; see [Protocol runtime checks](#protocol-runtime-checks-and-ioauthaccountselector). |
| CLI | `argparse` | Dynamic argument registration | `BackendPluginDefinition` extended with `cli_arguments_hook` and `config_applicator_hook`. |

## Requirements Traceability

| Requirement | Summary | Components | Interfaces |
|-------------|---------|------------|------------|
| 1.1–1.3 | Core independence (in-scope) | `oauth_detector.py`, `scope.py` | `BackendCapabilityDescriptor` |
| 2.1–2.3 | Capability declaration | `BackendCapabilityDescriptor` | `BackendCapabilityDescriptor` |
| 3.1–3.5 | Execution decoupling | `streaming_executor.py` | `ITokenRefresher` (relocated + extended), `ICredentialRotator`, `IOAuthAccountSelector` |
| 4.1–4.5 | Configuration and CLI | `argument_parser_builder.py`, `plugin_api.py`, `ConfigurationApplicator` | `BackendPluginDefinition`, optional schema hook |
| 5.1–5.4 | Test isolation + packaging exception | Core tests, plugin repo | N/A |

## Components and Interfaces

| Component | Domain/Layer | Intent | Req Coverage | Key Dependencies | Contracts |
|-----------|--------------|--------|--------------|------------------|-----------|
| `BackendCapabilityDescriptor` | Core Domain | Declare OAuth-related capabilities | 1, 2 | None | State |
| `BackendPluginDefinition` | Core Plugin API | Metadata + CLI/config hooks | 4 | `argparse` | API |
| `ITokenRefresher` | Core Interfaces | Token refresh (relocated from `streaming_executor.py`) | 3 | None | Protocol |
| `ICredentialRotator` | Core Interfaces | Credential rotation + rate-limit recording | 3 | extends `ITokenRefresher` | Protocol |
| `IOAuthAccountSelector` | Core Interfaces | Account selection surface | 3 | None | Protocol |
| `streaming_executor.py` | Core Execution | Execute requests using protocols | 3 | `ITokenRefresher`, `ICredentialRotator` | Service |
| `argument_parser_builder.py` | Core CLI | Build CLI parser dynamically | 4 | `BackendPluginDefinition` | Service |
| `ConfigurationApplicator` | Core CLI | Apply parsed CLI args to config | 4 | `BackendPluginDefinition` | Service |

### Core Domain

#### BackendCapabilityDescriptor

| Field | Detail |
|-------|--------|
| Intent | Extend capability descriptor with OAuth-related flags. |
| Requirements | 1.3, 2.1–2.3 |

**Responsibilities & Constraints**

- Declare whether a backend requires personal authentication.
- Declare whether a backend is OAuth-based (for discovery / scoping in scope).

**Contracts**: State

##### State model

Add `requires_personal_auth: bool = False` and `is_oauth_based: bool = False` to `BackendCapabilityDescriptor`.

**Implementation Notes**

- **Integration**: Update `oauth_detector.py` and `scope.py` to consult these flags (plus any existing neutral signals such as `has_static_credentials` on the class when supplied) instead of static connector lists for in-scope classification.
- **YAML config update**: All in-repo backends that are OAuth-based or require personal auth must have their `capability_descriptor` sections updated in config YAML templates (e.g., `gemini-oauth-plan`, `gemini-oauth-free`, `openai-codex`, etc.). This ensures the new flags are populated even without plugin hooks.

### Core Plugin API

#### BackendPluginDefinition

| Field | Detail |
|-------|--------|
| Intent | Allow plugins to register CLI arguments, apply parsed args to `AppConfig`, and optionally register config schema hooks. |
| Requirements | 4.1–4.5 |

**Responsibilities & Constraints**

- Provide hooks for plugins to inject arguments into the core `argparse.ArgumentParser` and apply the parsed arguments to `AppConfig`.
- Optional **schema extension** (REQ 4.3): support a hook such as `register_backend_config_models: Callable[..., None] | None` **or** documented convention that plugins validate their `BackendConfig.extra` payload during connector construction. Minimum bar for this spec: **one** supported approach is implemented and documented in `plugin_api.md` / docstrings—either (a) hook invoked during config model assembly for plugin-registered backend types, or (b) deferred validation only in the plugin with core passing through opaque `extra` dicts. Pick (a) if low coupling can be preserved with a narrow registry keyed by backend `type`.

**Contracts**: API

##### API Contract

```python
@dataclass(frozen=True)
class BackendPluginDefinition:
    # ... existing fields ...
    cli_arguments_hook: Callable[[argparse.ArgumentParser], None] | None = None
    config_applicator_hook: Callable[[argparse.Namespace, AppConfig], AppConfig] | None = None
    # Optional: register_backend_config_models or equivalent — see REQ 4.3 note above.
```

**Implementation Notes**

- **Integration**: Update `src/core/common/backend_discovery_state.py` to store these hooks alongside existing `_plugin_post_build_hooks`. Specifically:
  - Add `_plugin_cli_hooks: dict[str, Callable]` and `_plugin_config_hooks: dict[str, Callable]` module-level dicts (guarded by existing `_lock`).
  - Add `register_plugin_cli_hook(backend_name, hook)`, `get_plugin_cli_hooks()`, `clear_plugin_cli_hooks()` functions (mirroring existing `register_plugin_post_build_hook` / `get_plugin_post_build_hooks` / `clear_plugin_post_build_hooks` pattern).
  - Same for config hooks.
- **CLI builder**: Update `argument_parser_builder.py` to iterate registered CLI hooks in `_add_plugin_arguments`.
- **Config application**: `ConfigurationApplicator` uses a **domain-specific applicator delegation pattern** (15+ specialized applicators under `src/core/cli_support/applicators/`). Plugin hooks should be invoked as a **post-applicator phase** (after all domain applicators run) to ensure core config is stable before plugins modify it. Add a dedicated `PluginHookApplicator` or invoke hooks directly from `ConfigurationApplicator.apply_overrides` after the main applicator pipeline.
- **Validation**: Document that plugins must prefix CLI flags to avoid collisions.

### Core Interfaces

#### ITokenRefresher (relocated), ICredentialRotator & IOAuthAccountSelector

| Field | Detail |
|-------|--------|
| Intent | Formalize credential lifecycle, rotation, rate-limit recording, and account selection. |
| Requirements | 3.1–3.5 |

**Responsibilities & Constraints**

- Replace remaining duck-typing on private fields for in-scope executor paths.
- **Relocate** existing `ITokenRefresher` from `streaming_executor.py` to `src/core/interfaces/` (e.g., `backend_auth_interfaces.py`). This protocol already covers `refresh_token_if_needed(...)` and is the primary token-refresh contract.
- **Extend** with `ICredentialRotator` for credential rotation, rate-limit recording, and credential snapshot; and `IOAuthAccountSelector` for account selection strategy and count.
- **Dependency rule**: All protocols are defined under `src/core/interfaces/` for core use and **re-exported** from `src/core/plugin_api.py`. External plugins import only from `plugin_api.py`.

**Contracts**: Protocol

##### Relationship between ITokenRefresher, ICredentialRotator, and IOAuthAccountSelector

- **`ITokenRefresher`** (existing, relocated): Covers routine and forced token refresh. Already used as the typed parameter in `StreamingExecutor` methods. Remains the primary interface for token refresh.
- **`ICredentialRotator`** (new, extends `ITokenRefresher`): Adds rate-limit-aware credential rotation, credential snapshot access (replacing `_oauth_credentials` duck-typing), and rate-limit recording (replacing `_record_rate_limit` duck-typing). Implementors MUST also satisfy `ITokenRefresher`.
- **`IOAuthAccountSelector`** (new, standalone): Covers account selection strategy and available account count. Accessed separately from `ITokenRefresher` via `isinstance` checks on the same object or on a dedicated selector attribute exposed through a public method.

##### Service interface (illustrative)

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class ITokenRefresher(Protocol):
    """Relocated from streaming_executor.py to src/core/interfaces/.
    
    Already implemented by existing OAuth connectors.
    """
    async def refresh_token_if_needed(
        self,
        *,
        force_reload: bool = False,
        session_id: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> bool:
        """Refresh the OAuth token if needed. Returns True on success."""
        ...

@runtime_checkable
class ICredentialRotator(ITokenRefresher, Protocol):
    """Extended interface for credential rotation on rate limit.
    
    Adds rotation semantics, credential snapshot, and rate-limit recording
    on top of ITokenRefresher.
    """
    async def rotate_credentials_on_rate_limit(
        self,
        session_id: str | None,
        retry_after_seconds: float | None,
    ) -> bool:
        """Return True if rotation succeeded and the caller should retry.

        Return False if rotation did not occur (no-op) or failed without
        raising; callers treat False as 'do not retry based on rotation'."""
        ...

    def get_current_access_token(self) -> str | None:
        """Return the current access token for auth header construction.
        
        Replaces duck-typed access to _oauth_credentials['access_token']."""
        ...

    def record_rate_limit(
        self,
        *,
        retry_after_seconds: float | None = None,
    ) -> None:
        """Record a rate-limit event for accounting/monitoring.
        
        Replaces duck-typed getattr(token_refresher, 'record_rate_limit', None).
        May be sync or async; callers should handle both."""
        ...

@runtime_checkable
class IOAuthAccountSelector(Protocol):
    """Account selection surface for multi-account OAuth backends."""
    def get_selection_strategy(self) -> str | None:
        """Return the account selection strategy name (e.g., 'session-affinity').
        
        Migration note: replaces duck-typed access to
        token_refresher.selection_strategy and
        token_refresher._account_selector.selection_strategy."""
        ...

    def get_available_account_count(self) -> int | None:
        """Return the number of available accounts, or None if unknown.
        
        Migration note: method name standardized from the current mix of
        _account_selector.get_available_count() (method) and 
        token_refresher.available_account_count (attribute)."""
        ...
```

##### Protocol runtime checks and IOAuthAccountSelector

- Prefer **methods** (`get_*`) over `@property` on `@runtime_checkable` protocols: CPython's runtime structural checks for `isinstance` are unreliable for protocol properties in many versions.
- `IOAuthAccountSelector` does **not** require `isinstance` runtime dispatch in the current architecture (it is always accessed via a known code path from `ICredentialRotator` implementors). If this remains the case during implementation, the `@runtime_checkable` decorator is optional and can be omitted to sidestep CPython quirks. Keep it if future polymorphic dispatch is anticipated.
- If properties are required for backward compatibility during migration, avoid `isinstance` on that protocol; use `getattr` with **public** method names only as a temporary bridge, or use explicit adapter objects owned by core.

##### Migration path for current duck-typed access

| Current access pattern | Replacement |
|---|---|
| `getattr(tr, "backend_type", "")` + `"oauth-auto" in ...` | `isinstance(tr, ICredentialRotator)` |
| `getattr(tr, "_oauth_credentials", None)["access_token"]` | `tr.get_current_access_token()` (via `ICredentialRotator`) |
| `getattr(tr, "_account_selector", None).selection_strategy` | `selector.get_selection_strategy()` (via `IOAuthAccountSelector`) |
| `getattr(tr, "_account_selector", None).get_available_count()` | `selector.get_available_account_count()` (via `IOAuthAccountSelector`) |
| `getattr(tr, "record_rate_limit", None)(...)` | `tr.record_rate_limit(...)` (via `ICredentialRotator`) |
| `getattr(tr, "selection_strategy", None)` | `selector.get_selection_strategy()` (via `IOAuthAccountSelector`) |
| `getattr(tr, "available_account_count", None)` | `selector.get_available_account_count()` (via `IOAuthAccountSelector`) |

**Implementation Notes**

- **Integration**: Relocate `ITokenRefresher` from `streaming_executor.py` to `src/core/interfaces/backend_auth_interfaces.py` (or similar). Update all imports. Define `ICredentialRotator` and `IOAuthAccountSelector` in the same module. Re-export all three from `plugin_api.py`.
- **Refactor `streaming_executor.py`**: Replace `_is_oauth_auto_refresher` with `isinstance(token_refresher, ICredentialRotator)`. Replace `_apply_refreshed_auth_header` to use `ICredentialRotator.get_current_access_token()`. Replace `_get_oauth_auto_selection_strategy` / `_get_oauth_auto_available_account_count` with `IOAuthAccountSelector` method calls. Replace `_record_rate_limit` duck-typing with `ICredentialRotator.record_rate_limit()`.

### Core CLI

#### argument_parser_builder.py & ConfigurationApplicator

| Field | Detail |
|-------|--------|
| Intent | Dynamically build CLI parser and apply config including plugin arguments. |
| Requirements | 4.1–4.5 |

**Responsibilities & Constraints**

- Remove hardcoded extracted-plugin debug flags from core.
- Invoke plugin `cli_arguments_hook`s during parser build.
- Invoke plugin `config_applicator_hook`s during config application.

**Contracts**: Service

**Implementation Notes**

- **Integration**: Remove flags such as `--enable-gemini-oauth-auto-backend-debugging-override`. Add `_add_plugin_arguments` that invokes registered hooks.
- **Lifecycle ordering (critical)**: Current implementation runs `parse_cli_args()` / `ArgumentParserBuilder.build()` **before** full plugin discovery in staged initialization. This must be resolved (either move discovery earlier or adopt two-phase parsing). Documented as a key risk in `research.md`.
- **Config application**: `ConfigurationApplicator` (or a small helper invoked from it) iterates `config_applicator_hook`s with `Namespace` + `AppConfig` so plugins can inject into `BackendConfig.extra` or other extension fields.

## Testing Strategy

- **Unit tests**: `BackendCapabilityDescriptor` parses new flags; `argument_parser_builder` and `ConfigurationApplicator` invoke **mock** plugin hooks; `streaming_executor` uses mock backends implementing/extending `ITokenRefresher`. Legacy duck-typing paths are removed or guarded.
- **Integration tests**: End-to-end paths that do not import `llm_proxy_oauth_connectors`, using dummy entry points where needed.
- **Test isolation**: Move connector-behavior tests that require the real optional package to the plugin repository. Retain **packaging contract** tests listed in `requirements.md` §5 that only assert strings/metadata without importing connector modules.
