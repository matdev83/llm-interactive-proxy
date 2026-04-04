# Roadmap: LLM Interactive Proxy

## Overview

Brownfield stabilization roadmap for a mature universal LLM proxy. The goal is to make the platform production-reliable, architecturally sound, and commercially credible — in that order. Each phase has a single dominant concern. No phase adds new features before the foundation is trustworthy.

## Phases

- [ ] **Phase 1: Audit and Triage** - Classify what is stable, broken, and uncertain without changing any behavior
- [ ] **Phase 2: Test Strategy Reset** - Fix the regression feedback loop before touching fragile code
- [ ] **Phase 3: Core Boundary Hardening** - Enforce the core/non-core separation in code
- [ ] **Phase 4: Flow and Protocol Simplification** - Simplify bidirectional flow and converge streaming paths
- [ ] **Phase 5: Reliability and Session Hardening** - Stabilize low-frequency failures, sessions, and loop detection
- [ ] **Phase 6: Security, Isolation, and Commercial Foundations** - Establish trust boundaries for paid and enterprise use

## Phase Details

### Phase 1: Audit and Triage
**Goal**: Establish a verified, honest picture of what is stable, what is broken, and what is uncertain — without changing any behavior yet.
**Depends on**: Nothing (first phase)
**Requirements**: [OPS-01, OPS-02]
**Success Criteria** (what must be TRUE):
  1. Every interactive command has a documented support status (stable, broken, uncertain, or experimental).
  2. Loop-detection behavior is documented as active, partial, or defunct with code evidence.
  3. MCP client placeholder scope is documented with a clear boundary between real and synthetic behavior.
  4. Dead configuration variants in `src/core/domain/configuration/` are identified and confirmed safe to remove.
  5. The `MagicMock` production fallback risk in `src/core/app/controllers/__init__.py` is assessed and documented.
  6. Dependency pinning gaps in `pyproject.toml` are listed with risk assessment.
  7. A triage summary exists classifying each finding as fix-in-place, defer, or needs-phase.
**Plans**: TBD

### Phase 2: Test Strategy Reset
**Goal**: Fix the regression feedback loop before touching any fragile code. Make the test suite a reliable safety net rather than a false confidence generator.
**Depends on**: Phase 1
**Requirements**: [TEST-01, TEST-02, TEST-03, TEST-04]
**Success Criteria** (what must be TRUE):
  1. A fast stabilization-focused test slice exists and runs reliably in under 2 minutes covering core proxy behavior.
  2. Architectural boundary tests exist and would catch a non-core change that breaks core behavior.
  3. Protocol regression tests cover OpenAI, Anthropic, and Gemini frontends for both streaming and non-streaming.
  4. Main backend connectors (OpenAI, Anthropic, Gemini, OpenRouter) have contract-level tests.
  5. Session isolation is explicitly tested — no state leaks between concurrent or sequential sessions.
  6. Streaming/non-streaming equivalence is explicitly tested for shared semantics.
  7. Buffered capture concurrency regression (`_sequence_counter` in `src/core/services/buffered_wire_capture_service.py`) is covered.
  8. Runtime dependency versions are pinned to tested ranges.
**Plans**: TBD

### Phase 3: Core Boundary Hardening
**Goal**: Enforce in code the boundary between core proxy behavior and optional/non-core features so that non-core changes cannot break or reshape the core.
**Depends on**: Phase 2
**Requirements**: [STAB-02, STAB-03, STAB-04, ARCH-01]
**Success Criteria** (what must be TRUE):
  1. The `MagicMock` production fallback in `src/core/app/controllers/__init__.py` is removed; DI failures produce structured errors.
  2. Core service paths do not import or depend on connector-specific feature code.
  3. The external OAuth connector package boundary is explicit and tested.
  4. Dead configuration variants identified in Phase 1 are removed and call sites consolidated.
  5. Non-core features (context compression, random model replacement, interactive commands) are behind explicit interfaces the core does not depend on.
  6. All Phase 2 boundary tests remain green throughout.
**Plans**: TBD

### Phase 4: Flow and Protocol Simplification
**Goal**: Reduce the complexity of the bidirectional request/response path and converge streaming and non-streaming behavior where the semantics should be identical.
**Depends on**: Phase 3
**Requirements**: [COMP-01, COMP-02, COMP-03, COMP-04, COMP-05, ARCH-02, ARCH-03]
**Success Criteria** (what must be TRUE):
  1. The bidirectional flow can be traced end-to-end without hidden branches by a maintainer unfamiliar with the codebase.
  2. `responses_to_domain_stream_chunk` in `src/core/domain/translators/responses/streaming.py` is decomposed into smaller functions with individual contract tests.
  3. Streaming and non-streaming paths share a single implementation of behavior that should be identical.
  4. `src/core/app/controllers/responses_controller.py` has reduced responsibility and is no longer a single-file accumulation of unrelated concerns.
  5. All Phase 2 protocol regression tests remain green.
  6. No new core dependencies on connector-specific code are introduced.
**Plans**: TBD

### Phase 5: Reliability and Session Hardening
**Goal**: Stabilize low-frequency failure paths, session continuity, and the loop-detection subsystem so the system behaves predictably under real production conditions.
**Depends on**: Phase 4
**Requirements**: [STAB-01, ARCH-04]
**Success Criteria** (what must be TRUE):
  1. Known low-frequency session interruption paths have regression tests and confirmed fixes.
  2. Loop detection is either working and tested, or explicitly disabled with documented rationale — it does not silently affect core flows.
  3. Buffered capture sequence ordering is race-safe under concurrent load.
  4. Codex adapter failure paths (`src/connectors/openai_codex/`) produce structured errors rather than silent fallbacks.
  5. Pattern analyzer limits are configurable rather than hardcoded constants.
**Plans**: TBD

### Phase 6: Security, Isolation, and Commercial Foundations
**Goal**: Establish the trust boundary required for future paid and enterprise-facing capabilities.
**Depends on**: Phase 5
**Requirements**: [SEC-01, SEC-02, SEC-03]
**Success Criteria** (what must be TRUE):
  1. Cross-session and cross-user data leakage is demonstrably prevented in all supported deployment paths.
  2. Shell tool execution in `src/core/services/universal_tool_executor.py` is allowlist-controlled and does not use `shell=True` with dynamic input.
  3. Codex adapter translation failures are observable and do not silently corrupt output.
  4. A documented multi-tenant isolation model exists that future commercial work can build on.
  5. All Phase 2 and Phase 4 protocol regression tests remain green after security hardening.
**Plans**: TBD

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Audit and Triage | 0/TBD | Not started | - |
| 2. Test Strategy Reset | 0/TBD | Not started | - |
| 3. Core Boundary Hardening | 0/TBD | Not started | - |
| 4. Flow and Protocol Simplification | 0/TBD | Not started | - |
| 5. Reliability and Session Hardening | 0/TBD | Not started | - |
| 6. Security, Isolation, and Commercial Foundations | 0/TBD | Not started | - |

---
*Roadmap defined: 2026-04-04*
*Last updated: 2026-04-04 after reformatting to GSD template format*
