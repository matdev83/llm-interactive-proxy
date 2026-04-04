# LLM Interactive Proxy

## What This Is

LLM Interactive Proxy is a brownfield universal LLM gateway that sits between clients and provider backends. The current planning focus is production-grade stabilization: keep the core proxy stable and protocol-compliant, reduce architectural fragility, and make future business-facing capabilities possible without coupling optional features back into the core.

## Core Value

Provide a single, stable, protocol-compliant, and commercially credible multi-provider proxy endpoint while keeping core behavior insulated from optional and connector-specific features.

## Requirements

### Validated

- ✓ Multi-protocol frontend support exists (OpenAI, Anthropic, Gemini-compatible surfaces)
- ✓ Multi-backend routing and failover capabilities are implemented
- ✓ Safety and steering controls exist (dangerous command protection, tool controls, sandbox-related policies)
- ✓ Observability foundations exist (structured logs, wire capture including CBOR)
- ✓ Staged initialization and DI-based service wiring are established architectural patterns
- ✓ Typed `BackendCapabilityDescriptor` model wired into `BackendConfig` — backends declare capabilities explicitly (Validated in Phase 02: compatibility-contract-stabilization)
- ✓ Contract tests pin behavioral parity for OpenAI streaming/tool-call/error shapes, Anthropic event ordering/tool-use, and Gemini tool-call shapes (Validated in Phase 02: compatibility-contract-stabilization)

### Active

- [ ] Stabilize the codebase for production workloads, especially around session continuity, core protocol handling, and low-frequency failure paths
- [ ] Enforce a hard architectural boundary so non-core features do not require core changes and cannot break core proxy behavior
- [ ] Improve the testing strategy so regressions are caught earlier, test execution is faster, and backend/provider coverage is stronger
- [ ] Simplify the bidirectional request/response flow, especially the split between streaming and non-streaming paths, without losing advanced capabilities
- [ ] Harden session and user isolation to reduce the risk of cross-session or cross-user data leakage
- [ ] Prepare the platform for revenue-aligned commercial capabilities only after stability and security baselines are strong enough

### Out of Scope

- Building a first-party LLM model training/fine-tuning platform
- Replacing existing client applications with a proprietary chat client
- New vibe-coding-focused features that do not improve stability, security, or commercial readiness
- New non-core functionality that forces changes in the core proxy without a compelling stability or business justification
- Speculative feature expansion without clear customer demand or a plausible business payoff

## Context

This project is already mature and feature-rich. The immediate planning need is brownfield alignment around stabilization, modularity, and commercial readiness. Maintainer feedback highlights several planning drivers: low-frequency session interruptions, unknown state of interactive commands, frequent bug discovery despite a very large test suite, fragile module boundaries where optional features can break core behavior, overly complex bidirectional and streaming/non-streaming flows, unstable loop-detection subsystems, possible session/user isolation risk, incomplete multi-tenancy support, documentation-sync overhead, and a backlog of business-facing capabilities that only make sense after the platform is more stable.

Reference mapping artifacts:
- `.planning/codebase/STACK.md`
- `.planning/codebase/INTEGRATIONS.md`
- `.planning/codebase/ARCHITECTURE.md`
- `.planning/codebase/STRUCTURE.md`
- `.planning/codebase/CONVENTIONS.md`
- `.planning/codebase/TESTING.md`
- `.planning/codebase/CONCERNS.md`

## Constraints

- **Platform**: Python async FastAPI stack with staged startup and DI boundaries
- **Core isolation**: Non-core features must not require changes in core proxy behavior or architecture
- **Compatibility**: Main frontend connectors (OpenAI chat completions, Anthropic, Gemini) and main backend connectors must remain stable and protocol-compliant
- **Connector decoupling**: Core proxy functionality must not depend on connector-specific enhancements, and changes in the external OAuth connectors package must not regress proxy core behavior
- **Safety**: Keep safety and governance controls as first-class constraints
- **Security**: Cross-session or cross-user data leakage is unacceptable
- **Quality**: TDD-oriented workflow and existing lint/type/test expectations remain in force, but the testing approach itself is in scope for improvement
- **Business priority**: Revenue-aligned features should take precedence over non-business novelty once stability/security foundations are in place
- **Brownfield discipline**: Prefer incremental evolution over broad rewrites

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Treat this initiative as brownfield-first mapping | Existing system already contains broad capabilities and non-trivial architecture | ✓ Good |
| Defer concrete phase/task planning until scope delta is explicit | Avoid inventing roadmap items without stakeholder-confirmed priorities | ✓ Good |
| Use `.planning/codebase/*` as source of truth for current-state planning | Ensures future requirements are grounded in actual implementation | ✓ Good |
| Prioritize production stabilization before feature expansion | Fragility and regression risk currently limit confidence in the platform | - Pending |
| Preserve a hard boundary between core proxy behavior and optional enhancements | Non-core changes should not break or reshape core functionality | - Pending |
| Prefer business-value features over vibe-coding features after the foundation is stable | Open Core revenue potential should guide expansion priorities | - Pending |
| Prefer simplification and customer-requested value over speculative feature growth | The product needs a stable foundation businesses will pay for, not endless feature sprawl | - Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? -> Move to Out of Scope with reason
2. Requirements validated? -> Move to Validated with phase reference
3. New requirements emerged? -> Add to Active
4. Decisions to log? -> Add to Key Decisions
5. "What This Is" still accurate? -> Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check - still the right priority?
3. Audit Out of Scope - reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-04 after Phase 02 (compatibility-contract-stabilization) completion*
