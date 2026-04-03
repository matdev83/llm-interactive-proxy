# LLM Interactive Proxy

## What This Is

LLM Interactive Proxy is a universal LLM gateway that lets existing AI clients talk to many backend providers through one compatible endpoint. It is built for developers, operators, and agent-driven workflows that need routing, failover, safety controls, observability, and protocol translation without rewriting the client side.

## Core Value

Give any compatible LLM client a safer, smarter, vendor-independent control plane without forcing that client to change how it works.

## Requirements

### Validated

- ✓ OpenAI-, Anthropic-, and Gemini-compatible frontend surfaces route through a shared proxy layer — existing
- ✓ Requests can be routed across multiple backend families with failover and health-aware behavior — existing
- ✓ Safety and steering features can shape or block risky agent behavior at the proxy layer — existing
- ✓ Operators can inspect traffic through structured logging and byte-precise CBOR wire captures — existing
- ✓ Configuration resolves through CLI, environment, YAML, and defaults with documented precedence — existing
- ✓ The system supports session-oriented behavior, usage tracking, and debugging-oriented tooling — existing

### Active

- [ ] Improve reliability and operational safety across provider integrations and long-running agent sessions
- [ ] Expand and harden compatibility across supported clients, backends, and protocol variants
- [ ] Strengthen observability, debugging, and operator control surfaces for real-world deployments

### Out of Scope

- Training or fine-tuning foundation models inside this project — the proxy routes to external providers instead of becoming a model platform
- Replacing client applications with a first-party chat product — the main value is compatibility and control at the proxy layer
- Acting as a long-term conversation datastore of record — persistent storage is limited to operational/project features rather than full productized chat history

## Context

This is a mature brownfield Python project centered on an async FastAPI proxy with staged initialization, dependency injection, transport-neutral ports/adapters, and provider-specific connectors. The codebase already supports multiple frontend protocols, many backend families, structured safety features, traffic capture, session management, usage accounting, and optional enterprise-style access controls. Existing docs emphasize vendor independence, resilience, debugging with evidence, and improving agent workflows without requiring client rewrites.

## Constraints

- **Tech stack**: Python 3.10+, FastAPI, httpx, Pydantic v2, SQLModel/Alembic — existing architecture and tooling should remain the default path
- **Architecture**: Staged startup and DI-managed services — new work should fit established lifecycle and interface boundaries
- **Config model**: CLI > ENV > YAML > defaults — user-facing configuration changes must preserve precedence semantics
- **Quality**: TDD first, then targeted verification, then broader regression coverage — changes must be proven with tests
- **Platform**: Windows-first contributor workflow using `./.venv/Scripts/python.exe` — commands and scripts should remain compatible with this environment

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Use an async FastAPI proxy as the central control plane | Existing clients need compatible HTTP surfaces with low-friction adoption | ✓ Good |
| Keep staged initialization for startup wiring | Infrastructure, services, backends, and controllers have meaningful ordering constraints | ✓ Good |
| Use DI and interface boundaries for core services | Testability and replacement of cross-cutting collaborators are important in a large brownfield codebase | ✓ Good |
| Preserve transport-neutral ports/adapters where possible | Protocol translation logic should stay reusable outside the FastAPI transport layer | ✓ Good |
| Treat traffic capture and observability as first-class product features | Debugging LLM systems requires evidence, not only logs and assumptions | ✓ Good |

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
*Last updated: 2026-04-04 after initialization*
