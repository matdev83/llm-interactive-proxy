# Requirements Document

## Project Description (Input)

Refactor model routing so that backend selection is explicit and unambiguous, and so that clients can request models in a backend-agnostic way.

Supported request variants (all share the same semantics across the entire proxy, not just chat commands):

1. `backend:model`
   - Routes via available *instances* of the backend connector (e.g., `openai.1`, `openai.2`) using a routing policy (Round Robin by default).
2. `backend-instance:model`
   - Routes via the specific concrete instance only (e.g., `openai.1`).
3. `model` or `vendor/model`
   - Routes via available backends capable of handling the model (may be one or many), using a selection policy.

Constraints / clarifications:
- `:` is the only backend-selection separator. `/` must never be treated as a backend separator; it is part of the model identifier (e.g., `openai/gpt-4o`).
- Many backends are multi-model and multi-vendor (e.g., OpenRouter-like aggregators); therefore model identifiers should be treated as fully qualified `vendor/model` where possible.
- Model and backend availability may change at runtime (rate limits, auth failures, model-not-found, etc.), so routing should be able to avoid wasting attempts on unavailable targets and choose alternatives.

## Initial Context (Non-Exhaustive)

Key current touchpoints (for discovery/design phases):
- `src/core/services/backend_model_resolver.py` - resolves effective backend/model target via aliases, parsing, routing, static overrides
- `src/core/services/backend_routing_service.py` - explicit instance routing, backend round robin, model-based discovery
- `src/core/services/backend_completion_flow/` - orchestrated backend execution, availability checks, failover/retry, session-aware dispatch
- `src/core/services/backend_completion_flow/completion_session_resolver.py` - session lookup behavior for legacy and B2BUA modes
- `src/core/services/b2bua_session_resolver_service.py` - canonical A-leg session continuity resolution
- `src/core/services/resilience/*` and `src/core/services/resilience/scope.py` - cooldown/disablement and per-scope resilience instance IDs
- `src/core/domain/model_utils.py` - authoritative model parsing (`:` backend selector, `/` remains model payload)
- `src/connectors/base.py` - connector contract for model identifiers (`vendor/model`)

## Requirements

## Introduction

**Project Context**: Universal LLM Proxy - traffic routing and failover across multiple backend connector instances, with async FastAPI architecture, DI, and staged initialization.

**Problem Statement**: Model identifiers and backend selection must be unambiguous across the entire proxy. The system must support:
- Explicit backend addressing (`backend:model`, `backend-instance:model`)
- Backend-agnostic model addressing (`model`, `vendor/model`)
- Dynamic selection across multiple backend instances that can serve the same model
- Avoidance of unavailable targets using runtime availability signals (rate limits, auth failures, model-not-found)

**Stakeholders**:
- Developers integrating LLM capabilities via unified API surfaces
- Operators configuring multiple backend instances (API key pools) and failover behavior
- End users relying on consistent availability and reduced latency under failures

## Glossary

| Term | Definition |
|------|------------|
| Backend type | Logical connector type (e.g., `openai`, `openrouter`, `gemini`) |
| Backend instance | Concrete connector instance identifier (e.g., `openai.1`, `openai.2`) |
| Backend selection | Choosing a backend type or instance to satisfy a request |
| Model identifier | String provided by client in `model` field after aliasing; may include `/` (e.g., `openai/gpt-4o`) |
| Vendor prefix | The `vendor` component of a `vendor/model` identifier (e.g., `openai` in `openai/gpt-4o`) |
| Routing URI parameters | Query-like key/value settings embedded in model selector strings (e.g., `vendor/model?temperature=0.5`) |
| Candidate set | The set of backend instances eligible to serve a requested model at a point in time |
| Availability | Whether an instance or (instance, model) pair is eligible for selection (not disabled / not in cooldown / not permanently unsupported) |

## Requirements

