# Design Document: oauth-connectors-plugin-architecture

## Overview

**Purpose**: This feature evolves the architecture of `llm-interactive-proxy` to treat OAuth-oriented backends as true, decoupled plugins. It removes hardcoded references, implicit contracts, and test dependencies that currently bind the core proxy to the `llm-interactive-proxy-oauth-connectors` package.

**Users**: Core system maintainers and plugin developers will use this design to build and maintain independent, modular backend connectors.

**Impact**: Changes the current system state by replacing string matching and duck-typing with explicit capability declarations and strongly typed interfaces, ensuring the core remains agnostic to plugin-specific implementations in the in-scope paths.

### Goals

- Eliminate hardcoded extracted-plugin identifiers and implicit contracts from in-scope core logic and connector-behavior tests.
- Introduce standardized OAuth-related capability declaration through `BackendCapabilityDescriptor`.
- Decouple in-scope execution logic by extending the existing `ITokenRefresher` contract and removing remaining duck-typing.
- Enable dynamic CLI argument registration and configuration application for plugins.
- Ensure runtime test isolation from the OAuth plugin package, with a narrow packaging-contract exception.

### Non-Goals

- Large refactors inside the OAuth plugin repository beyond what is needed to adopt new contracts and relocate plugin-specific tests.
- Global cleanup of every remaining `backend_type` heuristic outside the explicitly in-scope modules.
- Reclassification of deferred in-repo OAuth policy flags in this iteration.

### Scope and deferred work

**In scope** matches `requirements.md`: discovery and classification, resilience scoping, streaming execution, CLI/config hooks, capability metadata, plugin registration metadata, and test isolation for the targeted paths.

**Deferred (follow-up)**: Additional modules that still use OAuth-oriented string heuristics remain follow-up work unless they are explicitly pulled into a future task list.

### Cross-repository coordination

Moving connector-specific runtime-behavior tests into `llm-interactive-proxy-oauth-connectors` requires coordinated versioning, CI expectations, and release ordering so the plugin can adopt the new contracts after the core publishes them.

## Architecture

### Existing Architecture Analysis

The core already has substantial OAuth-related infrastructure, but it remains partially coupled:

- Discovery and classification still combine capability-like checks with hardcoded names and spelling-based heuristics.
- `streaming_executor.py` already has an `ITokenRefresher` protocol, but related behaviors still depend on duck-typing and private connector state.
- Resilience scoping still uses hardcoded backend lists and name heuristics for personal-auth decisions.
- CLI wiring still contains hardcoded extracted-plugin debug flags instead of plugin-owned registration hooks.
- Some tests still model real optional-plugin behavior from the core repository.

This spec standardizes the remaining plugin boundary and removes those implicit contracts from the in-scope paths.

### Architecture Pattern and Boundary Map

- **Selected pattern**: Capability-driven plugin architecture with explicit `typing.Protocol` contracts.
- **Core ownership**: Core defines the stable contracts, capability model, discovery registries, and CLI/config integration points.
- **Plugin ownership**: Plugins declare capabilities, implement published protocols, and own any plugin-specific runtime behavior and tests.
- **Boundary rule**: External plugins import from `src/core/plugin_api.py` only; core may use internal interfaces but must re-export stable contracts for plugin use.
- **Lifecycle rule**: Plugin discovery must complete before CLI argument registration is needed on the supported entry path.

### Technology Stack

| Layer | Choice | Role in Feature |
|-------|--------|-----------------|
| Backend / Services | Python 3.10+ | Core runtime and protocol definitions |
| CLI | `argparse` | Dynamic plugin argument registration |
| Configuration | Pydantic v2 models | Capability declaration and config application |

## Requirements Traceability

| Requirement | Summary | Components |
|-------------|---------|------------|
| 1.1–1.3 | Core independence from plugin names | Discovery, resilience scoping, capability metadata |
| 2.1–2.4 | Capability declaration | `BackendCapabilityDescriptor`, plugin registration metadata |
| 3.1–3.5 | Execution decoupling | Runtime protocols, streaming execution |
| 4.1–4.5 | Configuration and CLI independence | CLI hook registration, config application |
| 5.1–5.4 | Test isolation | Core tests, plugin-repo behavior tests |

