# Requirements Document

## Project Description (Input)
Create/improve dynamic backend/model routing to support composite model route strings for failover ("|") and weighted random load balancing ("^" with optional [weight=N]) across main request routing, auxiliary routing, and quality verifier routing via one shared routing entry point. Preserve existing backend:model and URI parameter semantics, enforce deterministic/validated parsing, prevent retry explosion from nested failover layers, and deprecate random model replacement immediately with N+1 removal timeline and compatibility bridge.

## Requirements

### Requirement 1: Unified composite routing entry point
**Objective:** As a proxy operator, I want all model-routing call sites to resolve composite selectors through one shared entry point, so that failover and balancing behavior stays consistent across the product.

#### Acceptance Criteria
1. The LLM Interactive Proxy shall provide one shared routing entry point that resolves composite model route strings for main request routing, auxiliary routing, and quality verifier routing.
2. When any supported routing surface receives a non-composite selector, the LLM Interactive Proxy shall preserve the existing resolution behavior for `backend:model`, model-only selectors, backend-instance selectors, and URI-style parameters.
3. When any supported routing surface receives a composite selector, the LLM Interactive Proxy shall evaluate it through the same parsing and validation rules regardless of which routing surface initiated the resolution.
4. If a routing surface is not wired through the shared routing entry point, the LLM Interactive Proxy shall reject the implementation as non-compliant with this specification.
5. The LLM Interactive Proxy shall expose composite routing behavior without requiring callers to change the existing selector field names or request payload shape.

### Requirement 2: Ordered failover composite selectors
**Objective:** As a proxy operator, I want route strings to express ordered fallback targets, so that requests can continue on alternate backends or models when preferred targets are unavailable.

#### Acceptance Criteria
1. When a selector uses the `|` operator, the LLM Interactive Proxy shall interpret the selector as an ordered failover chain evaluated from left to right, starting from the first target on each new routing attempt.
2. When the active target in a failover chain cannot be used because selection, health, or execution routing rejects it before meaningful output begins, the LLM Interactive Proxy shall attempt the next eligible target in the chain.
3. If every target in a failover chain is exhausted or ineligible, the LLM Interactive Proxy shall fail the routing attempt with a deterministic error outcome instead of silently falling back to unrelated routing behavior.
4. While evaluating a failover chain, the LLM Interactive Proxy shall preserve selector-local URI parameters and target identity for the chosen target.
5. The LLM Interactive Proxy shall allow failover targets to use the same selector semantics already supported for single-target routing, including explicit backend selection and URI-style parameters.

### Requirement 3: Weighted random composite selectors
**Objective:** As a proxy operator, I want route strings to express weighted random choices, so that traffic can be distributed probabilistically across equivalent targets.

#### Acceptance Criteria
1. When a selector uses the `^` operator, the LLM Interactive Proxy shall interpret the selector as a weighted random choice among the participating targets.
2. Where a weighted-random target includes a `[weight=N]` prefix annotation immediately before the target selector, the LLM Interactive Proxy shall use `N` as that target's relative selection weight.
3. Where a weighted-random target omits `[weight=N]`, the LLM Interactive Proxy shall assign a default weight of `1`.
4. If a weighted-random selector contains an invalid, non-positive, or non-numeric weight declaration, the LLM Interactive Proxy shall reject the selector with a validation error before request execution begins.
5. When a weighted-random selector is resolved successfully, the LLM Interactive Proxy shall route the request to exactly one selected target for that routing decision.

### Requirement 4: Deterministic parsing and validation
**Objective:** As a maintainer, I want composite selectors to be parsed predictably and validated early, so that configuration and request errors are caught before they cause inconsistent runtime behavior.

#### Acceptance Criteria
1. The LLM Interactive Proxy shall define deterministic parsing rules for composite selectors, including operator handling, operator exclusivity rules, whitespace treatment, parameter binding, and weight annotations.
2. If a composite selector mixes the failover operator `|` and the weighted-random operator `^` in the same selector string, the LLM Interactive Proxy shall reject the selector with a validation error rather than attempting to interpret mixed-operator precedence.
3. If a composite selector is syntactically malformed, the LLM Interactive Proxy shall reject it with an explicit validation error that identifies composite-selector parsing as the failure cause.
4. If a composite selector mixes constructs that are unsupported by the routing grammar, the LLM Interactive Proxy shall reject it instead of applying best-effort interpretation.
5. When the same valid composite selector string is parsed multiple times under the same configuration, the LLM Interactive Proxy shall produce the same parse structure each time.
6. The LLM Interactive Proxy shall validate composite selectors before attempting provider execution, so that invalid selectors do not trigger partial downstream side effects.
7. If any composite leaf target is invalid under the existing single-target selector semantics, the LLM Interactive Proxy shall reject the entire composite selector during validation.

