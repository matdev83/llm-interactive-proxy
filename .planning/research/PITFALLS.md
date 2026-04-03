# Domain Pitfalls

**Domain:** Universal LLM proxy / agent control plane (brownfield hardening + expansion)
**Researched:** 2026-04-04

## Critical Pitfalls

Mistakes that commonly trigger outages, expensive rewrites, or silent trust erosion.

### Pitfall 1: Compatibility Surface Drift ("OpenAI-compatible" that is no longer behavior-compatible)
**What goes wrong:** New protocol support (e.g., Responses-style flows, tool call formats, streaming chunk variants) is added, but existing clients regress because behavior parity is not preserved across frontends.
**Why it happens:** Teams optimize for endpoint coverage (`/v1/...` exists) instead of contract coverage (ordering, chunk semantics, tool-call lifecycle, error payload shape, retry semantics).
**Consequences:** Client breakage in production, hidden regressions in agent frameworks, rollback pressure, and permanent trust loss in the proxy abstraction.
**Warning signs:**
- Rising “works direct-to-provider, fails through proxy” incidents
- Frequent hotfixes around translators/adapters
- Regression tests concentrated on status codes, not streaming/tool behavior
- Increased one-off compatibility toggles in config
**Prevention:**
- Freeze explicit compatibility contracts per frontend (chat, responses, anthropic, gemini) and version them
- Add characterization tests for real client traces (including streaming + tool-calls)
- Gate connector changes on cross-protocol parity suites before merge
- Treat “behavioral compatibility budget” as a release KPI, not just feature throughput
**Detection:** Contract test failure spikes, increase in compatibility-only config flags, growth in protocol-specific exception adapters.
**Phase to address:** **Phase 1 (Stabilization baseline)** and continuously in **Phase 2 (Expansion)**.

### Pitfall 2: Safety Feature Entanglement with Core Routing Path
**What goes wrong:** Safety/steering additions (dangerous command prevention, repair passes, rewrite middleware) get woven deeply into routing/execution flow, making failures hard to isolate and causing unintended model behavior shifts.
**Why it happens:** Brownfield projects add guardrails incrementally without strict boundaries between “policy decision,” “payload transformation,” and “transport execution.”
**Consequences:** Non-deterministic behavior, brittle debugging, accidental blocking/rewrites, and inability to reason about whether failures are provider-side or middleware-induced.
**Warning signs:**
- Same prompt behaves differently across minor releases without provider changes
- Increasing number of “temporary bypass flags” for safety middleware
- Incident reports where root cause remains “unknown transform interaction”
**Prevention:**
- Enforce phase-ordered transformation pipeline with invariant tests per phase
- Separate policy decision logs from transformed payload logs and backend response logs
- Introduce middleware “proof mode” (decision-only, no mutation) for canary validation
- Keep fail-open vs fail-closed behavior explicit and tested for each safety feature
**Detection:** High variance in response behavior for identical inputs; inability to replay from captures and get same intermediate states.
**Phase to address:** **Phase 1 (Architecture hardening)**.

### Pitfall 3: Retry/Failover Semantics That Corrupt Streaming or Tool State
**What goes wrong:** Retry/fallback improves availability but breaks correctness for streaming sessions or tool-calling turns (duplicated chunks, partial tool execution, or mixed-provider state).
**Why it happens:** Retries are designed as stateless HTTP retries, while agent sessions are stateful and often mid-stream.
**Consequences:** Ghost outputs, duplicate tool side-effects, user-visible incoherence, hard-to-audit incidents.
**Warning signs:**
- Duplicate assistant text in streamed responses
- Tool calls re-issued after partial success
- Higher incident rate during upstream 429/5xx events
**Prevention:**
- Make retries idempotency-aware by request type (non-streaming vs streaming vs tool-turn)
- Disable automatic replay for non-idempotent phases unless checkpointed
- Record failover decision metadata in response envelopes and captures
- Add chaos tests for partial-stream interruption + failover
**Detection:** Duplicate chunk signatures, repeated tool call IDs, mismatch between usage accounting and emitted output.
**Phase to address:** **Phase 2 (Resilience expansion)**.

### Pitfall 4: Observability That Captures Data but Not Causality
**What goes wrong:** Logs and CBOR captures exist, but incidents still take hours because there is no end-to-end correlation of request -> transform chain -> backend attempt(s) -> policy decisions.
**Why it happens:** Teams collect payloads but skip lineage metadata and canonical correlation IDs across stages.
**Consequences:** Slow MTTR, repeated incidents, low confidence in postmortems, expensive “debug by guess.”
**Warning signs:**
- Multiple logs/captures required but cannot reconstruct one request timeline quickly
- Postmortems rely on assumptions instead of event evidence
- “No repro” outcomes despite available captures
**Prevention:**
- Standardize causal trace envelope: session key, turn id, route decision id, transform ids, retry/failover chain id
- Ensure capture inspectors can reconstruct stage-by-stage timeline automatically
- Define golden incident queries (top 10 failure classes) and verify they are answerable from telemetry alone
**Detection:** MTTR trending up despite more logs; repeated “insufficient telemetry context” in incident reviews.
**Phase to address:** **Phase 1 (Observability hardening)**.

