# Roadmap: LLM Interactive Proxy

**Defined:** 2026-04-04
**Revised:** 2026-04-04
**Scope Basis:** `.planning/PROJECT.md`, `.planning/PRIORITIES.md`, `.planning/SCOPE-SELECTION.md`, `.planning/REQUIREMENTS.md`, and `.planning/codebase/*.md`

## Roadmap Principles

- Stabilize before expanding features.
- Simplify before adding new moving parts.
- Audit and prove current behavior before changing it.
- Fix the feedback loop before touching anything fragile.
- Protect core proxy behavior from optional and connector-specific changes.
- Prefer customer-requested and revenue-aligned outcomes over speculative feature growth.
- Only pursue commercial follow-on work after the platform is stable enough to carry it safely.

---

## Phase 1: Audit and Triage

**Goal:** Establish a verified, honest picture of what is stable, what is broken, and what is uncertain — without changing any behavior yet.

**Why first:** You cannot safely simplify, harden, or test what you have not accurately classified. This phase produces the evidence base that every subsequent phase depends on. It is deliberately read-only and classification-focused.

**Concrete scope:**
- Audit and document the actual support status of every interactive command. Classify each as: stable, broken, uncertain, or experimental. Record findings in `.planning/codebase/` or a dedicated audit doc.
- Audit the functional state of multi-tier loop detection. Determine whether it is currently active, partially active, or silently disabled. Document what it does and does not protect against.
- Audit the MCP client (`src/core/services/universal_mcp_client.py`) and confirm the scope of placeholder behavior. Document which operations are real vs synthetic.
- Audit the duplicate/experimental configuration models (`src/core/domain/configuration/reasoning_config*.py`) and confirm which variants are live, which are dead, and which call sites reference each.
- Audit the `MagicMock` fallback in `src/core/app/controllers/__init__.py` and confirm whether it can be reached in production deployments.
- Audit the dependency pinning state in `pyproject.toml` and identify which runtime packages are unpinned and at risk of silent behavior drift.
- Produce a short triage summary that classifies each finding as: fix-in-place, defer, or needs-phase.

**Success Criteria:**
- Every interactive command has a documented support status.
- Loop-detection behavior is documented as active, partial, or defunct with evidence.
- MCP placeholder scope is documented with a clear boundary between real and synthetic behavior.
- Dead configuration variants are identified and confirmed safe to remove.
- The `MagicMock` production fallback risk is assessed and documented.
- Dependency pinning gaps are listed with risk assessment.
- A triage summary exists that feeds directly into Phase 2 and Phase 3 scope.

**Requirements Covered:** `OPS-01`, `OPS-02`

---

## Phase 2: Test Strategy Reset

**Goal:** Fix the regression feedback loop before touching any fragile code. Make the test suite a reliable safety net rather than a false confidence generator.

**Why second:** The maintainer's own observation is that new bugs keep appearing in core behavior despite a very large test suite. That means the suite is not structured to catch the right things. Fixing this before Phase 3 and Phase 4 means every subsequent change has a trustworthy safety net.

**Concrete scope:**
- Define and implement a fast stabilization-focused test slice (e.g. a pytest marker or subset) that covers core proxy behavior and can run in under 2 minutes. This is the slice developers run on every change.
- Add architectural boundary tests that assert non-core features do not require core changes and do not break core proxy behavior when disabled or modified. These tests should fail if the boundary is violated.
- Expand protocol regression coverage for the three main frontends: OpenAI chat completions, Anthropic messages, and Gemini. Cover both streaming and non-streaming paths with contract-level assertions.
- Expand backend connector coverage for the main backends (OpenAI, Anthropic, Gemini, OpenRouter) with protocol-level request/response contract tests.
- Add explicit session isolation tests that assert no state leaks between concurrent or sequential sessions.
- Add streaming/non-streaming equivalence tests for cases where public API semantics should produce identical outcomes.
- Address the under-specified concurrency regression for `_sequence_counter` in `src/core/services/buffered_wire_capture_service.py`.
- Pin unpinned runtime dependencies identified in Phase 1 to tested ranges.

**Success Criteria:**
- A fast test slice exists and runs reliably in under 2 minutes covering core proxy behavior.
- Architectural boundary tests exist and would catch a non-core change that breaks core behavior.
- Protocol regression tests cover OpenAI, Anthropic, and Gemini frontends for both streaming and non-streaming.
- Main backend connectors have contract-level tests.
- Session isolation is explicitly tested.
- Streaming/non-streaming equivalence is explicitly tested for shared semantics.
- Buffered capture concurrency regression is covered.
- Runtime dependency versions are pinned to tested ranges.