### Requirement 5: Composite failover safety and retry-bound control
**Objective:** As an operator, I want composite routing interaction with existing retry mechanisms to stay bounded, so that retries and failover do not explode combinatorially during degraded backend conditions.

#### Acceptance Criteria
1. When composite routing interacts with existing failover and retry mechanisms, the LLM Interactive Proxy shall enforce a bounded maximum number of failover hops across the entire routing attempt.
2. While processing composite routing, the LLM Interactive Proxy shall count failover progress across the shared routing attempt instead of resetting retry or failover depth independently per mechanism.
3. If a routing attempt reaches the configured failover bound, the LLM Interactive Proxy shall stop further composite failover evaluation and return a deterministic exhaustion error.
4. When a retryable backend failure occurs inside a composite route, the LLM Interactive Proxy shall prevent composite failover combined with existing retry layers from multiplying retries beyond the configured safety limit.
5. The LLM Interactive Proxy shall preserve existing protections that avoid retry or failover after meaningful streaming output has already begun.
6. The LLM Interactive Proxy shall ensure composite failover progression shares a single bounded attempt budget with existing retry/failover mechanisms, so that composite routing does not create an independent retry loop.

### Requirement 6: Backward compatibility for existing selector semantics
**Objective:** As an existing user, I want current selector formats to keep working, so that composite routing can be adopted without breaking established integrations.

#### Acceptance Criteria
1. The LLM Interactive Proxy shall preserve existing `backend:model` selector semantics when the selector does not use composite routing operators.
2. The LLM Interactive Proxy shall preserve existing URI-style parameter semantics for both single-target selectors and composite targets that include parameters.
3. When composite routing is not configured or not used, the LLM Interactive Proxy shall behave equivalently to the pre-feature routing behavior.
4. If an existing configuration or request uses a selector format that remains valid under the composite grammar, the LLM Interactive Proxy shall continue to accept it without requiring migration.
5. The LLM Interactive Proxy shall keep explicit-backend requirements for surfaces that already require strict `backend:model` input, except where composite syntax explicitly extends those surfaces.

### Requirement 7: Deprecation and migration of random model replacement
**Objective:** As a product owner, I want the older random model replacement behavior deprecated with a clear migration bridge, so that routing logic converges on one composite-routing model without abrupt user breakage.

#### Acceptance Criteria
1. The LLM Interactive Proxy shall mark random model replacement as deprecated immediately when composite weighted-random routing becomes available.
2. When deprecated random model replacement is still configured, the LLM Interactive Proxy shall provide a compatibility bridge that preserves current behavior, including session-level replacement stickiness, during the deprecation window.
3. The LLM Interactive Proxy shall define an N+1 removal timeline for deprecated random model replacement and surface that timeline in operator-facing configuration or deprecation messaging.
4. If deprecated random model replacement cannot be mapped safely into the composite-routing model, the LLM Interactive Proxy shall fail with an explicit migration error rather than silently changing routing behavior.
5. The LLM Interactive Proxy shall ensure new routing capabilities are expressed through composite selectors rather than through expansion of the deprecated random replacement feature.

### Requirement 8: Consistent observability and diagnosability
**Objective:** As an operator, I want composite routing decisions to remain inspectable, so that I can understand why a request chose, skipped, or exhausted a route target.

#### Acceptance Criteria
1. When composite routing resolves a target, the LLM Interactive Proxy shall make the selected target and composite-routing context available to existing observability surfaces used for request diagnostics.
2. When failover skips or exhausts a target in a composite route, the LLM Interactive Proxy shall record enough structured context to distinguish validation rejection, ineligibility, and runtime failure causes.
3. If a composite selector is rejected during parsing or validation, the LLM Interactive Proxy shall expose an operator-actionable error that identifies the invalid selector input.
4. While maintaining observability for composite routing, the LLM Interactive Proxy shall not remove existing request diagnostics for non-composite routing.
5. The LLM Interactive Proxy shall keep diagnostic behavior consistent across main request routing, auxiliary routing, and quality verifier routing.
