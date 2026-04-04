# Requirements Document

## Project Description (Input)

Extract OAuth-oriented backend connectors from the core proxy distribution into a separate Python package while preserving core stability, compatibility, and modular architecture.

## Introduction

**Project Context**: Universal LLM Proxy with async FastAPI runtime, staged initialization, DI-driven services, unified routing, and B2BUA-like session handling.

**Problem Statement**: OAuth/sensitive connectors are currently coupled to the core repository layout. The project needs a package and architecture contract that allows extracting these connectors without destabilizing core routing/session behavior or API-key-based backends.

## Glossary

| Term | Definition |
|------|------------|
| Core proxy | Main `llm-interactive-proxy` distribution and runtime services |
| OAuth package | Separate connector distribution (target name: `llm-interactive-proxy-oauth-connectors`) |
| Extracted connector | Backend moved out of core and loaded as plugin |
| Frontend connector | Client-facing protocol adapter/controller path (OpenAI-compatible, Anthropic-compatible, Gemini-compatible, Responses API, and internal sidecar ingress) |
| Shared routing boundary | Unified proxy routing path used by all outbound inference call surfaces |
| B2BUA A-leg | Internal continuity identity used by proxy core |
| B2BUA B-leg | Connector-facing attempt/session identity used at dispatch boundary |

## Requirements

### Requirement 1: Separate OAuth Connector Package and Installation UX
**Objective:** As an operator, I want OAuth connectors delivered as a separate pip-installable package, so that core and optional connector capabilities can evolve independently.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1.1 The system shall provide extracted OAuth connectors via a separate Python distribution named `llm-interactive-proxy-oauth-connectors`.
1.2 The core distribution `llm-interactive-proxy` shall expose an optional extra named `oauth` that installs the OAuth connector distribution.
1.3 The system shall document `pip install llm-interactive-proxy[oauth]` as the recommended full-install command for optional OAuth connectors.
1.4 Dependencies required only by extracted OAuth connectors shall not be mandatory dependencies of core distribution.

### Requirement 2: Plugin Discovery and Optional Availability Detection
**Objective:** As a maintainer, I want optional plugin discovery for extracted connectors, so that missing optional package installation never breaks core startup.

**Priority:** P0 (Critical)

#### Acceptance Criteria
2.1 When the proxy starts, the system shall discover built-in core connectors from `src/connectors/` using core discovery mechanism.
2.2 When connector discovery runs, the system shall attempt to discover external backends via Python entry points in group `llm_proxy_backends`.
2.3 If no entry points exist for `llm_proxy_backends`, then the system shall treat this as a valid optional absence and continue startup.
2.4 If an external entry point cannot be loaded, then the system shall log an actionable warning and continue startup.
2.5 The system shall register each successfully loaded plugin backend factory into `BackendRegistry` under deterministic backend name.
2.6 Discovery shall run before backend selection/validation stages that require registry contents.

### Requirement 3: Core Independence from Concrete Backend Connectors
**Objective:** As a maintainer, I want proxy core to depend on stable abstractions instead of concrete backend implementations, so that adding or changing connectors does not require core changes.

**Priority:** P0 (Critical)

#### Acceptance Criteria
3.1 The proxy core shall depend on backend abstractions/contracts (for example `LLMBackend` and interface boundaries) rather than concrete extracted backend modules.
3.2 Core startup and DI registration paths shall not unconditionally import extracted connector modules.
3.3 When a new connector is introduced through plugin contract, the system shall not require source changes in proxy core business logic to support discovery/loading.
3.4 If extracted connector implementation changes, then proxy core functionality for non-extracted connectors shall remain operational.
3.5 The system shall preserve deterministic fail-open behavior for optional connector plugin loading failures.

### Requirement 4: Core Independence from Concrete Frontend Connector Implementations
**Objective:** As a maintainer, I want core business services isolated from protocol-specific ingress implementations, so that frontend protocol evolution does not force core refactors.

**Priority:** P0 (Critical)

#### Acceptance Criteria
4.1 Frontend connector implementations shall adapt protocol payloads into canonical domain contracts before invoking core request/routing services.
4.2 Proxy core routing/session/resilience services shall not depend on concrete frontend controller classes.
4.3 When a new frontend protocol adapter is added, core routing/session business logic shall remain unchanged except for registration/composition wiring.
4.4 All frontend protocol adapters shall invoke outbound inference through the shared routing boundary.

### Requirement 5: Runtime Behavior When OAuth Package Is Not Installed
**Objective:** As an operator, I want the proxy to remain functional without optional OAuth package, so that API-key-based connectors continue to serve traffic.

**Priority:** P0 (Critical)

