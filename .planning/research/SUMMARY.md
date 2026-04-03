# Project Research Summary

**Project:** LLM Interactive Proxy — Universal LLM Gateway / Agent Control Plane
**Domain:** Universal LLM proxy / agent control plane (brownfield hardening + expansion)
**Researched:** 2026-04-04
**Confidence:** HIGH

## Executive Summary

This is a mature brownfield FastAPI-based proxy that routes LLM traffic across multiple providers (OpenAI, Anthropic, Gemini, etc.) with features like failover, wire-level CBOR captures, token accounting, and SSO. The codebase has 13,195 passing tests and an 8-stage staged startup. Research confirms the current architecture — canonical core model with protocol translators, DI-based service layer, connector plane — is sound and should be evolved, not rewritten.

The recommended approach is **boundary-first hardening**, not net-new feature expansion. Freeze compatibility contracts, extract remaining collaborators from orchestrator god-objects, and standardize resilience/observability before adding differentiators. The stack research unanimously says KEEP the current core (FastAPI, httpx, Pydantic v2, SQLModel, structlog, cbor2) and ADOPT OpenTelemetry, prometheus-client, sse-starlette, httpx-sse, and stamina for observability and resilience. The biggest risks are compatibility surface drift (breaking OpenAI-compatible semantics), safety feature entanglement with core routing, and retry/failover semantics that corrupt streaming or tool state — all preventable through typed boundary contracts, phase-ordered transformation pipelines, and idempotency-aware retry policies.

## Key Findings

### Recommended Stack

This is a KEEP-dominant brownfield. The current stack choices remain strong; the additions are targeted and additive.

**Core technologies (KEEP):**
- **FastAPI 0.135.3**: Active release cadence, SSE/WebSocket support, OpenAPI auto-gen — 135+ releases since 2019
- **httpx[http2]**: Async HTTP client with HTTP/2 — essential for OpenAI/Anthrik backends
- **Pydantic v2**: Request/response envelopes and config schemas are built on it — no viable replacement path
- **SQLModel + Alembic**: Wraps SQLAlchemy 2.0 + Pydantic v2 — exact sweet spot for this codebase
- **structlog**: Best-in-class structured logging, JSON output, async support
- **cbor2**: Byte-precise wire captures are core product value — replacing would invalidate debugging tooling
- **authlib**: OAuth/SAML/OIDC for multi-provider SSO — superior to httpx-oauth for this use case
- **websockets ≥14.0**: Upgrade from current ≥12.0 to eliminate legacy API deprecation warnings

**New additions (ADOPT):**
- **OpenTelemetry SDK + FastAPI/httpx instrumentations**: Distributed tracing — 2026 standard for vendor-neutral observability
- **prometheus-client ≥0.20.0**: Metrics export with multi-process uvicorn support
- **sse-starlette ≥3.3.4**: Production-ready SSE serving with client disconnect detection
- **httpx-sse ≥0.4.0**: Client-side SSE parsing for backend responses
- **stamina**: Async-native retry with exponential backoff + structured logging (by structlog author)
- **pydantic-settings (selective)**: For new subsystem config only — don't replace custom CLI > ENV > YAML system

**Dependency maintenance:** Unpin openai, pytest-asyncio, pytest, ruff from exact pins to `>=` to reduce upgrade friction. Keep black and mypy pinned for CI stability.

### Expected Features

**Must have (table stakes):**
- Multi-provider + multi-protocol compatibility with behavioral parity — teams expect one endpoint for all backends
- Reliability controls (retries, failover, circuit breaker, health checks, request dedup) — agent workloads are failure-prone
- AuthN/AuthZ + tenant isolation (API keys, SSO/OIDC/SAML, per-team scopes) — procurement blocker
- Guardrails at proxy layer (secret redaction, policy checks, tool/command/file controls) — central policy enforcement expected
- Cost + usage governance (token/cost accounting, quotas, rate limits, budget caps) — finance teams require attribution
- Deep observability (structured logs, traceable request IDs, wire-level debugging) — debugging model behavior requires evidence-grade telemetry
- Streaming + multimodal pass-through reliability — streaming correctness is no longer optional
- Configurability with safe defaults and rollout-safe toggles — ops teams need predictable behavior

