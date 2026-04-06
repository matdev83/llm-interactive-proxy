# Product Overview

**LLM Interactive Proxy** is a universal control plane for LLM traffic. It sits between
existing AI clients and provider backends so teams can keep client integrations stable
while changing routing, safety, and operations at the proxy layer.

## Core Promise

- **Keep clients unchanged**: point clients at one endpoint instead of rewriting them
- **Stay vendor-independent**: route across provider families and backend instances
- **Run with stronger controls**: apply safety, policy, and diagnostics centrally
- **Debug with evidence**: inspect wire-level captures instead of guessing from logs

## Capability Pillars (Pattern-Level)

### 1. Frontend compatibility surfaces

The product exposes multiple API surfaces so common client SDKs and agent tooling can
run through one proxy:

- OpenAI-compatible chat/responses/models surfaces
- Anthropic-compatible messages surfaces (including dedicated Anthropic host mode)
- Gemini-compatible v1beta surfaces, including streaming and tool-call paths
- Operational endpoints for diagnostics and backend reactivation

Use `docs/user_guide/frontends/overview.md` for exhaustive endpoint details.

### 2. Backend orchestration and resilience

- Multi-backend routing with selector semantics (`backend:model`, instances, model-only)
- Health-aware backend lifecycle and failover controls
- Request shaping and policy-aware backend preparation before provider calls

### 3. Safety and governance

- Access modes for local/single-user and shared/multi-user operation
- Dangerous-command protection, tool access policies, and file sandbox guardrails
- Optional SSO/OAuth login flows with authorization policies and CAPTCHA support

### 4. Session and response quality controls

- Session enrichment and continuity services across turns
- Command-aware request pipeline and transform chain
- Optional quality-verifier and loop/behavior monitoring features

### 5. Observability and debugging

- Structured logs and usage accounting
- Byte-precise CBOR wire captures at request/response boundaries
- Replay/simulation utilities for troubleshooting regressions

### 6. Extensibility

- In-repo connector model for first-party provider adapters
- Entry-point plugin contract (`llm_proxy_backends`) for external connector packages

## Primary Use Cases

- **Teams with mixed clients/providers**: one integration point for many backends
- **Operator-focused deployments**: central policy, auth, and diagnostics
- **Agent-heavy workflows**: reliable routing plus safety controls for tool-enabled agents
- **Protocol migration periods**: move between backend providers without client rewrites

## Current Product Direction (Brownfield)

Planning artifacts under `.planning/` currently emphasize:

- Stabilize protocol compatibility on core frontend surfaces (OpenAI/Anthropic/Gemini)
- Isolate core proxy behavior from optional or connector-specific enhancements
- Reduce fragility in streaming/non-streaming and low-frequency failure paths
- Strengthen session/user isolation and regression detection quality
- Prioritize revenue-aligned capabilities only after stability/security baselines hold

## Non-Goals

- Training or fine-tuning foundation models
- Building a first-party chat client that replaces existing tools
- Acting as a standalone model hosting/inference platform
- Growing backend feature breadth at the cost of core stability

---

**License**: AGPL-3.0-or-later (see `LICENSE`)

_Updated: 2025-12-22_
_Focus on patterns and purpose; link out for exhaustive catalogs_

_Updated: 2026-01-01_
_Reason: Align product memory with then-current safety/quality feature set_

_Updated: 2026-04-06_
_Reason: Sync with current compatibility surfaces, plugin extensibility, and brownfield stabilization direction from `.planning/`_
