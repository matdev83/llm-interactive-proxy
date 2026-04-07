# Research & Design Decisions

---
**Purpose**: Capture discovery findings, architectural investigations, and rationale that inform the technical design for `compression-layer-rtk-inspired`.

**Project Context**: Universal LLM Proxy - FastAPI async, DI containers, staged initialization, adapter pattern.
---

## Summary
- **Feature**: `compression-layer-rtk-inspired`
- **Discovery Scope**: Complex Integration (brownfield extension)
- **Key Findings**:
  - The repo already reduces token usage via three separate mechanisms: history compaction (stale-output stubbing), pytest output filtering, and Gemini connector tool-output truncation. A unified strategy-based subsystem is required to meet broad coverage and configuration integrity requirements without creating new god-services.
  - The backend pipeline already contains two natural integration points for request-bound compression: `BackendRequestPreparationService` (message shaping, history compaction) and `BackendPreparer` (token limit enforcement with accurate token measurement). These points enable deterministic escalation before size-based failure.
  - Current compaction configuration has documented but inactive knobs (`stub_template`, `max_stubs_per_resource`, `preserve_last_n_results`). Dynamic compression design must include a compatibility + integrity plan so legacy controls remain deterministic and operator-trustworthy during migration.

## Research Log
Document notable investigation steps and their outcomes. Group entries by topic for readability.

### Existing Codebase Analysis
- **Components Reviewed**:
  - `src/core/services/backend_request_preparation_service.py` - request message shaping + history compaction hook point
  - `src/core/services/history_compaction_service.py` / `src/core/domain/compaction.py` - tool identity extraction (`ToolCategory`, `categorize_tool`) + stub replacement behavior
  - `src/core/services/backend_preparer.py` - token/context-window enforcement (accurate token measurement + structured 413 errors)
  - `src/core/services/response_manager_service.py` - existing pytest output compression path
  - `src/connectors/gemini_base/chat_request_preparer.py` - connector-specific tool output truncation (and current “skip when compaction enabled” guard)
  - DI wiring points: `src/core/di/registration_helpers/request_processing/_rp_backend_components.py`
  - Documentation: `docs/user_guide/features/context-compaction.md`, `docs/user_guide/features/pytest-compression.md`, `docs/user_guide/configuration.md`
- **Patterns Identified**:
  - Staged init + DI factories are the canonical way to introduce cross-cutting runtime services.
  - Fail-open is an established safety posture (compaction returns original messages on error; Gemini truncation is optional and bypassable).
  - Token estimation is intentionally “cheap” in the request prep stage (char-count heuristic), while “accurate” measurement is used only in strict validation (`count_tokens()` in `BackendPreparer`).
  - `ChatMessage.metadata` is used for internal bookkeeping (e.g., `_compacted`) without affecting provider payloads, enabling audit metadata without changing protocol shapes.
- **Implications**:
  - Dynamic compression should be a dedicated subsystem (interfaces + services + strategies) wired into existing request preparation and token enforcement points.
  - Strategy implementations must be stateless and deterministic to avoid cross-request coupling and to keep contract tests stable.
  - Observability should follow existing structured-logging patterns (metrics in `extra`) and wire-capture transparency (captured payload must reflect what the backend received).

