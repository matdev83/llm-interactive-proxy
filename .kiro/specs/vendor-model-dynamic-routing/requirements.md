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
- `src/core/services/backend_service.py` - resolves backend + model and executes failover logic
- `src/core/services/backend_routing_service.py` - instance selection and model-based discovery
- `src/core/services/resilience/*` - instance/model cooldown tracking and permanent instance disable
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
| Candidate set | The set of backend instances eligible to serve a requested model at a point in time |
| Availability | Whether an instance or (instance, model) pair is eligible for selection (not disabled / not in cooldown / not permanently unsupported) |

## Requirements

### Requirement 1: Model Addressing Semantics
**Objective:** As an operator, I want unambiguous model addressing rules, so that clients and configuration can express routing intent consistently.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1.1 When parsing any model string, the system shall use `:` as the only backend-selection separator and shall never treat `/` as a backend-selection separator.
1.2 When a model string is in `backend:model` format, the system shall treat the portion before the first `:` as the backend selector and the remainder as the model identifier (which may include `/` and `:` characters).
1.3 When a model string is in `backend-instance:model` format, the system shall treat the backend selector as a concrete backend instance identifier and shall not load-balance to other instances.
1.4 When a model string contains no `:` separator, the system shall treat it as a backend-agnostic model request and shall not infer backend selection from any `/` segments.
1.5 If a model string contains multiple `:` characters, the system shall split backend selection at the first `:` only.

#### Technical Constraints
- The parsing rules shall apply uniformly to all request paths and features that consume model strings (API endpoints, session state, failover, internal services).

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
3.2 When multiple candidate instances are available for a model-only request, the system shall select one using a policy (Round Robin by default).
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

### Requirement 5: Model Capability Discovery and Indexing
**Objective:** As an operator, I want the proxy to know which backend instances can serve which `vendor/model` identifiers, so that model-only routing can be performed quickly and correctly.

**Priority:** P1 (High)

#### Acceptance Criteria
5.1 When the proxy starts, the system shall build an initial model capability index from configured backends and their available model listings when available.
5.2 If a backend instance cannot provide an authoritative model list, the system shall degrade gracefully by using configured model hints when present and shall not prevent startup.
5.3 The system shall maintain a unique set of models in backend-agnostic `vendor/model` format and shall not include backend prefixes in model identifiers.
5.4 When model capability information changes at runtime (e.g., refreshed discovery), the system shall update the capability index without restarting the proxy.

#### Technical Constraints
- The capability index lookups shall be efficient enough to be used on every request.

### Requirement 6: Observability of Routing and Availability
**Objective:** As an operator, I want visibility into model availability and routing decisions, so that I can debug and tune the proxy behavior.

**Priority:** P2 (Medium)

#### Acceptance Criteria
6.1 When requesting the models listing endpoint, the system shall expose the backend-agnostic set of available `vendor/model` identifiers.
6.2 When requesting diagnostics, the system shall expose the current availability status of backend instances and the mapping between models and eligible backend instances.
6.3 If a routing decision fails due to no candidates, the system shall provide a structured error that distinguishes “unknown model” from “temporarily unavailable”.

#### Technical Constraints
- Observability outputs shall not leak secrets (API keys, tokens).

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

### Requirement 8: Compatibility and Migration
**Objective:** As an operator, I want a clear and safe migration path away from ambiguous legacy syntax, so that existing deployments can be upgraded predictably.

**Priority:** P1 (High)

#### Acceptance Criteria
8.1 If a client supplies a model string of the form `backend/model` (no `:`), the system shall treat it as a model-only identifier and shall not interpret it as backend selection.
8.2 When configuration contains backend-addressing elements, the system shall require `backend:model` format and shall provide clear validation errors for invalid formats.
8.3 Where user-facing features require explicit backend selection (e.g., one-off routing), the system shall reject non-`backend:model` inputs with a clear error message.

#### Technical Constraints
- Migration behavior shall be consistent across API requests, configuration parsing, and interactive commands.