**Requirements Covered:** `TEST-01`, `TEST-02`, `TEST-03`, `TEST-04`

---

## Phase 3: Core Boundary Hardening

**Goal:** Enforce in code the boundary between core proxy behavior and optional/non-core features so that non-core changes cannot break or reshape the core.

**Why third:** Phase 1 identified the boundary violations. Phase 2 gave us the safety net to change things safely. Now we can enforce the boundary structurally.

**Concrete scope:**
- Remove the `MagicMock` fallback from `src/core/app/controllers/__init__.py` and replace with a hard fail-fast service-resolution error. Core should never silently degrade into synthetic behavior.
- Enforce that core proxy functionality depends on stable internal contracts (`CanonicalChatRequest`, `ResponseEnvelope`, `BackendTarget`) rather than connector-specific feature code. Identify and remove any direct connector-specific imports or behavior in core service paths.
- Isolate the external OAuth connector package boundary so that changes or failures in that package cannot propagate into core proxy behavior. This may mean a thin adapter layer or explicit interface contract at the boundary.
- Consolidate dead configuration variants identified in Phase 1 (`reasoning_config_new.py`, `reasoning_config_new2.py`) to a single canonical model.
- Classify and isolate non-core features (context compression, random model replacement, interactive commands) behind explicit interfaces so they can be disabled, changed, or removed without touching core proxy code.
- Verify that the Phase 2 boundary tests pass after each structural change.

**Success Criteria:**
- The `MagicMock` production fallback is gone. DI failures produce structured errors, not synthetic responses.
- Core service paths do not import or depend on connector-specific feature code.
- The OAuth connector package boundary is explicit and tested.
- Dead configuration variants are removed and call sites are consolidated.
- Non-core features are behind explicit interfaces that the core does not depend on.
- All Phase 2 boundary tests remain green throughout.

**Requirements Covered:** `STAB-02`, `STAB-03`, `STAB-04`, `ARCH-01`

---

## Phase 4: Flow and Protocol Simplification

**Goal:** Reduce the complexity of the bidirectional request/response path and converge streaming and non-streaming behavior where the semantics should be identical.

**Why fourth:** The boundary is now enforced and the test suite is trustworthy. This is the right moment to simplify the most complex and fragile part of the system — the data flow — because we can now do it safely.

**Concrete scope:**
- Map the full bidirectional flow end-to-end: inbound request → transforms → backend dispatch → response → outbound. Identify every branch, adapter, and translation step. Document the simplified target shape.
- Decompose `src/core/domain/translators/responses/streaming.py` (`responses_to_domain_stream_chunk`, complexity score 113) into smaller pure functions organized by event family, each with contract tests.
- Identify shared logic between streaming and non-streaming execution paths and consolidate it into shared collaborators. The goal is one implementation of shared behavior, not two diverging copies.
- Reduce the size and responsibility of `src/core/app/controllers/responses_controller.py` (currently ~2081 lines) by extracting bounded collaborators behind existing DI interfaces.
- Verify that OpenAI, Anthropic, and Gemini frontend protocol compliance is preserved throughout all refactoring. The Phase 2 protocol regression tests are the gate.
- Verify that main backend connector contracts are preserved throughout.

**Success Criteria:**
- The bidirectional flow can be traced end-to-end without hidden branches by a maintainer unfamiliar with the codebase.
- `responses_to_domain_stream_chunk` is decomposed into smaller functions with individual contract tests.
- Streaming and non-streaming paths share a single implementation of behavior that should be identical.
- `responses_controller.py` has reduced responsibility and is no longer a single-file accumulation of unrelated concerns.
- All Phase 2 protocol regression tests remain green.
- No new core dependencies on connector-specific code are introduced.

**Requirements Covered:** `COMP-01`, `COMP-02`, `COMP-03`, `COMP-04`, `COMP-05`, `ARCH-02`, `ARCH-03`

---

## Phase 5: Reliability and Session Hardening

**Goal:** Stabilize low-frequency failure paths, session continuity, and the loop-detection subsystem so the system behaves predictably under real production conditions.

**Why fifth:** The flow is now simpler and the test suite is stronger. This is the right time to address the remaining reliability gaps that only show up in less common paths — the ones that cause mid-session interruptions and hard-to-reproduce bugs.

