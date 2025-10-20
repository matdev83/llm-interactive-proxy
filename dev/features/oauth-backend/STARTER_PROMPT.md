You’re picking up the OpenAI OAuth (Codex) connector refactor. Here’s what you need to know:

### Mission Snapshot
- We’re building a proof‑of‑concept connector that can act as a universal proxy between varied clients (Codex CLI, Droid, OpenCode, etc.) and the `openai-oauth:gpt-5-codex` backend.
- The current code is intertwined with KiloCode-specific logic; our work is guided by the PRD and phased plan just drafted.
- Goal: capability-driven translation pipeline with minimal assumptions about the client.

### Critical Docs
- `dev/features/oauth-backend/PRD.md` — definitive requirements and design principles.
- `dev/features/oauth-backend/PLAN.md` — phased refactor roadmap (start at Phase 0 / Phase 1).

### Where to Dive In
1. Re-read Phase 0 and Phase 1 in PLAN.md. The first actionable steps involve auditing the current connector and identifying Kilo-specific branches.
2. Scan these code hotspots:
   - `src/connectors/openai_oauth.py` — payload construction and prompt/tool handling.
   - `src/core/domain/translation.py` — streaming chunk translation (look for `_tool_call_text`, custom text injections).
   - `src/core/services/translation_service.py` — conversion back to OpenAI chat format.
   - Any test files referencing Kilo/Cline (e.g., `tests/unit/connectors/test_openai_oauth_codex.py`, `tests/unit/core/services/test_translation_service_responses_api.py`) to understand current expectations.

### Immediate Next Step (Phase 1 kickoff)
- Catalog existing Kilo/Cline detections and hard-coded renderers.
- Replace direct agent checks with placeholders that will later consult the capability resolver.
- Document findings in comments or notes for Phase 0 deliverables, then begin implementing the resolver scaffolding.

Keep the scope limited to proof-of-concept: correctness and clean architecture come first; advanced features (metrics, rate limiting) can wait. When in doubt, cross-reference the PRD. Good luck!
