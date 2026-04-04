# Scope Selection

Use this to choose the next brownfield milestone. This is intentionally scope-only: no tasks, no roadmap, no implementation plan.

Current state: maintainer priorities have now been captured. This file is no longer a blank questionnaire; it is the current scope-selection baseline.

## 1. Primary Goal

Selected priorities for the next milestone:

- [x] Reliability hardening
- [x] Compatibility/protocol correctness
- [x] Security/governance
- [ ] Observability/debugging
- [ ] MCP/tooling maturity
- [ ] New provider/backend capability
- [ ] Developer/operator UX

Business-value expansion is a priority lens, but only on top of stronger stability and security foundations.

## 2. In-Scope Areas

Current candidate scope themes:

- [x] Architectural boundary hardening between core proxy behavior and optional/non-core features
- [x] Streaming and non-streaming path simplification
- [x] Session continuity and session/user isolation hardening
- [x] Testing-strategy reset: better regression detection, shorter execution time, stronger backend/provider coverage
- [x] Validation of interactive command behavior and overall non-core feature isolation
- [x] Review of loop-detection stability and testability
- [x] Security and multi-tenancy foundations needed for future commercial use
- [x] Documentation-maintenance strategy that scales with project growth

Relevant mapped hotspots:

- `src/core/services/universal_mcp_client.py`
- `src/core/app/controllers/__init__.py`
- `src/core/domain/configuration/`
- `src/core/domain/translators/responses/streaming.py`
- `src/connectors/_openai_codex_connector.py`
- `src/core/app/controllers/responses_controller.py`
- `src/core/services/buffered_wire_capture_service.py`
- `src/core/auth/`
- `src/core/services/` and `src/connectors/`

## 3. Success Signal

How should we know the milestone worked?

- [x] Fewer correctness gaps and fewer hidden fallbacks
- [x] Better protocol compatibility for existing clients and connectors
- [x] Safer production operation and debugging
- [x] Cleaner architecture with lower change risk when optional features evolve
- [x] Better test coverage around fragile areas and stronger provider coverage
- [x] Faster, more trustworthy test feedback loops
- [x] Higher confidence that non-core changes do not break core behavior
- [x] Better security posture around session and user isolation

## 4. Constraints To Preserve

Assume these stay fixed unless explicitly changed:

- Brownfield-first, incremental evolution
- Async FastAPI + staged initialization + DI
- Existing frontend compatibility surfaces and main backend connector stability
- TDD-oriented workflow and current lint/type/test gates
- Safety and observability remain first-class
- Non-core features must not require core changes
- External OAuth connector changes must not regress proxy core

## 5. Freeform Notes

Current planning notes:

- Production stabilization matters more than feature novelty.
- The codebase feels too fragile; architectural simplification is desired, especially around bidirectional flow and streaming/non-streaming divergence.
- The test suite is large but not protecting the core as effectively as expected.
- Multi-tenancy, session isolation, and commercial-grade controls are strategically important.
- Revenue-aligned features should come before vibe-coding-oriented expansion.

## 6. Explicitly Deferred

- Vibe-coding-focused feature work
- Features without clear business or commercial value
- Optional enhancements that increase coupling before the core is more stable

## 7. Business-Aligned Follow-On Themes

After the foundation is stronger, likely revenue-aligned candidates include:

- Precise billing
- SSO-based token management
- User provisioning
- Business-grade reporting and audit logging
- Cloud-friendly logging and session export
- Stronger safety/protection layers

---
Grounding docs:
- `.planning/codebase/ARCHITECTURE.md`
- `.planning/codebase/CONCERNS.md`
- `.planning/codebase/INTEGRATIONS.md`
- `.planning/codebase/TESTING.md`