### RTK Reference: Strategy Taxonomy and Filter Levels
- **Context**: Requirements cite `rtk-ai/rtk` as a reference implementation (RTK - Rust Token Killer).
- **Sources Consulted**:
  - [RTK Filtering Strategies](https://mintlify.com/rtk-ai/rtk/concepts/filtering-strategies)
  - [RTK Token Savings](https://mintlify.com/rtk-ai/rtk/concepts/token-savings)
  - [RTK README](https://raw.githubusercontent.com/rtk-ai/rtk/master/README.md)
  - RTK architecture reference (`docs/contributing/ARCHITECTURE.md`) fetched from RTK repo
- **Findings**:
  - RTK’s core reduction primitives are: filtering, grouping, truncation, and deduplication.
  - RTK uses “detail levels” for code reading (none/minimal/aggressive) where “aggressive” keeps signatures only.
  - RTK defaults to fail-safe behavior: if filtering fails, it emits original output.
  - RTK often makes outputs more “LLM-friendly” rather than preserving strict machine-parseable formats (e.g., structure-only JSON representations).
- **Implications**:
  - Proxy compression should implement RTK-inspired primitives as composable strategies, with explicit levels and deterministic priority.
  - File-content detail levels (full / structure-only / signatures-only) can be modeled similarly to RTK filter levels while preserving explicit omission markers.
  - Optional “raw recovery” concepts (RTK tee) inform proxy-side retention/correlation design, but must respect the proxy’s API-layer scope and privacy constraints.

### Token Limit Enforcement and Escalation Hook Point
- **Context**: Requirement 2.5 demands increased compression aggressiveness under token pressure “before failing the request for size alone.”
- **Sources Consulted**:
  - `src/core/services/backend_preparer.py` (context-window enforcement + 413 errors)
  - `src/core/services/backend_request_preparation_service.py` (pre-translation request shaping)
  - `src/core/utils/token_count.py` (prompt extraction + token counting)
- **Findings**:
  - The system already has a strict validation boundary that can fail requests based on measured token counts, producing structured `InvalidRequestError` responses.
  - There is already a budget concept in compaction (`CompactionConfig.token_threshold`, `CompactionConfig.max_tokens`) used for triggering and “overflow risk” warnings.
- **Implications**:
  - Dynamic compression should execute in the request-prep stage using cheap heuristics, then optionally escalate in the strict enforcement stage when measured limits are exceeded.
  - Escalation must be bounded (time + number of passes) and deterministic to preserve reliability and performance.

### Connector-Level Tool Output Truncation (Gemini) and Double-Reduction Risk
- **Context**: The Gemini connector can truncate tool outputs via `extra` settings; it currently skips truncation when history compaction is enabled.
- **Sources Consulted**:
  - `src/connectors/gemini_base/chat_request_preparer.py`
  - `docs/user_guide/configuration.md` (Gemini `extra.tool_output_truncate_*`)
- **Findings**:
  - Connector truncation is provider-specific and can silently reduce tool content without a unified marker/metadata model.
  - The existing “skip when compaction enabled” guard prevents one class of double reduction but does not address future dynamic compression.
- **Implications**:
  - The design must define precedence rules so connector truncation does not stack with the new compression subsystem unless explicitly configured as a final safety fallback.
  - Migration should move provider-local truncation into the unified strategy registry where possible.

### Marker Semantics and Format Safety
- **Context**: Requirements call for explicit markers indicating compression and method(s) applied.
- **Sources Consulted**:
  - Requirements document (Req 3.4, Req 7.2)
  - Existing compaction stubs (`[COMPACTED]` markers) and docs
- **Findings**:
  - Markers improve transparency but can interfere with “shape” expectations (e.g., JSON-like outputs).
  - Existing compaction stubs are explicit and consistent, which supports debuggability and wire-capture auditability.
- **Implications**:
  - Marker insertion must be configurable and content-type-aware, with deterministic formatting and a “marker disabled” compatibility mode.

## Architecture Pattern Evaluation
List candidate patterns or approaches that were considered.

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Extend existing services | Add dynamic compression directly inside compaction / response manager | Lowest file count; reuses wiring | High risk of god-services and regression in sensitive pipeline | Avoid for long-term maintainability |
| New compression subsystem | Strategy registry + orchestrator + typed config | Clear boundaries; scalable coverage; testable strategies | More initial wiring work | Good architecture baseline |
| Hybrid incremental migration | New subsystem, but wrap legacy behaviors first | Preserves compatibility contracts; phased rollout with flags | Requires careful precedence + double-reduction guards | **Recommended** |

## Design Decisions
Record major decisions that influence `design.md`. Focus on choices with significant trade-offs.

### Decision: Strategy-based dynamic compression subsystem (hybrid migration)
- **Context**: Requirements demand broad tool coverage, per-method flags, deterministic ordering, and fail-open behavior.
- **Alternatives Considered**:
  1. Expand existing compaction/pytest code paths directly
  2. Introduce a new subsystem and migrate incrementally
- **Selected Approach**: Implement a new strategy registry + orchestrator, and initially adapt/wrap existing pytest compression and connector truncation behaviors as strategies where appropriate.
- **Rationale**: Preserves compatibility contracts while enabling safe progressive rollout and isolated testing.
- **Trade-offs**: Requires new interfaces/config models and additional DI wiring.
- **Follow-up**: Verify legacy behavior equivalence via regression tests before enabling by default.

### Decision: Two-stage budget handling (heuristic pre-pass + measured escalation)
- **Context**: Token pressure handling must avoid size-based request failure when compression can safely reduce output further.
- **Alternatives Considered**:
  1. Only heuristic compression in request-prep stage
  2. Only measured-token compression in strict validation stage
  3. Combined approach (pre-pass + escalation)
- **Selected Approach**: Apply deterministic heuristic compression in request preparation; if strict enforcement fails, optionally re-run compression at a higher aggressiveness level within bounded limits.
- **Rationale**: Aligns with existing fast-path + strict-path design and minimizes unnecessary tokenization overhead.
- **Trade-offs**: Adds an escalation loop that must be capped for performance and determinism.
- **Follow-up**: Define maximum escalation steps and per-output time budgets.

### Decision: Precedence model across legacy and new controls
- **Context**: Legacy compaction, legacy pytest compression, and connector truncation must remain functional and avoid double reduction.
- **Alternatives Considered**:
  1. Hard-disable legacy behaviors when dynamic compression is enabled
  2. Keep all behaviors and rely on operator configuration
  3. Deterministic precedence + explicit compatibility flags
- **Selected Approach**: Keep legacy behaviors functional; define deterministic precedence and explicit “already reduced” markers/metadata to prevent double application.
- **Rationale**: Protects existing workflows and supports phased rollout.
- **Trade-offs**: More configuration surface and migration documentation needed.
- **Follow-up**: Add diagnostics reporting “effective compression settings” and decisions per request.

### Decision: DI Lifetime Selection
- **Context**: Strategies and orchestration are deterministic/stateless; configuration is read per request.
- **Selected Approach**: Register orchestrator/registry/strategies as `Singleton` services. Avoid content-dependent caches that introduce cross-request coupling; allow only compiled-regex and static lookup caches.

### Decision: Error Handling Strategy
- **Context**: Compression errors must not break request processing.
- **Selected Approach**: Catch strategy errors per method and fail open by returning the last successful output (or original). Record errors in structured logs/metrics without raising transport-layer exceptions.

## Testing Strategy Research

### Existing Test Patterns
- History compaction is covered by unit + integration tests (e.g., `tests/unit/test_history_compaction_service.py`, `tests/integration/test_history_compaction_integration.py`).
- Pytest compression has unit + integration coverage (e.g., `tests/unit/core/services/test_pytest_compression_service.py`, `tests/integration/test_pytest_compression_e2e.py`).

### Coverage Requirements (for implementation phase)
- Unit tests per strategy (ANSI stripping, dedupe, grouping, truncation, JSON/NDJSON, file detail levels).
- Integration tests covering:
  - request-prep compression placement (pre-translation)
  - measured-token escalation behavior (no regressions in `BackendPreparer`)
  - double-reduction prevention with Gemini truncation and legacy pytest compression.

## Risks & Mitigations
- Risk: Compression breaks agent workflows by removing critical context - Mitigation: fail-open per method; conservative defaults; failure-focused heuristics for tests/lint/build.
- Risk: Double reduction (legacy + new) causes over-truncation - Mitigation: explicit precedence rules and “already reduced” markers.
- Risk: Performance regression from expensive parsing/tokenization - Mitigation: heuristics by default; strict time budgets per output; token counting only in enforcement path.
- Risk: Sensitive data leakage in logs or retained artifacts - Mitigation: redaction controls, retention toggles, and redaction-safe diagnostics outputs.

## Performance Considerations
- Avoid blocking I/O in strategies. Keep operations pure string/structure transforms.
- Enforce per-output time budgets (default target: 100ms) and maximum input size thresholds to bound work.
- Prefer O(n) algorithms (line scans, stable grouping) with deterministic ordering.

## References
- Project code and docs:
  - `src/core/services/backend_request_preparation_service.py`
  - `src/core/services/backend_preparer.py`
  - `src/core/services/history_compaction_service.py`
  - `src/core/services/response_manager_service.py`
  - `src/connectors/gemini_base/chat_request_preparer.py`
  - `docs/user_guide/features/context-compaction.md`
  - `docs/user_guide/features/pytest-compression.md`
  - `docs/user_guide/configuration.md`
- RTK reference:
  - `https://mintlify.com/rtk-ai/rtk/concepts/filtering-strategies`
  - `https://mintlify.com/rtk-ai/rtk/concepts/token-savings`
  - `https://raw.githubusercontent.com/rtk-ai/rtk/master/README.md`
