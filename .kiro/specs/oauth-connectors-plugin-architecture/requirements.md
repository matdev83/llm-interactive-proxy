# Requirements Document

## Project Description (Input)

oauth-connectors-plugin-architecture — Evolve the split between `llm-interactive-proxy` and `llm-interactive-proxy-oauth-connectors` so OAuth-oriented backends behave as true plugins: the core proxy must not depend on plugin package names, enumerations, hardcoded connector lists, plugin-specific tests, or plugin-private behavior; integration should be modular, discoverable, and self-contained at the plugin boundary.

## Scope and boundaries

**Primary target**: Decouple the **extracted** optional distribution `llm-interactive-proxy-oauth-connectors` and generic OAuth **plugin** behavior from core **discovery**, **resilience scoping**, **streaming/token execution**, and **CLI / debug-flag** wiring. Replace name-based heuristics and duck-typing with capability metadata and stable protocols exported from `src/core/plugin_api.py`.

**In-repo backends**: YAML `backend_type` strings for connectors shipped in this repository remain valid identifiers. The requirement is to stop using spelling-based inference and plugin-specific lists for classification and execution where capability metadata should drive behavior. Those backends declare the same OAuth-related capability flags as extracted plugins.

**In scope (initial implementation)**:

- OAuth classification and discovery behavior
- Resilience scoping for personal-auth backends
- Streaming and token-execution behavior
- CLI registration and configuration application for plugins
- Core plugin seams and capability models
- YAML capability flags for in-repo OAuth-oriented backends

**Deferred scope (follow-up)**:

- Other `backend_type` heuristics outside the in-scope modules
- Operator-facing copy that does not affect branching behavior
- In-repo OAuth policy flags such as `--disable-gemini-oauth-fallback`, `--disable-gemini-oauth-reasoning-prompt-injection`, and `--allow-oauth-auto-replacement`

## Discovery-time capability constraint

Some discovery paths may need to decide whether a connector is OAuth-oriented before importing the connector implementation. At that point, runtime connector instances and loaded YAML-backed capability descriptors may not yet exist.

For those paths, the system shall use only capability signals that are available when the classification decision is made. Those signals may come from registration-time plugin metadata, core-readable capability metadata for in-repo connectors, or other neutral public signals that do not require private implementation access. The system shall not rely on extracted plugin name literals, package import paths, or substring-based marketing-name inference for that decision.

## Requirements

### 1. Core Independence from Plugin Names

**Objective:** As a core system maintainer, I want the core proxy to be free of hardcoded plugin names, so that new plugins can be added or removed without modifying core code.

#### Acceptance Criteria

1. When the core classifies OAuth-oriented backends in the in-scope paths, the system shall not use hardcoded strings referencing specific extracted OAuth connector logical names.
2. When the core presents user documentation or static help text, the system may mention common `backend_type` examples only where those examples do not control behavioral branching.
3. When the core executes request processing, streaming, token refresh, or backend instance selection, the system shall not use the optional OAuth plugin import path or module name as a runtime discriminator.
4. Where packaging diagnostics or packaging-contract tests require package-identifying strings, the system shall keep those strings isolated from runtime behavioral branching.
5. When the in-scope modules filter or categorize connectors after configuration has been loaded, the system shall use declared capability metadata from `BackendCapabilityDescriptor`.
6. When an in-scope discovery decision occurs before configuration-backed descriptors are available, the system shall use equivalent declared capability signals that are available at that decision point.
7. When the core classifies or categorizes extracted OAuth connectors in the in-scope modules, the system shall not rely on naming conventions or static lists of extracted connector logical names for that decision.

### 2. Capability Declaration

**Objective:** As a plugin developer, I want to declare my plugin's capabilities through a standard interface, so that the core proxy can interact with it correctly without knowing its specific type.

#### Acceptance Criteria

