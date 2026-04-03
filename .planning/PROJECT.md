# LLM Interactive Proxy

## What This Is

LLM Interactive Proxy is a brownfield universal LLM gateway that sits between clients and provider backends. It provides compatibility layers, routing and failover controls, safety/steering features, and evidence-oriented observability without requiring client rewrites.

## Core Value

Provide a single, safer, and more controllable proxy endpoint for multi-provider LLM workflows while preserving client compatibility.

## Requirements

### Validated

- ✓ Multi-protocol frontend support exists (OpenAI, Anthropic, Gemini-compatible surfaces)
- ✓ Multi-backend routing and failover capabilities are implemented
- ✓ Safety and steering controls exist (dangerous command protection, tool controls, sandbox-related policies)
- ✓ Observability foundations exist (structured logs, wire capture including CBOR)
- ✓ Staged initialization and DI-based service wiring are established architectural patterns

### Active

- [ ] Define next milestone scope after codebase mapping review (brownfield delta only)

### Out of Scope

- Building a first-party LLM model training/fine-tuning platform
- Replacing existing client applications with a proprietary chat client
- Planning detailed implementation phases before brownfield scope is explicitly selected

## Context

This project is already mature and feature-rich. The immediate planning need is brownfield alignment: map the current system accurately, then select incremental scope with minimal architecture drift.

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
- **Compatibility**: Preserve existing frontend/backend behavior for current clients
- **Safety**: Keep safety and governance controls as first-class constraints
- **Quality**: TDD-oriented workflow and existing lint/type/test expectations remain in force
- **Brownfield discipline**: Prefer incremental evolution over broad rewrites

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Treat this initiative as brownfield-first mapping | Existing system already contains broad capabilities and non-trivial architecture | ✓ Good |
| Defer concrete phase/task planning until scope delta is explicit | Avoid inventing roadmap items without stakeholder-confirmed priorities | ✓ Good |
| Use `.planning/codebase/*` as source of truth for current-state planning | Ensures future requirements are grounded in actual implementation | ✓ Good |

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
*Last updated: 2026-04-04 after brownfield codebase mapping alignment*
