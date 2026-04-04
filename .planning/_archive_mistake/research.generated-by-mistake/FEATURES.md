# Feature Landscape

**Domain:** Universal LLM proxy / agent control plane (brownfield, 2026)
**Researched:** 2026-04-04

## Table Stakes

Features users now expect by default. Missing these makes the product feel behind.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Multi-provider + multi-protocol compatibility | Teams expect one control-plane endpoint for OpenAI/Anthropic/Gemini-style clients and heterogeneous backends | Med | **Capability expansion**. Keep protocol translation stable first; breadth without compatibility quality is net negative. |
| Reliability controls: retries, failover, circuit breaker, health checks, request dedup | Production agent workloads are long-running and failure-prone; users assume self-healing behavior | Med | **Platform hardening**. Treat routing policy + failure policy as first-class config, not ad hoc flags. |
| AuthN/AuthZ + tenant isolation (API keys, SSO/OIDC/SAML in shared mode, per-team scopes) | Security baselines moved from “nice to have” to procurement blocker | High | **Platform hardening**. Must support both single-user dev mode and shared enterprise mode cleanly. |
| Guardrails at proxy layer (secret redaction, policy checks, tool/command/file controls) | Agent execution risk is now explicit; customers expect central policy enforcement | High | **Platform hardening**. Must be policy-driven and auditable; avoid brittle regex-only enforcement. |
| Cost + usage governance (token/cost accounting, quotas, rate limits, budget caps) | Multi-model usage explodes spend without controls; finance and platform teams require attribution | Med | **Platform hardening**. Per-key/team/project budgets are expected. |
| Deep observability (structured logs, traceable request IDs, latency/error metrics, wire-level debugging) | Debugging model behavior and provider mismatches requires evidence-grade telemetry | Med | **Platform hardening**. Keep low-level captures optional but deterministic and reproducible. |
| Streaming + multimodal pass-through reliability | Modern clients expect streaming and non-text modalities to work consistently | High | **Capability expansion + hardening**. Streaming correctness is table stakes now. |
| Configurability with safe defaults (policy-as-config, clear precedence, rollout-safe toggles) | Ops teams expect predictable behavior across environments | Med | **Platform hardening**. Preserve explicit config precedence and support progressive rollout. |

## Differentiators

These are not universally required on day one, but they materially improve product selection and retention.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Policy-as-code with per-tenant/per-route enforcement and versioned rollout | Turns safety/compliance from static checklists into auditable platform workflow | High | Strong strategic differentiator if tied to audit trails and simulation. |
| Experimentation controls (canary routing, traffic mirroring, A/B model tests) | Lets teams adopt new models faster without destabilizing production | High | Depends on robust observability + replay tooling. |
| First-class eval loop integration (dataset replay, quality scoring hooks, regression gating) | Converts proxy from transport layer into quality control plane for LLM systems | High | Best paired with Langfuse-like evaluation workflows. |
| Intelligent routing on SLO + cost + risk signals (not just static model maps) | Delivers measurable latency/cost/reliability improvements automatically | High | Requires strong telemetry and route decision explainability. |
| Advanced session intelligence (cross-session memory controls, context compaction/enforcement) | Improves long-running agent success and token efficiency | Med | Must remain opt-in and bounded to avoid hidden behavior surprises. |
| Enterprise operations UX (team-scoped logging controls, compliance exports, private-route controls) | Accelerates enterprise rollout and governance acceptance | Med | Particularly important for regulated and multi-team environments. |
| Remote MCP/tool gateway mediation | Expands control plane from “LLM calls” to “agent runtime boundaries” | High | High upside, but security and permissioning must be mature first. |

## Anti-Features

Deliberately avoid these; they create distraction, risk, or strategic drift.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Building a first-party chat app/UI as core roadmap thrust | Competes with customers’ clients and dilutes control-plane focus | Keep UX focused on operator/admin workflows, APIs, and diagnostics. |
| Becoming a long-term conversation database of record | Expands compliance burden and product scope dramatically | Keep retention minimal/operational; integrate with external data systems where needed. |
| Unbounded “connector sprawl” without quality gates | Many low-quality integrations hurt reliability and trust | Use connector acceptance criteria: test coverage, compatibility matrix, health semantics, owner accountability. |
| Hidden automatic prompt/response mutation by default | Undermines trust and makes incidents hard to debug | Make all transformations explicit, observable, and opt-in with trace markers. |
| Regex-only “security theater” guardrails | Easy to bypass; creates false confidence | Use layered controls: policy engine + scoped permissions + moderation/classification hooks + audit logs. |
| Over-centralized monolith policy engine that blocks all traffic on misconfig | Single bad deploy can create platform-wide outage | Use staged rollout, per-tenant policies, dry-run mode, and fast kill-switches. |
| Feature creep into model training/fine-tuning platform | Violates core product identity and stretches team capacity | Stay focused on routing, control, safety, and observability around external model providers. |

## Feature Dependencies

```text
AuthN/AuthZ + Tenant Isolation -> Per-tenant Budgets/Rate Limits -> Enterprise Compliance Exports
Structured Observability -> Intelligent Routing (SLO/cost/risk aware) -> Canary/A-B/Mirroring
Policy Engine -> Guardrails (tool/file/command controls) -> Auditable Enforcement + Incident Forensics
Protocol Compatibility Baseline -> Streaming/Multimodal Reliability -> Advanced Session Intelligence
Traffic Capture/Replay -> Eval Integrations -> Regression Gating for routing/policy changes
```

## MVP Recommendation

Prioritize:
1. Reliability + resilience baseline (retries, failover, circuit breakers, health checks, dedup)
2. Security + governance baseline (auth, tenant scopes, guardrails, auditable policy enforcement)
3. Cost + observability baseline (usage attribution, budgets/rate limits, evidence-grade tracing)

Then add one differentiator:
4. Safe experimentation controls (canary + mirroring + rollback)

Defer:
- Deep eval platform and advanced autonomous routing until telemetry quality and policy reliability are proven in production.
- Broad MCP/tool-gateway expansion until permissions and sandbox controls are hardened.

## Sources

- Project context and existing capability surface:
  - `.planning/PROJECT.md`
  - `README.md`
  - `docs/user_guide/index.md`
  - `.kiro/steering/product.md`
- LiteLLM AI Gateway + Enterprise docs (routing, budgets, guardrails, enterprise controls) — **HIGH confidence**:
  - https://docs.litellm.ai/docs/proxy/enterprise
  - Context7: `/berriai/litellm` (proxy/enterprise/guardrails references)
- Portkey AI Gateway feature index (routing, retries, circuit breaking, cache, canary, multimodality, budget/rate controls) — **MEDIUM confidence** (official docs page, breadth verified, depth not fully validated here):
  - https://portkey.ai/docs/product/ai-gateway
- Langfuse platform docs (observability/evals/prompt mgmt ecosystem expectations around LLM production workflows) — **MEDIUM confidence** for control-plane adjacency:
  - Context7: `/langfuse/langfuse-docs`