### Requirement 1: Model Addressing Semantics
**Objective:** As an operator, I want unambiguous model addressing rules, so that clients and configuration can express routing intent consistently.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1.1 When parsing any model string, the system shall use `:` as the only backend-selection separator and shall never treat `/` as a backend-selection separator.
1.2 When a model string is in `backend:model` format, the system shall treat the portion before the first `:` as the backend selector and the remainder as the model identifier (which may include `/` and `:` characters, for example `backend:vendor/model-name:free`).
1.3 When a model string is in `backend-instance:model` format, the system shall treat the backend selector as a concrete backend instance identifier and shall not load-balance to other instances.
1.4 When a model string contains no `:` separator, the system shall treat it as a backend-agnostic model request and shall not infer backend selection from any `/` segments.
1.5 If a model string contains multiple `:` characters and is classified as explicit backend format, the system shall split backend selection at the first `:` only.
1.6 If the first `:` appears after a `/` in the route portion of a selector, then the system shall treat that `:` as part of the model identifier and shall not treat the prefix as a backend selector.
1.7 If a selector ends with `:free` or contains `:free?<param>=<value>` in a model-only form (for example `vendor/model-name:free`), then the system shall treat `:free` as model identifier suffix and not as backend routing syntax.

#### Technical Constraints
- The parsing rules shall apply uniformly to all request paths and features that consume model strings (API endpoints, session state, failover, internal services).
- The uniform parsing contract shall cover all protocol-compatible inference ingress surfaces (OpenAI-compatible, Anthropic-compatible, Gemini-compatible, and internal auxiliary inference paths).
- Parsing shall evaluate query/URI parameter suffixes after routing-mode disambiguation of the route portion, so routing interpretation is stable for selectors like `vendor/model:free?temperature=0.5`.

### Requirement 2: Backend Instance Selection for `backend:model`
**Objective:** As an operator, I want `backend:model` to load-balance across backend instances, so that multiple API keys can be utilized effectively.

**Priority:** P0 (Critical)

#### Acceptance Criteria
2.1 When a request specifies `backend:model` and multiple backend instances exist for that backend type, the system shall select a concrete backend instance using Round Robin by default.
2.2 When a request specifies `backend:model` and no numbered instances exist, the system shall treat the backend type itself as a single selectable target.
2.3 When selecting a backend instance for `backend:model`, the system shall exclude instances that are unavailable at selection time.
2.4 If no available instance exists for `backend:model`, the system shall surface a routing error without attempting a backend call.

#### Technical Constraints
- The default selection policy shall be deterministic and safe under concurrency.

### Requirement 3: Model-Only Routing for `model` / `vendor/model`
**Objective:** As an application developer, I want to request `model` or `vendor/model` without naming a backend, so that the proxy can choose the best available backend instance dynamically.

**Priority:** P0 (Critical)

#### Acceptance Criteria
3.1 When a request specifies a model-only identifier (`model` or `vendor/model`), the system shall determine a candidate set of backend instances that can serve the model.
3.2 When multiple candidate instances are available for a model-only request, the system shall select one using a configured routing policy (Round Robin by default when no preference policy is configured).
3.3 If a model-only identifier is unknown (no candidates), the system shall return an error without attempting any backend call.
3.4 While model-only routing is disabled by routing policy, the system shall reject model-only requests with an explicit routing error.

#### Technical Constraints
- Candidate selection shall consider runtime availability state (see Requirement 4).

### Requirement 4: Runtime Availability Integration
**Objective:** As an operator, I want routing decisions to avoid unavailable backends and models automatically, so that the proxy minimizes latency and wasted requests under failures.

**Priority:** P0 (Critical)

#### Acceptance Criteria
4.1 While a backend instance is rate limited, the system shall treat the instance as unavailable for all models during its cooldown period.
4.2 While a specific (backend instance, model) pair is rate limited, the system shall treat that pair as unavailable during its cooldown period.
4.3 If an authentication failure is detected for a backend instance (e.g., 401/403 for static credentials), the system shall mark the instance as permanently unavailable until explicitly reactivated.
4.4 If a backend call fails with a permanent model-not-found signal for a specific (backend instance, model) pair, the system shall mark that pair as permanently unavailable to avoid future attempts.
4.5 When selecting candidates for routing, the system shall exclude any permanently unavailable instances and (instance, model) pairs.
4.6 When a backend call succeeds for a previously rate-limited (instance, model) pair, the system shall clear the temporary cooldown for that pair.

#### Technical Constraints
- The availability decisions shall not block the event loop and shall be safe under concurrent requests.
- Provider-specific error payloads shall be normalized through a deterministic classification policy before deciding whether a failure is permanent model-not-found.
- Cooldown recovery on success shall clear temporary cooldown state only; permanent unsupported/permanent disabled state shall remain unchanged unless explicitly reset.
- Permanent-disablement reactivation shall use an explicit control-plane contract and be reflected in diagnostics.