#### Acceptance Criteria
5.1 If extracted OAuth package is absent, the system shall not crash during startup.
5.2 If configuration references extracted backend that is not registered, then the system shall emit actionable warning including install guidance (`pip install llm-interactive-proxy[oauth]`).
5.3 If `default_backend` or `static_route` references an unregistered extracted backend and no registered alternative exists, then startup validation shall fail with actionable error.
5.4 When request targets unregistered backend, the system shall return deterministic handled error response instead of unhandled exception.
5.5 While at least one configured backend is registered and healthy, the system shall continue startup even if some extracted backends are unavailable.
5.6 API-key-based core connectors shall remain functional when OAuth package is absent.

### Requirement 6: Unified Routing Contract Across All Outbound Inference Surfaces
**Objective:** As a maintainer, I want one routing contract for all outbound inference calls, so that behavior and diagnostics stay consistent regardless of feature entry point.

**Priority:** P0 (Critical)

#### Acceptance Criteria
6.1 The system shall resolve backend/model selection through one shared routing boundary for primary request execution.
6.2 Random model replacement flows shall resolve targets through the same shared routing boundary.
6.3 Quality verifier flows shall resolve targets through the same shared routing boundary.
6.4 Auxiliary/sidecar inference flows shall resolve targets through the same shared routing boundary.
6.5 If any outbound inference path bypasses shared routing boundary, then compliance verification shall fail development-time validation.
6.6 Routing unification compliance checks shall remain required merge gate for routing-related changes.

### Requirement 7: B2BUA Session Identity Isolation at Connector Boundary
**Objective:** As an operator, I want B2BUA continuity and connector-facing identity to remain isolated after extraction, so that connector plugins never receive proxy-internal continuity identity.

**Priority:** P0 (Critical)

#### Acceptance Criteria
7.1 While B2BUA mode is active, the system shall use canonical A-leg identity for proxy-internal continuity/session resolution.
7.2 When dispatching connector call in B2BUA mode, the system shall use B-leg identity for connector-facing `session_id`.
7.3 The system shall not expose `a_session_id`, `client_session_id`, or `auth_scope_id` fields at connector-facing request context boundary.
7.4 If B2BUA identity allocation fails, then the system shall fail open without leaking proxy-internal identity fields.
7.5 Auxiliary requests shall use isolated effective session identities so sidecar execution does not mutate primary continuity state.

### Requirement 8: Constrained Single-Instance Policy for Self-Managed OAuth Families
**Objective:** As an operator, I want constrained OAuth connector families to run as single proxy instances, so connector-internal scheduling remains coherent.

**Priority:** P0 (Critical)

#### Acceptance Criteria
8.1 The system shall enforce single-instance policy for constrained families including `gemini-oauth*`, `antigravity*`, and `qwen-oauth`.
8.2 If multiple constrained-family proxy instances are configured, then semantic validation shall fail with deterministic actionable guidance.
8.3 Runtime routing shall not proxy-load-balance across multiple constrained-family instances.
8.4 Constrained-family matching rules shall be deterministic and reusable across validation and routing.

### Requirement 9: Stable Plugin API and Compatibility Contract
**Objective:** As a plugin developer, I want a stable API contract from core, so external connector packages can be developed without importing deep internals.

**Priority:** P1 (High)

#### Acceptance Criteria
9.1 Core shall expose documented plugin API surface for external backends (minimum: backend contract type, configuration types required for registration, and supported registration hook contract).
9.2 Plugin backends shall be discoverable only through supported plugin registration mechanism (entry points and documented hooks).
9.3 Optional plugin service registration hooks shall execute conditionally and shall not be required for core startup.
9.4 If plugin declares unsupported core compatibility, then system shall skip plugin activation with warning instead of crashing startup.

### Requirement 10: Layered Modular Architecture, SOLID, and DRY Constraints
**Objective:** As an architect, I want extraction changes to preserve modular layered design and clean boundaries, so long-term maintainability improves rather than regresses.

**Priority:** P0 (Critical)

#### Acceptance Criteria
10.1 The system shall enforce dependency direction where core policy/services depend on abstractions and connector/plugin implementations depend on those abstractions.
10.2 Components touched by extraction shall preserve single responsibility and avoid mixed concerns across routing, session, and transport layers.
10.3 Shared behaviors (routing policy, session identity projection, plugin discovery) shall be implemented once and reused rather than duplicated across adapters/connectors.
10.4 Changes introduced for OAuth extraction shall preserve loose coupling between core layers and external connector implementations.

### Requirement 11: Verification and Regression Safety
**Objective:** As a maintainer, I want explicit verification coverage for both package-present and package-absent modes, so extraction cannot silently regress core behavior.

**Priority:** P0 (Critical)

#### Acceptance Criteria
11.1 Core test suite shall pass in environment where OAuth connector package is not installed.
11.2 Core tests shall verify plugin discovery fail-open behavior for missing entry points and entry point load failures.
11.3 Core tests shall verify API-key-based connector functionality remains intact when OAuth package is absent.
11.4 Core tests shall verify deterministic errors/warnings for unregistered extracted backends.
11.5 Plugin package shall maintain its own connector functionality test suite independent of core repository tests.