**Should have (competitive):**
- Policy-as-code with per-tenant/per-route enforcement and versioned rollout — turns compliance into auditable workflow
- Experimentation controls (canary routing, traffic mirroring, A/B model tests) — faster model adoption without production risk
- Intelligent routing on SLO + cost + risk signals — measurable latency/cost/reliability improvements
- Advanced session intelligence (cross-session memory, context compaction) — token efficiency for long-running agents
- Enterprise operations UX (team-scoped logging, compliance exports) — accelerates enterprise rollout
- Remote MCP/tool gateway mediation — expands control plane to agent runtime boundaries

**Defer (v2+):**
- Deep eval platform integration (dataset replay, quality scoring, regression gating) — needs proven telemetry quality first
- Fully autonomous intelligent routing — needs strong route decision explainability
- Broad MCP/tool-gateway expansion — needs hardened permissions and sandbox controls

### Architecture Approach

Bounded orchestration core with strict seams across 4 layers: transport edge (protocol-facing), canonical core (policy-facing), connector plane (provider-facing), and control/ops plane (operator-facing). The design keeps **one stable canonical request/response model plus many edge translators**, avoiding combinatorial pairwise translation as connectors and frontends grow.

**Major components:**
1. **Transport Controllers** — Parse protocol-specific HTTP requests, emit protocol-specific responses
2. **Transport Adapters** — Convert transport payloads <-> canonical contracts (`CanonicalChatRequest`, `ResponseEnvelope`)
3. **Request Processor** — Orchestrate pre-backend pipeline (session enrich, command handling, transforms, backend handoff)
4. **Backend Completion Flow** — Orchestrate backend invocation lifecycle: availability gating, failover, usage accounting, wire capture
5. **Connector Plane** — Provider adapters implementing narrow `LLMBackend` contract
6. **Control/Ops Services** — Health checks, diagnostics, capture orchestration, usage accounting

**Key ownership rule:** Orchestrators own ordering only. Collaborators own behavior. Connectors own provider quirks only. Transport owns protocol quirks only.

### Critical Pitfalls

1. **Compatibility Surface Drift** — "OpenAI-compatible" endpoint exists but behavioral parity breaks. Prevent by freezing explicit compatibility contracts per frontend and gating connector changes on cross-protocol parity suites.

2. **Safety Feature Entanglement with Core Routing** — Guardrails woven into execution flow make failures hard to isolate. Prevent with phase-ordered transformation pipeline, invariant tests per phase, and middleware "proof mode" for canary validation.

3. **Retry/Failover Corrupting Streaming or Tool State** — Stateless HTTP retries break stateful agent sessions. Prevent with idempotency-aware retry policies, disabling auto-replay for non-idempotent phases, and chaos tests for partial-stream interruption.

4. **Observability That Captures Data but Not Causality** — Logs and captures exist but incidents still take hours. Prevent by standardizing causal trace envelopes (session key, turn ID, route decision ID, transform IDs, retry chain ID) and ensuring capture inspectors reconstruct stage-by-stage timelines automatically.

5. **Config Surface Explosion Without Governance** — Too many flags create contradictory behavior. Prevent with supported config profiles (local, shared-prod, hardened-enterprise), startup config linter, and deprecation lifecycle for stale flags.

## Implications for Roadmap

Based on research, suggested phase structure (6 phases, derived from ARCHITECTURE.md build order mapped to FEATURES.md priorities):

### Phase 1: Stabilization & Boundary Hardening
**Rationale:** All expansion work depends on safe seams. Freeze compatibility contracts before adding new capabilities.
**Delivers:** Typed boundary contracts, collaborator extraction completion, deterministic boundary validation, architecture lint rules, compatibility characterization suite
**Addresses:** Multi-provider compatibility (table stakes), streaming reliability (table stakes), deep observability baseline (table stakes)
**Avoids:** Pitfall 1 (compatibility drift), Pitfall 6 (test portfolio drift)
**Uses:** Existing typed contracts infrastructure, mypy boundary enforcement