### Requirement 5: Model Capability Discovery and Indexing
**Objective:** As an operator, I want the proxy to know which backend instances can serve which `vendor/model` identifiers, so that model-only routing can be performed quickly and correctly.

**Priority:** P1 (High)

#### Acceptance Criteria
5.1 When the proxy starts, the system shall build an initial model capability index from configured backends and their available model listings when available.
5.2 If a backend instance cannot provide an authoritative model list, the system shall degrade gracefully by using configured model hints when present and shall not prevent startup.
5.3 The system shall maintain a unique set of models in backend-agnostic `vendor/model` format and shall not include backend prefixes in model identifiers.
5.4 When model capability information changes at runtime (e.g., refreshed discovery), the system shall update the capability index without restarting the proxy.
5.5 When capability data is derived from mixed sources (enumeration, config hints, aliases), the system shall apply deterministic source precedence, normalization, and collision rules to produce stable canonical and alias mappings.

#### Technical Constraints
- The capability index lookups shall be efficient enough to be used on every request.
- Model normalization and alias handling shall follow deterministic tie-breaking rules so `model` and `vendor/model` collisions resolve predictably.
- Runtime refresh shall use deterministic merge semantics so repeated refresh cycles with equivalent inputs produce equivalent snapshots.
- Refresh lifecycle policy (startup, periodic, and on-demand) shall be explicitly defined with deterministic concurrency and failure/backoff behavior.

### Requirement 6: Observability of Routing and Availability
**Objective:** As an operator, I want visibility into model availability and routing decisions, so that I can debug and tune the proxy behavior.

**Priority:** P2 (Medium)

#### Acceptance Criteria
6.1 When requesting the models listing endpoint, the system shall expose the backend-agnostic set of available `vendor/model` identifiers.
6.2 When requesting diagnostics, the system shall expose the current availability status of backend instances and the mapping between models and eligible backend instances.
6.3 If a routing decision fails due to no candidates, the system shall provide a structured error that distinguishes “unknown model” from “temporarily unavailable”.

#### Technical Constraints
- Observability outputs shall not leak secrets (API keys, tokens).
- Diagnostics payloads shall remain bounded and deterministic in size under large model/instance sets.
- Deterministic boundedness shall use stable ordering and truncation rules; random sampling shall not be used.
- Routing error classification shall use one canonical internal error envelope with explicit protocol-adapter mappings for all supported frontend APIs.

### Requirement 7: Non-Functional Requirements (Performance, Concurrency, Safety)
**Objective:** As an operator, I want routing to remain fast and safe under concurrency, so that the proxy stays responsive under load.

**Priority:** P0 (Critical)

#### Acceptance Criteria
7.1 The system shall make routing decisions without blocking the async event loop.
7.2 The system shall use concurrency-safe data structures for shared routing state and shall avoid deadlocks.
7.3 The system shall support constant-time (or effectively constant-time) candidate lookup by model identifier.
7.4 The system shall allow a bounded maximum number of backend instances to be attempted for a single request.

#### Technical Constraints
- DI usage must comply with the DI scanner expectations (no ad-hoc construction in business logic where DI is required).
- Attempt-budget semantics shall define counting rules and precedence against connector-internal hold/wait behavior and request cancellation/timeouts.

### Requirement 8: Compatibility and Migration
**Objective:** As an operator, I want a clear and safe migration path away from ambiguous legacy syntax, so that existing deployments can be upgraded predictably.

**Priority:** P1 (High)

#### Acceptance Criteria
8.1 If a client supplies a model string of the form `backend/model` (no `:`), the system shall treat it as a model-only identifier and shall not interpret it as backend selection.
8.2 When configuration contains backend-addressing elements, the system shall require `backend:model` format and shall provide clear validation errors for invalid formats.
8.3 Where user-facing features require explicit backend selection (e.g., one-off routing), the system shall reject non-`backend:model` inputs with a clear error message.
8.4 When interactive command surfaces accept routing/model selectors, the system shall apply the same parsing and validation semantics used by API/config paths.

#### Technical Constraints
- Migration behavior shall be consistent across API requests, configuration parsing, and interactive commands.

### Requirement 9: Session-Aware Routing and B2BUA Identity Isolation
**Objective:** As an operator, I want dynamic routing to respect B2BUA session semantics, so that retries/failover remain correct while connector-facing identity stays isolated from proxy-internal continuity state.