### Pitfall 5: Config Surface Explosion Without Governance
**What goes wrong:** CLI/ENV/YAML precedence remains technically correct, but growth of flags and feature toggles creates contradictory, hard-to-reason runtime behavior.
**Why it happens:** Brownfield expansions add emergency toggles and backend-specific switches faster than policy/documentation cleanup.
**Consequences:** Misconfiguration incidents, environment drift between staging/prod, unsafe defaults in shared deployments.
**Warning signs:**
- Frequent “works on my config” discrepancies
- Operators rely on tribal knowledge rather than documented profiles
- New features require multiple hidden flags to be safe
**Prevention:**
- Introduce supported config profiles (local, shared-prod, hardened-enterprise) with locked defaults
- Add startup config linter for contradictory/suspicious combinations
- Deprecate and remove stale flags on a published schedule
- Add “effective config fingerprint” to diagnostics endpoint for supportability
**Detection:** Rising config-related incidents; repeated startup warnings ignored over releases.
**Phase to address:** **Phase 1 (Operational baseline)** and cleanup in **Phase 3 (debt retirement)**.

### Pitfall 6: Test Portfolio Drift Toward Fast Unit Tests, Away from Contract Risk
**What goes wrong:** Total test count grows, but the highest-risk areas (cross-protocol translation, streaming, failover, safety interactions) are under-specified or flaky.
**Why it happens:** Unit tests are easier to add; integration/behavior/property suites are slower and require higher discipline.
**Consequences:** “Green CI, broken production” scenarios, frequent regressions in edge-case flows.
**Warning signs:**
- Regressions recur in areas already “covered” by many tests
- Streaming and multi-backend failover tests are quarantined/flaky
- Lack of invariants for translator behavior under randomized inputs
**Prevention:**
- Maintain explicit risk-based test matrix (contract, behavior, integration, property) tied to incident classes
- Prioritize deterministic harnesses for streaming and concurrent session isolation
- Add mutation/property checks around request/response translators and repair pipelines
- Track flake rate as a release gate metric
**Detection:** Regression density concentrated in integration boundaries; flaky test retries masking true instability.
**Phase to address:** **Phase 1 (Quality baseline)** and expanded in **Phase 2**.

## Moderate Pitfalls

### Pitfall 1: Personal-vs-shared resilience scoping mistakes
**What goes wrong:** Rate-limit/cooldown state is scoped incorrectly, causing one user’s failures to throttle unrelated users (or vice versa).
**Warning signs:** Cross-tenant complaints during provider throttling; unexplained cooldown propagation.
**Prevention:** Validate resilience scope rules per backend type with tenancy-focused integration tests and diagnostics visibility.
**Phase to address:** **Phase 2**.

### Pitfall 2: Memory/context features expanding before privacy boundaries mature
**What goes wrong:** Cross-session memory and context injection increase utility but create retention/redaction surprises.
**Warning signs:** Sensitive fragments appearing in unrelated sessions; unclear data retention ownership.
**Prevention:** Enforce redaction tests, retention policy audits, and per-mode (single/multi-user) privacy defaults before enabling by default.
**Phase to address:** **Phase 2**.

### Pitfall 3: Connector sprawl without lifecycle ownership
**What goes wrong:** Many backend connectors exist, but maintenance expectations differ; stale connectors silently degrade quality.
**Warning signs:** Uneven release cadence, provider breakages detected by users first.
**Prevention:** Define connector maturity tiers (core/experimental/deprecated), owner map, and minimum contract suite per tier.
**Phase to address:** **Phase 3**.

## Minor Pitfalls

### Pitfall 1: Documentation lag behind behavior toggles
**What goes wrong:** Config/docs mention features but not precise interactions/precedence edge-cases.
**Prevention:** Require docs + compatibility note updates in every behavior-changing PR.
**Phase to address:** **Phase 1 onward**.

### Pitfall 2: Over-rotation to benchmark overhead metrics
**What goes wrong:** Micro-latency optimization dominates roadmap while correctness/operability issues persist.
**Prevention:** Balance performance KPIs with compatibility SLOs, incident rate, and MTTR.
**Phase to address:** **Phase 2**.

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Stabilization baseline | Chasing new providers before compatibility contracts are frozen | Freeze compatibility matrix + characterization suite first |
| Architecture hardening | Safety logic coupling to execution path | Enforce pipeline boundaries + invariant tests |
| Resilience expansion | Retry/failover duplicates non-idempotent operations | Idempotency-aware retry policy + chaos tests |
| Observability upgrade | More logs without causal linkage | Correlated trace envelope and replayable timelines |
| Config cleanup | Flag count grows faster than governance | Profiles, linter, and deprecation lifecycle |
| Connector expansion | Capability drift across providers | Tiered connector support + owner accountability |

## Confidence Notes

- **HIGH confidence (project-specific):** configuration precedence risk, architecture drift risk, test/observability risks (grounded in current repository structure and docs).
- **MEDIUM confidence (industry pattern + partial verification):** failover/streaming/tool-state corruption and compatibility drift patterns (supported by LLM gateway ecosystem docs and implementation patterns).
- **LOW confidence:** broad market/benchmark claims from blog-style web search sources; treated as directional only.

## Sources

- Project context: `.planning/PROJECT.md`
- Product behavior/surfaces: `README.md`
- Config and precedence: `docs/user_guide/configuration.md`
- Architecture and staged initialization: `.kiro/steering/tech.md`
- Testing philosophy/contracts: `.kiro/steering/testing.md`
- Context7 (LiteLLM docs index + snippets): `/berriai/litellm` (routing/retries/fallbacks/proxy concerns)
- Ecosystem scan (directional, lower authority):
  - https://dev.to/debmckinney/openai-responses-api-in-an-llm-gateway-what-changed-and-why-it-matters-j9h
  - https://portkey.ai/blog/failover-routing-strategies-for-llms-in-production/
  - https://www.truefoundry.com/blog/llm-load-balancing