1. The system shall provide a standardized metadata structure by extending `BackendCapabilityDescriptor` so backends can declare OAuth-related capabilities, including `requires_personal_auth` and `is_oauth_based`.
2. When a plugin is loaded for an in-scope flow, the system shall read its declared capabilities to determine the plugin's lifecycle and authentication behavior.
3. When a backend requires personal authentication, the system shall use the declared capability flag to trigger the appropriate in-scope authentication behavior.
4. When the core evaluates a backend that does not require personal authentication, the system shall not infer personal-auth behavior from the backend's marketing name or module slug.
5. When an entry-point plugin must be classified during discovery or filtering, the system shall make the needed OAuth-related capability flags available through registration-time plugin metadata.
6. Where registration-time plugin metadata is used for OAuth classification, the system shall not infer OAuth behavior from optional package import paths or connector nicknames.

### 3. Execution Decoupling

**Objective:** As an architect, I want core execution logic to interact with plugins via generic interfaces, so that the core remains agnostic to plugin-specific implementations.

**Existing infrastructure**: `streaming_executor.py` already defines `ITokenRefresher`, a runtime-checkable protocol covering token refresh. This spec extends and relocates that contract rather than introducing an overlapping refresh abstraction.

#### Acceptance Criteria

1. The system shall define generic interfaces for the credential-refresh, credential-rotation, rate-limit bookkeeping, and account-selection behaviors currently reached through duck-typing.
2. Where an existing protocol already covers one of those behaviors, the system shall extend or reconcile that protocol rather than introduce a parallel contract for the same concern.
3. The system shall expose the in-scope execution interfaces through the stable plugin API in `src/core/plugin_api.py`.
4. When the core executes an in-scope request path, the system shall interact with the backend connector through the published interfaces for the covered behaviors.
5. When the core performs those in-scope execution behaviors, the system shall not access private attributes or private nested state of backend connectors through duck-typing or `getattr`.
6. Where a connector implements a supported execution interface, the system shall invoke the interface methods without checking the connector's specific type or backend marketing name.

### 4. Configuration and CLI Independence

**Objective:** As a system operator, I want plugins to manage their own configuration and CLI flags, so that the core proxy's configuration remains clean and focused on core features.

#### Acceptance Criteria

1. When the application starts, the system shall provide a mechanism for plugins to dynamically register their own CLI arguments.
2. When CLI arguments have been parsed, the system shall provide a mechanism for plugins to apply their parsed CLI values to application configuration.
3. Where a plugin owns private configuration fragments, the system shall provide a mechanism for the plugin to own validation of those fragments without requiring core-owned plugin-specific schemas or default YAML instances.
4. When the core defines CLI flags, the system shall not define flags specific to individual extracted OAuth plugins.
5. When the core ships configuration templates or schemas, the system shall not ship default YAML instances or schemas dedicated to individual extracted OAuth plugins beyond neutral extension points.

### 5. Test Isolation

**Objective:** As a developer, I want the core proxy's test suite to avoid runtime coupling to the OAuth plugin package for connector behavior tests, so that tests can run without importing optional connector code while packaging remains verifiable.

#### Packaging contract exception

The following do not violate acceptance criterion 1 below when they do not import `llm_proxy_oauth_connectors`: tests that assert optional-dependency wiring, install command strings, or discovery-state constants against `pyproject.toml` or metadata. Discovery unit tests may also use string module names and fake entry points to simulate a plugin without importing the real package.

#### Acceptance Criteria

1. Except for the packaging contract exception above, when the core test suite covers connector behavior, streaming, or retry logic, the system shall not import or attempt to import `llm_proxy_oauth_connectors`.
2. When the core test suite validates extracted OAuth connector behavior, the system shall not keep those behavior tests in the core repository.
3. When the core test suite validates plugin discovery or execution logic, the system shall use generic mock or dummy plugins.
4. When extracted OAuth connector runtime behavior needs direct verification, the system shall keep those tests in the `llm-interactive-proxy-oauth-connectors` repository.