**Priority:** P0 (Critical)

#### Acceptance Criteria
9.1 When B2BUA mode is active for a request, the system shall use canonical A-leg identity for internal continuity decisions (session lookup, routing continuity, and resilience scoping inputs).
9.2 When dispatching an outbound backend attempt in B2BUA mode, the system shall use a B-leg session identifier for connector-facing `session_id` fields.
9.3 When retrying or failing over in B2BUA mode, the system shall allocate a distinct B-leg attempt identity per attempt while preserving the same A-leg continuity identity.
9.4 When auxiliary or sidecar backend requests are generated from a primary request, the system shall derive isolated effective session identifiers so they do not mutate primary conversation continuity state.
9.5 If B2BUA identity allocation fails at runtime, then the system shall fail open by preserving request processing and avoiding leakage of proxy-internal identity fields to connector-facing payloads.

#### Technical Constraints
- Session-aware routing behavior shall remain async-safe and shall not introduce cross-request identity leakage.
- Auxiliary/sidecar calls shall use a deterministic derived-identity contract that is isolated from primary continuity state.
- Fail-open identity handling shall follow deterministic fallback rules that prevent leakage of A-leg/internal identity fields.

### Requirement 10: Project-Wide Routing Unification
**Objective:** As a maintainer, I want one standardized routing mechanism for all outbound LLM inference calls, so that all features use consistent backend selection rules, availability handling, and diagnostics.

**Priority:** P0 (Critical)

#### Acceptance Criteria
10.1 When any outbound call to a remote LLM inference backend is prepared, the system shall resolve backend and model selection through one shared routing function/method.
10.2 When the Random Model Replacement feature selects a replacement model, the system shall route that replacement call through the same shared routing function/method used for normal requests.
10.3 When the Quality Verifier model is invoked, the system shall route that call through the same shared routing function/method used for normal requests.
10.4 When auxiliary backend calls are generated (for example title generation, summarization, or similar sidecar tasks), the system shall route those calls through the same shared routing function/method used for normal requests.
10.5 If any feature attempts to bypass the shared routing function/method for an outbound inference call, then the system shall reject or fail validation for that integration path during development-time verification.
10.6 When CI/build verification runs for routing-related changes, the system shall execute a mandatory unified-routing compliance gate that fails on bypass detection and blocks integration until fixed.

#### Technical Constraints
- Unified routing behavior shall preserve existing policy controls, availability filtering, and session/B2BUA safety guarantees.
- The shared routing function/method defines proxy-level target resolution and shall not replace connector-internal scheduling logic.
- Development-time verification shall include automated checks that detect outbound inference call paths bypassing the shared routing function/method.
- The unified-routing compliance gate shall be a required CI check (non-optional) for merges affecting outbound inference call surfaces.
- Compliance verification shall include both static path inspection and runtime contract tests over the authoritative outbound call-surface inventory.
- Compliance verification shall fail on unregistered outbound call surfaces detected by automated discovery/registration checks.

### Requirement 11: Connector-Internal Autonomy and Hierarchical Routing Composition
**Objective:** As a maintainer, I want the new routing architecture to preserve connector-internal autonomy (for example, `gemini-oauth-auto` multi-account rotation and temporary hold behavior), so that proxy-level routing and connector-level scheduling compose safely without duplicated or conflicting logic.

**Priority:** P0 (Critical)

#### Acceptance Criteria
11.1 When the shared routing function/method resolves an outbound target, the system shall treat connector-internal account selection/rotation as an internal connector concern and shall not duplicate that account-level routing logic at proxy level.
11.2 When a connector performs internal temporary hold/wait behavior due to provider-side rate limiting, the system shall allow that behavior to proceed within configured bounds without violating B2BUA continuity or causing cross-session identity leakage.
11.3 When a connector supports internal round-robin or affinity across multiple provider identities, the system shall preserve that behavior while still applying proxy-level routing policies at the connector-instance boundary.
11.4 If connector-internal autonomy conflicts with proxy-level constraints (timeouts, cancellation, failover limits), then the system shall apply explicit precedence and boundary rules that keep behavior deterministic and observable.
11.5 When observability data is emitted, the system shall distinguish proxy-level routing decisions from connector-internal scheduling outcomes without exposing sensitive account credentials.