### Phase 2: Resilience Core & Reliability Controls
**Rationale:** With stable boundaries, backend lifecycle/failover behavior can be hardened predictably.
**Delivers:** Fail-over/retry normalization (stamina integration), health-aware routing invariants, cancellation consistency, streaming resilience, circuit breaker patterns
**Addresses:** Reliability controls (table stakes), retry/failover/dedup (table stakes)
**Avoids:** Pitfall 3 (streaming/tool-state corruption), Pitfall 1 mod (personal-vs-shared scope)
**Uses:** stamina, httpx-sse for backend SSE parsing, anyio memory object streams

### Phase 3: Observability & Control Plane
**Rationale:** Reliability work generates the telemetry needed for intelligent routing and operator UX.
**Delivers:** OpenTelemetry instrumentation (traces for FastAPI + httpx), Prometheus metrics export, causal trace envelopes, diagnostic endpoint unification, capture/replay workflow improvements
**Addresses:** Deep observability (table stakes), cost/usage governance (table stakes)
**Avoids:** Pitfall 4 (data without causality), Pitfall 5 (config explosion)
**Uses:** opentelemetry-sdk, opentelemetry-instrumentation-fastapi, opentelemetry-instrumentation-httpx, prometheus-client

### Phase 4: Security & Governance Baseline
**Rationale:** AuthN/AuthZ and guardrails can now build on reliable telemetry and stable routing.
**Delivers:** authlib SSO enhancements, tenant isolation, policy-as-code engine with audit trails, guardrail enforcement (tool/file/command controls), guardrail "proof mode"
**Addresses:** AuthN/AuthZ + tenant isolation (table stakes), guardrails (table stakes), policy-as-code (differentiator)
**Avoids:** Pitfall 2 (safety entanglement), Pitfall M2 (memory/privacy before boundaries)
**Uses:** authlib, pydantic-settings (selective for policy config)

### Phase 5: Experimentation & Protocol Decoupling
**Rationale:** With reliability, observability, and security baselines, safe experimentation becomes viable.
**Delivers:** Canary routing, traffic mirroring, A/B model testing, protocol adaptation package split (frontend->canonical, canonical->backend), connector capability descriptors
**Addresses:** Experimentation controls (differentiator), intelligent routing (differentiator), advanced session intelligence (differentiator)
**Avoids:** Stabilization pitfall (new providers before contracts frozen)
**Uses:** sse-starlette ≥3.3.4 for advanced streaming surfaces

### Phase 6: Connector Ecosystem & Enterprise UX
**Rationale:** Last — connector sprawl and enterprise features require everything prior to be proven in production.
**Delivers:** Connector acceptance criteria, maturity tiers (core/experimental/deprecated), owner accountability map, plugin-ready connector plane, team-scoped UX, compliance exports
**Addresses:** Enterprise operations UX (differentiator), MCP/tool gateway (differentiator), connector standardization (differentiator)
**Avoids:** Pitfall M3 (connector sprawl), Pitfall A3 (connector sprawl anti-feature)

### Phase Ordering Rationale

- Phase 1 must come first because every subsequent phase depends on stable boundary contracts. Adding features on top of drifting interfaces multiplies complexity debt.
- Phase 2 precedes Phase 3 because resilience generates the failure data that observability must correlate. Tracing without resilience is just documentation.
- Phase 4 (security) follows reliability and observability because guardrails and tenant isolation require reliable routing and traceable enforcement — otherwise policy decisions are undifferentiated from provider failures.
- Phase 5 (experimentation) requires Phases 1-4 because canary routing and intelligent routing depend on telemetry quality, routing stability, and policy enforcement.
- Phase 6 is last because connector ecosystem maturity and enterprise UX are demand-driven; building them before the platform is proven is speculative.
- This ordering directly avoids the top pitfalls: compatibility drift (Phase 1 first), safety entanglement (Phase 4 with proof mode), streaming corruption (Phase 2 with idempotency), and causality gaps (Phase 3 with trace envelopes).

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 3 (Observability):** OpenTelemetry resource semantics for multi-instance deployment, Prometheus multi-process uvicorn worker setup patterns — needs vendor-specific exporter research
- **Phase 5 (Experimentation):** Canary routing algorithms, traffic mirroring latency impact, A/B test statistical validity for LLM quality scoring — niche domain, needs API-level research
- **Phase 6 (MCP/Tool Gateway):** Model Context Protocol specification maturity, security/permission model for tool exposure — emerging standard, sparse production patterns

