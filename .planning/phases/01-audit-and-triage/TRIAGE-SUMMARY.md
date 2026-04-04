# Triage Summary

**Phase:** 01-audit-and-triage
**Date:** 2026-04-04
**Auditor:** Antigravity

## Executive Summary

The LLM Interactive Proxy codebase is in **good operational health**. The interactive command system is comprehensively implemented with 56 of 63 command registrations classified as stable. The primary risks are concentrated in two areas: (1) MagicMock fallbacks in production DI code that could silently degrade service quality, and (2) dependency management issues including test deps in production and unpinned high-risk SDKs.

No critical bugs or broken commands were found. The system's dual-registration architecture (decorator + domain registry) adds complexity but is not a reliability risk.

---

## Issue Classification Matrix

### Fix-in-Place (Can be resolved without new architecture)

| # | Issue | Source | Severity | Effort | Description |
|---|-------|--------|----------|--------|-------------|
| F1 | MagicMock in AnthropicController fallback | RISK-AUDIT #3 | HIGH | S | Remove mock fallback at `controllers/__init__.py:175`. Replace with `HTTPException(503)`. |
| F2 | MagicMock in QualityVerifierServiceFactory | RISK-AUDIT #3 | HIGH | S | Remove mock fallback at `_rp_orchestration_core.py:393`. Use null-object or raise. |
| F3 | MagicMock in ToolCallReactorMiddleware | RISK-AUDIT #3 | MEDIUM | S | Remove mock fallback at `_streaming_pipeline.py:416`. Already `enabled=False` -- simplify to skip construction. |
| F4 | MagicMock in application_factory | RISK-AUDIT #3 | LOW | S | Remove `isinstance(config, MagicMock)` check at `application_factory.py:52`. |
| F5 | Test deps in production dependencies | RISK-AUDIT #5 | MEDIUM | S | Move `pytest-asyncio` and `pytest-xdist` from `[project.dependencies]` to `[project.optional-dependencies.dev]`. |
| F6 | test_stages.py in src/ tree | RISK-AUDIT #3 | LOW | S | Move `src/core/app/stages/test_stages.py` to `tests/`. |

### Defer (Acknowledged but not urgent)

| # | Issue | Source | Severity | Rationale |
|---|-------|--------|----------|-----------|
| D1 | MCP client placeholder | RISK-AUDIT #2 | MEDIUM | Not wired into any production path. Add `# PLACEHOLDER` banner. |
| D2 | Dead config examples | RISK-AUDIT #4 | LOW | Example files are harmless. Consider `config/README.md` later. |
| D3 | json_sanitizer AsyncMock import | RISK-AUDIT #3 | LOW | Uses type for isinstance check, not creating mock instances. |
| D4 | Uncertain commands (`/provider`, `/mode`, `gemini-generation-config`) | COMMANDS-AUDIT | LOW | Commands have real implementations, just missing dedicated tests. |

### Needs-Phase (Requires dedicated stabilization work)

| # | Issue | Source | Target Phase | Description |
|---|-------|--------|-------------|-------------|
| N1 | Loop breaking not wired | RISK-AUDIT #1 | Phase 02/03 | `LoopBreakingService` (271 lines) is dead code. Wire into streaming pipeline or remove. |
| N2 | Dependency pinning strategy | RISK-AUDIT #5 | Phase 02 | Pin high-risk deps (`fastapi`, `httpx`, `anthropic`, `google-genai`, `llm-accounting`). Consider lock file. |
| N3 | Dual-registry command tech debt | COMMANDS-AUDIT | Future | Commands are registered in both decorator registry and domain registry. Consolidate to single path. |

---

## Roadmap Phase Mapping

| Phase | Issues | Focus |
|-------|--------|-------|
| **Phase 02 (Stabilize DI)** | F1, F2, F3, F4, F5, F6, N2 | Remove all MagicMock fallbacks from production. Fix deps. |
| **Phase 03 (Loop Detection)** | N1 | Wire or remove LoopBreakingService. |
| **Phase 04+ (Clean Architecture)** | N3 | Consolidate dual command registry. |
| **Deferred** | D1-D4 | No action required in near term. |

---

## Metrics

| Category | Count |
|----------|-------|
| Total unique interactive commands | ~35 |
| Command registrations (raw) | 63 |
| Stable commands | 56 |
| Uncertain commands | 3 |
| Broken commands | 0 |
| Risk areas audited | 5 |
| Fix-in-place issues | 6 |
| Deferred issues | 4 |
| Needs-phase issues | 3 |
| Production files with MagicMock | 6 |
| Unpinned high-risk dependencies | 5 |
| Dead code files | 2 (LoopBreakingService, UniversalMCPClient) |

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|-----------|-------|
| Command enumeration | HIGH | All handler files inspected, both registries traced |
| MagicMock audit | HIGH | Full source grep across `src/` tree |
| Loop detection | HIGH | DI registration chain traced end-to-end |
| MCP status | HIGH | All 5 placeholder methods confirmed |
| Config audit | MEDIUM | File listing complete, runtime loading not traced |
| Dependency audit | HIGH | Full pyproject.toml reviewed |

---

## Source Documents

- [INTERACTIVE-COMMANDS-AUDIT.md](INTERACTIVE-COMMANDS-AUDIT.md) -- Complete command registry
- [RISK-AUDIT.md](RISK-AUDIT.md) -- Detailed risk findings with code evidence