#### Technical Constraints
- Architecture shall follow hierarchical routing composition: proxy-level routing selects connector instance and model contract; connector-level scheduling selects provider identity/account when applicable.

### Requirement 12: Single-Instance Policy for Self-Managed OAuth Connectors
**Objective:** As an operator, I want self-managed OAuth connectors that internally manage borrowed credentials and account-level balancing to run as a single proxy instance, so that credential state, rate-limit handling, and connector-internal scheduling remain coherent.

**Priority:** P0 (Critical)

#### Acceptance Criteria
12.1 When loading backend configuration, the system shall enforce a maximum of one configured instance for self-managed OAuth connector families (including `gemini-oauth*`, `antigravity*`, and `qwen-oauth`).
12.2 If configuration defines multiple proxy instances for a connector family constrained to one instance, then the system shall fail validation with a clear, actionable error describing the constraint.
12.3 When backend instances are discovered from file/env/defaults, the system shall preserve the single-instance constraint and shall not create implicit additional instances for constrained connector families.
12.4 When routing requests for connectors constrained to one proxy instance, the system shall not apply proxy-level multi-instance load balancing for that connector family.
12.5 When migration encounters legacy configurations that already define multiple constrained connector instances, the system shall surface deterministic validation guidance for consolidation.

#### Technical Constraints
- The constrained connector-family set shall be centrally defined and reused by configuration validation and routing behavior.
- Connector-family matching rules (explicit names and/or wildcard patterns) shall be deterministic and surfaced in validation diagnostics.
- Family matching shall define canonical normalization (case/aliases) and precedence between explicit names and wildcard patterns.

### Requirement 13: First-Class URI Parameter Routing and Inheritance
**Objective:** As an application developer, I want URI-like parameters embedded in model selector strings to be treated as first-class routing inputs, so that settings are preserved across backend selection and applied consistently by connectors.

**Priority:** P0 (Critical)

#### Acceptance Criteria
13.1 When parsing model selector strings, the system shall parse and preserve URI-like parameters (for example `model?temperature=0.5`) for all routing modes (`backend:model`, `backend-instance:model`, `model`, `vendor/model`).
13.2 When model-only routing expands to multiple candidate backend instances, the system shall inherit the parsed URI parameters into the effective outbound request parameters for the selected backend attempt.
13.3 When failover or retry selects a different backend instance for the same logical request, the system shall preserve inherited URI parameters unless an explicit higher-precedence override applies.
13.4 When connectors receive an outbound request, the system shall provide inherited URI parameters as actual handling parameters, except where connector-enforced hardcoded/forced settings explicitly override them.
13.5 If URI parameters conflict with other request parameter sources, then the system shall apply deterministic precedence and expose this behavior in diagnostics/testing contracts.

#### Technical Constraints
- URI-parameter parsing/merging shall be protocol-agnostic and consistent across all inference ingress surfaces.
- Parameter propagation rules shall remain deterministic under routing expansion, failover, and connector-specific adaptation.

### Requirement 14: User-Configurable Preference Ordering for Multi-Candidate Model Routing
**Objective:** As an operator, I want configurable preference ordering when `model` or `vendor/model` resolves to multiple backend candidates, so that routing reflects cost and policy intent while remaining fair and deterministic.

**Priority:** P0 (Critical)

#### Acceptance Criteria
14.1 When model-only routing has multiple eligible candidates, the system shall apply a configurable preference policy before selecting the target.
14.2 The system shall support policy-driven ranking that includes cost-based preference and explicit priority-based preference as first-class options.
14.3 If multiple eligible candidates have equivalent effective preference score (for example equal cost), the system shall select among that equivalent set using deterministic Round Robin.
14.4 If failover is required after a failed attempt, the system shall continue within the same highest-preference equivalent set first, then proceed to lower-preference sets when needed.
14.5 If no explicit preference policy is configured for model-only routing, then the system shall default to Round Robin across eligible candidates.
14.6 When diagnostics are requested, the system shall expose which preference policy was applied and which candidates were considered equivalent for tie-breaking, without exposing secrets.
14.7 The system shall support preference-policy configuration at a global scope with optional deterministic overrides for backend family and model pattern scopes.

#### Technical Constraints
- Preference-policy evaluation shall be deterministic and concurrency-safe.
- Preference policy configuration shall define deterministic handling for missing cost/priority metadata.
- Preference-policy scope resolution shall be deterministic (`model override` > `backend-family override` > `global default`).