## Components and Interfaces

### 1. Backend Capability Metadata

**Intent**: Represent OAuth-related backend characteristics through explicit metadata rather than name inference.

**Responsibilities**:

- Carry capability flags such as `requires_personal_auth` and `is_oauth_based`.
- Support classification in configuration-aware paths.
- Align in-repo backends and entry-point plugins around the same capability vocabulary.

**Design decisions**:

- Extend `BackendCapabilityDescriptor` with the OAuth-related flags required by the requirements.
- Ensure in-repo OAuth-oriented backends declare those flags in their capability descriptor data.
- Keep new flags limited to cross-cutting behavior rather than plugin-specific quirks.

### 2. Discovery and Registration Metadata

**Intent**: Let discovery logic classify OAuth-oriented connectors without depending on extracted-plugin naming conventions.

**Responsibilities**:

- Make OAuth-related capability signals available at discovery time.
- Preserve idempotent backend and plugin discovery behavior.
- Separate packaging diagnostics from behavioral branching.

**Design decisions**:

- Entry-point plugins expose discovery-time OAuth capability hints through plugin registration metadata.
- In-repo connectors use core-readable capability information that is available before heavy runtime behavior is needed.
- Discovery code may use neutral public signals available at decision time, but must not rely on extracted-plugin literals or package-path discrimination.

### 3. Runtime Protocols

**Intent**: Replace private-state duck-typing in execution paths with stable protocol-based contracts.

**Responsibilities**:

- Preserve the existing `ITokenRefresher` concern as the refresh contract.
- Add explicit contracts for credential rotation, rate-limit bookkeeping, and account-selection behavior.
- Keep runtime calls centered on published interfaces rather than backend names or private fields.

**Design decisions**:

- Relocate `ITokenRefresher` to a stable core interfaces module and re-export it from `plugin_api.py`.
- Add protocol-based capabilities for credential rotation and account selection.
- Prefer method-based protocol surfaces for runtime structural checks.
- Treat multi-account OAuth refreshers as the primary place where refresh, rotation, and account-selection capabilities coexist.

### 4. CLI and Configuration Hooks

**Intent**: Move plugin-specific CLI and configuration ownership out of hardcoded core wiring.

**Responsibilities**:

- Let plugins register CLI arguments dynamically.
- Let plugins apply parsed arguments to configuration through a supported hook.
- Preserve the existing core config precedence and applicator flow.

**Design decisions**:

- Extend `BackendPluginDefinition` with hooks for CLI registration and configuration application.
- Keep plugin hook invocation deterministic and compatible with the current CLI lifecycle.
- Allow plugin-private configuration validation through a documented extension mechanism without introducing core-owned plugin-specific defaults.

### 5. Test Boundary

**Intent**: Keep the core test suite independent from optional plugin runtime behavior.

**Responsibilities**:

- Use generic mocks and dummy plugins in core tests.
- Preserve packaging-contract assertions that do not import the optional plugin package.
- Move extracted-plugin behavior tests to the plugin repository.

**Design decisions**:

- Core tests validate contracts and integration seams, not plugin-specific runtime behavior.
- Plugin-repo tests own connector-specific retry, streaming, and behavior assertions.

## Integration Notes

- Discovery, CLI registration, and application startup must continue to honor the current supported lifecycle so plugin hooks are available when argument parsing occurs.
- Capability metadata and runtime protocols should converge on one vocabulary so resilience, execution, and discovery do not drift apart again.
- The stable plugin API should remain narrow and versionable because external packages depend on it directly.

## Testing Strategy

- **Unit tests**: Capability metadata parsing, plugin hook registration and application, and runtime protocol dispatch using mock implementations.
- **Integration tests**: Discovery and execution flows using dummy plugins without importing `llm_proxy_oauth_connectors`.
- **Boundary tests**: Packaging-contract assertions stay in core; extracted-plugin runtime-behavior tests move to the plugin repository.
