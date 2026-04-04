# Roadmap: LLM Interactive Proxy

## Overview

This roadmap is derived directly from the v1 requirements and ordered for a brownfield system: harden internal boundaries first, then stabilize compatibility, then make failure handling safe, then improve operator visibility, and finally expand governance and extension surfaces on top of a trustworthy platform.

## Phase Order

- [ ] **Phase 1: Boundary and Configuration Hardening** - Freeze internal seams, reduce architectural drag, and prevent contradictory runtime states
- [ ] **Phase 2: Compatibility Contract Stabilization** - Make OpenAI, Anthropic, Gemini, and backend capability behavior explicit and dependable
- [ ] **Phase 3: Resilience and Failover Safety** - Standardize retries, circuit breaking, streaming recovery, and side-effect-safe failover
- [ ] **Phase 4: Observability and Operator Diagnostics** - Add causal tracing, metrics, capture correlation, and live operational visibility
- [ ] **Phase 5: Tenant Governance, Safety Independence, and Connector Extensibility** - Complete tenant controls, scoped key management, safety isolation, and plugin-ready connector expansion

## Phase Details

### Phase 1: Boundary and Configuration Hardening
**Goal**: Make the core platform safe to evolve by enforcing typed boundaries, shrinking monolithic responsibilities, updating stale dependencies, and blocking invalid runtime configuration before traffic starts.
**Depends on**: Nothing (first phase)
**Requirements**: [ARCH-01, ARCH-02, ARCH-03, SEC-03]
**Success Criteria**:
1. Developers changing a port or adapter boundary get immediate type or contract failures instead of discovering drift only at runtime.
2. Operators starting the proxy with contradictory CLI, ENV, and YAML settings receive a clear validation error before the service accepts requests.
3. Maintainers can change translation, backend, or request-processing collaborators without editing god-object modules for unrelated behavior.
4. The default verification path runs on current dependencies without suppressed deprecation warnings in the standard test suite.

### Phase 2: Compatibility Contract Stabilization
**Goal**: Preserve the product promise that existing AI clients can use the proxy without custom rewrites by making protocol behaviors explicit, tested, and configuration-driven.
**Depends on**: Phase 1
**Requirements**: [COMP-01, COMP-02, COMP-03, COMP-04]
**Plans**: 3 plans
**Success Criteria**:
1. An OpenAI-compatible client can stream, call tools, and receive spec-shaped errors through the proxy without compatibility-specific patches.
2. An Anthropic-compatible client can use streaming and tool-use through the proxy with expected event ordering and response semantics.
3. A Gemini-compatible client can use tools and streaming behavior through the proxy without provider-specific workaround flags.
4. Operators can declare backend capabilities through typed configuration and see routing and validation honor those descriptors consistently.

Plans:
- [ ] 02-01-PLAN.md — Add BackendCapabilityDescriptor typed model and wire into BackendConfig (COMP-04)
- [ ] 02-02-PLAN.md — OpenAI streaming, tool-call, and error-shape contract tests (COMP-01)
- [ ] 02-03-PLAN.md — Anthropic event-ordering and Gemini tool-call contract tests (COMP-02, COMP-03)

### Phase 3: Resilience and Failover Safety
**Goal**: Make backend instability survivable by normalizing retries, health gating, streaming recovery, and failover semantics across connector families.
**Depends on**: Phase 2
**Requirements**: [REL-01, REL-02, REL-03, REL-04]
**Success Criteria**:
1. During transient provider failures, requests retry with bounded async backoff and either recover cleanly or fail with deterministic retry history.
2. Unhealthy backends stop receiving routed traffic automatically and only re-enter service after configured health thresholds are met.
3. A user streaming a response does not see duplicated output or corrupted tool-call state when a backend fails mid-stream.
4. Failover between backend instances preserves request context and avoids repeating non-deterministic side effects.

### Phase 4: Observability and Operator Diagnostics
**Goal**: Give operators evidence-grade visibility into request flow, latency, failures, and routing decisions so incidents can be diagnosed quickly and confidently.
**Depends on**: Phase 3
**Requirements**: [OBS-01, OBS-02, OBS-03, OBS-04]
**Success Criteria**:
1. An operator can trace one request from frontend ingress through transforms and backend response in a single distributed trace.
2. An operator can view request counts, error rates, latency distributions, and backend health from Prometheus-compatible metrics without ad-hoc log parsing.
3. An incident reviewer can jump from a trace or route decision to the matching CBOR capture and reconstruct the end-to-end exchange.
4. Operators can inspect active sessions, routing decisions, and backend status from a live diagnostic surface while traffic is in flight.

### Phase 5: Tenant Governance, Safety Independence, and Connector Extensibility
**Goal**: Finish the v1 governance surface by adding tenant-aware controls, safe credential lifecycle management, routing-independent safety execution, and a stable external connector contract.
**Depends on**: Phase 4
**Requirements**: [SEC-01, SEC-02, SEC-04, ARCH-04]
**Success Criteria**:
1. A tenant admin can define tenant-specific access, rate, and model policies that take effect without impacting other tenants.
2. Operators can rotate API keys and assign scoped permissions to client groups without service downtime or blanket credential replacement.
3. Safety controls such as steering, dangerous-command protection, and sandboxing can be enabled, audited, or fail independently from request routing.
4. An external connector author can follow the documented plugin contract, register a connector, and have it discovered predictably by the proxy.

## Requirement Coverage

| Phase | Requirement Count | Requirement IDs |
|-------|-------------------|-----------------|
| Phase 1 | 4 | ARCH-01, ARCH-02, ARCH-03, SEC-03 |
| Phase 2 | 4 | COMP-01, COMP-02, COMP-03, COMP-04 |
| Phase 3 | 4 | REL-01, REL-02, REL-03, REL-04 |
| Phase 4 | 4 | OBS-01, OBS-02, OBS-03, OBS-04 |
| Phase 5 | 4 | SEC-01, SEC-02, SEC-04, ARCH-04 |

**Coverage validation:**
- v1 requirements total: 20
- Mapped to exactly one phase: 20
- Unmapped: 0
- Duplicate mappings: 0

## Ordering Rationale

- Phase 1 comes first because the brownfield system needs stable seams and config governance before any deeper expansion or hardening can be trusted.
- Phase 2 follows because compatibility is the core product promise and should be frozen on top of those safer boundaries.
- Phase 3 then hardens retry and failover behavior against the now-explicit contracts.
- Phase 4 adds operator-facing evidence once routing and failure behavior are stable enough to measure meaningfully.
- Phase 5 finishes the v1 capability set by layering tenant governance, safety isolation, and external connector growth on top of a hardened platform.

---
*Roadmap defined: 2026-04-04*
*Last updated: 2026-04-04 during roadmap creation from v1 requirements*