Phases with standard patterns (skip research-phase):
- **Phase 1 (Stabilization):** Well-documented — typed contracts, collaborator extraction, and test coverage are established patterns with strong internal precedent
- **Phase 2 (Resilience):** stamina, circuit breakers, and idempotent retry are well-documented patterns; httpx-sse parsing is confirmed by official docs
- **Phase 4 (Security):** authlib OIDC/SAML flows, policy-as-code engine design are well-documented enterprise patterns

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All recommendations cross-referenced with Context7 (benchmark scores, release notes), official docs, and local codebase verification |
| Features | HIGH | Table stakes confirmed by LiteLLM/Portkey enterprise docs + project context; differentiators validated against competitive landscape |
| Architecture | HIGH | Grounded in actual codebase structure (staged init, DI boundaries, contracts), internal steering docs, and god-object analysis |
| Pitfalls | HIGH | Critical pitfalls are project-specific (grounded in repo structure); moderate pitfalls match LLM gateway ecosystem patterns |

**Overall confidence:** HIGH

### Gaps to Address

- **Token accounting granularity:** Research mentions tiktoken but doesn't detail per-connector token counting fidelity (some providers return token counts, others don't) — validate during Phase 3 implementation
- **Multi-instance deployment:** Research assumes single-process flow is acceptable at current scale; if multi-instance becomes a requirement, Redis adoption decision needs re-evaluation with actual scaling data
- **Connector maturity tier thresholds:** Phase 6 proposes core/experimental/deprecated tiers but doesn't define exact criteria — establish during Phase 1 planning with connector owners
- **Guardrail policy engine scope:** "Policy-as-code" is mentioned as a differentiator but the exact policy language/format (OPA/Cedar/custom) was not evaluated — needs dedicated research before Phase 4

## Sources

### Primary (HIGH confidence)
- `/berriai/litellm` — LiteLLM proxy/enterprise/guardrails docs (routing, retries, fallbacks)
- Context7: FastAPI release notes (0.135.3 as of April 2026)
- Context7: httpx releases (0.28.1, active maintenance)
- Context7: sse-starlette v3.3.4 (821 stars, production-ready)
- Context7: httpx-sse v0.4.3 (by encode contributor)
- Context7: OpenTelemetry Python official SDK
- Context7: prometheus-client FastAPI multi-process mode
- Context7: uvicorn benchmark 92/100
- Context7: pydantic 2.12 (mature ecosystem)
- Context7: structlog benchmark 92/100
- Context7: stamina (by hynek, async-native retry)
- Context7: pytest-asyncio auto mode confirmed as recommended default
- `.planning/PROJECT.md` — brownfield goals, constraints, decisions
- `README.md` — supported fronts/backends, product intent
- `.kiro/steering/tech.md` — staged init order, DI boundaries
- `.kiro/steering/structure.md` — component map, ownership by path
- `.kiro/steering/product.md` — product positioning
- `pyproject.toml` — dependency inventory and tooling config
- `docs/development_guide/typed-data-contracts.md` — canonical contracts and boundary conversion
- `docs/development_guide/plugin-api.md` — extension and plugin compatibility contract

### Secondary (MEDIUM confidence)
- Portkey AI Gateway feature index — routing, retries, canary, multimodality (official docs, breadth verified)
- Langfuse platform docs — observability/evals ecosystem expectations
- LiteLLM docs index + snippets — proxy concerns patterns

### Tertiary (LOW confidence)
- dev.to: OpenAI Responses API in LLM Gateway — directional blog post
- portkey.ai/blog: Failover routing strategies — directional blog post
- truefoundry.com/blog: LLM load balancing — directional blog post

---
*Research completed: 2026-04-04*
*Ready for roadmap: yes*