**Concrete scope:**
- Investigate and fix the known low-frequency session interruption paths identified in Phase 1 triage. Each fix must be accompanied by a regression test that would have caught it.
- Stabilize or safely isolate multi-tier loop detection based on the Phase 1 audit findings. If it is defunct, either restore it to a working and tested state or explicitly disable it and document the decision. It must not silently affect core proxy flows in an undefined state.
- Address the `_sequence_counter` race condition in `src/core/services/buffered_wire_capture_service.py` if not already resolved in Phase 2.
- Harden the Codex compatibility adapters (`src/connectors/openai_codex/client_families/droid_adapter.py`, `compat.py`, `executor.py`) by replacing broad exception swallowing with structured error handling and behavioral snapshot tests.
- Externalize the hardcoded pattern analyzer memory ceilings (`_content_stats` threshold at 10000, event history cap at 100) to configuration.

**Success Criteria:**
- Known low-frequency session interruption paths have regression tests and confirmed fixes.
- Loop detection is either working and tested, or explicitly disabled with documented rationale. It does not silently affect core flows.
- Buffered capture sequence ordering is race-safe under concurrent load.
- Codex adapter failure paths produce structured errors rather than silent fallbacks.
- Pattern analyzer limits are configurable rather than hardcoded constants.

**Requirements Covered:** `STAB-01`, `ARCH-04`

---

## Phase 6: Security, Isolation, and Commercial Foundations

**Goal:** Establish the trust boundary required for future paid and enterprise-facing capabilities.

**Why sixth:** Businesses will not pay for advanced capabilities on top of a system that cannot confidently protect sessions, users, or tenant boundaries. This phase makes the platform credible for commercial use.

**Concrete scope:**
- Audit and harden cross-session and cross-user isolation in request handling, session state, persistence (`var/memory.sqlite3`, `var/sso_auth.db`, `var/state/b2bua_continuity.sqlite3`), logging, and CBOR wire capture replay paths.
- Harden `src/core/services/universal_tool_executor.py`: replace `shell=True` subprocess execution with an explicit allowlist/policy layer and bind shell execution to trusted modes only.
- Harden exception swallowing in `src/connectors/openai_codex/client_families/droid_adapter.py`: add structured error counters and an optional strict mode that surfaces translation failures.
- Establish a documented and enforceable multi-tenant isolation model: define what tenant boundaries mean in this system, where they need to be enforced, and what the minimum viable implementation looks like for future billing, token management, and access-control work.
- Verify that all security hardening preserves protocol compliance and core request handling behavior. The Phase 2 and Phase 4 regression tests are the gate.

**Success Criteria:**
- Cross-session and cross-user data leakage is demonstrably prevented in all supported deployment paths.
- Shell tool execution is allowlist-controlled and does not use `shell=True` with dynamic input.
- Codex adapter translation failures are observable and do not silently corrupt output.
- A documented multi-tenant isolation model exists that future commercial work can build on.
- All Phase 2 and Phase 4 protocol regression tests remain green after security hardening.

**Requirements Covered:** `SEC-01`, `SEC-02`, `SEC-03`

---

## Deferred After This Roadmap

These remain intentionally deferred until the roadmap above is complete enough to support them safely:

- Precise billing and revenue-grade usage accounting
- SSO-based token lifecycle management
- User provisioning and enterprise administration
- Business-grade audit logging, reporting, and statistics
- Cloud-friendly logging and session export
- Web GUI for user/token management and reporting
- Additional safety/protection layers beyond the stabilization baseline
- Vibe-coding-oriented or speculative feature expansion without strong customer pull

---

## Coverage Summary

- Total v1 requirements: 22
- Roadmap phases: 6
- Requirements mapped: 22
- Unmapped requirements: 0

| Phase | Requirements |
|-------|-------------|
| Phase 1 | `OPS-01`, `OPS-02` |
| Phase 2 | `TEST-01`, `TEST-02`, `TEST-03`, `TEST-04` |
| Phase 3 | `STAB-02`, `STAB-03`, `STAB-04`, `ARCH-01` |
| Phase 4 | `COMP-01`, `COMP-02`, `COMP-03`, `COMP-04`, `COMP-05`, `ARCH-02`, `ARCH-03` |
| Phase 5 | `STAB-01`, `ARCH-04` |
| Phase 6 | `SEC-01`, `SEC-02`, `SEC-03` |

---
*Roadmap defined: 2026-04-04*
*Last updated: 2026-04-04 after phase restructuring and concretization*
