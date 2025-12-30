# Gap Analysis: History Compaction Follow-Up

## Executive Summary

The codebase already contains a working history compaction pipeline (config model, DI registration, request-preparation integration, and unit/integration tests). The primary gaps versus the follow-up requirements are correctness and safety issues around resource identity for paginated file reads, conservative eligibility defaults for unknown tools, and “operational hygiene” concerns (redaction semantics, stable stub detection across client-submitted histories, and metrics correctness at edge cases).

**Primary evidence (existing assets)**:
- Compaction algorithm and identity extraction: `src/core/services/history_compaction_service.py`, `src/core/domain/compaction.py`
- Config model + schema surface: `src/core/domain/configuration/compaction_config.py`, `config/schemas/app_config.schema.yaml`
- Request pipeline integration: `src/core/services/backend_request_preparation_service.py`
- Test coverage: `tests/unit/test_history_compaction_service.py`, `tests/unit/test_compaction_domain.py`, `tests/integration/test_history_compaction_integration.py`

**Effort**: M (3–7 days)  
**Risk**: Medium (behavior changes affect prompt contents and may impact connectors/agents; most changes are localized and testable)

## 1. Current State Investigation

### Key assets already in place

- **Single-pass staleness compaction service**:
  - Builds a tool-call index, extracts a `ResourceIdentity` for each tool result, and replaces all but the last occurrence with a stub.
  - `src/core/services/history_compaction_service.py`
- **Resource identity model + extractor**:
  - Identity keyed by tool name + primary key + optional secondary keys (offset/limit for some file-read categories).
  - `src/core/domain/compaction.py`
- **Config + runtime policy evaluation**:
  - `CompactionConfig` includes thresholds, allow/deny categories, and unused knobs (`max_stubs_per_resource`, `preserve_last_n_results`, `stub_template`).
  - `src/core/domain/configuration/compaction_config.py`
  - Schema supports these fields: `config/schemas/app_config.schema.yaml`
- **Pipeline placement before backend translation**:
  - Compaction invoked during backend request preparation based on an approximate token estimate.
  - `src/core/services/backend_request_preparation_service.py`
- **Observability primitives**:
  - `CompactionResult` provides metrics and structured log context (including `stale_resources`).
  - `src/core/interfaces/history_compaction_interface.py`

### Conventions and constraints relevant to the work

- **DI + staged initialization** is the expected integration mechanism (`src/core/di/`, staged app startup).
- **TDD expectation**: changes should be introduced by tests that pin externally observable behavior (`.kiro/steering/testing.md`).
- **Domain model behavior**: `ChatMessage.to_dict()` does not include `metadata` (`src/core/domain/chat.py`), so compaction markers stored only in `metadata` are not preserved if a client later re-submits history.

## 2. Requirement-to-Asset Map (with Gaps)

Legend: **Present** / **Missing** / **Constraint** (present but insufficient) / **Unknown** (requires research/clarification)

| Requirement Area | Existing Assets | Status | Gap Notes |
|---|---|---:|---|
| R1: Resource identity correctness | `src/core/domain/compaction.py` | Constraint | Pagination identity includes offset/limit for some categories, but does not cover `index`/`page`-style selectors; also depends on tool categorization to decide whether pagination params matter. |
| R2: Staleness invariants | `src/core/services/history_compaction_service.py` | Constraint | Preserves latest per identity, but “already stubbed” detection relies on `metadata['_compacted']`, which is not stable across client-submitted histories (`src/core/domain/chat.py`). |
| R3: Stub transparency | `src/core/domain/compaction.py` | Constraint | Stub text includes only `primary_key` (e.g., file path) and not the full resource identity (missing selection parameters), reducing agentic interpretability for partial reads. |
| R4: Token budget governance + threshold semantics | `src/core/services/backend_request_preparation_service.py`, `src/core/domain/configuration/compaction_config.py` | Constraint | Call site uses `>= token_threshold` but service-side `needs_compaction` is `>`; iterative compaction “subject to preservation limits” is not implemented (service compacts all stale in one pass). |
| R5: Conservative eligibility defaults | `src/core/domain/configuration/compaction_config.py`, `src/core/domain/compaction.py` | Missing | If allowlist is empty, all non-denied categories are eligible; unknown tool names categorize as `OTHER`, so “unknown tools must not compact by default” is not met. Tool-name allow/deny exists only as runtime parameters, not as config fields. |
| R6: Observability + redaction + accounting correctness | `src/core/interfaces/history_compaction_interface.py`, `src/core/domain/compaction.py`, `tests/integration/test_history_compaction_integration.py` | Constraint | Redaction currently uses `redact_text()` against the identifier string, which primarily redacts secrets and does not necessarily redact the identifier itself; `stale_resources` may leak identifiers; `bytes_saved` can go negative (stub longer than original). |
| R7: Extensibility to other tools | `src/core/domain/compaction.py` | Constraint | Extractor supports command/query/directory identities, but query identity parameter list includes `SearchPath` as a possible “query” key which can mis-identify resources; unknown tool types are not treated as “ineligible by default.” |
| NFRs (perf/reliability/observability/security) | Current service is O(n), fail-open exists | Constraint | Additional identity parsing and diagnostics must remain lightweight; redaction requirements need clarification (see Research Needed). |

## 3. Implementation Approach Options

### Option A: Extend existing components in place (targeted fixes)

**Description**: Keep the current architecture (service + extractor + config) and implement follow-up requirements by tightening identity extraction, stub generation, eligibility defaults, and diagnostics.

**Likely touch points**:
- `src/core/domain/compaction.py` (identity extraction for `index`/`page` and other selection params; query identity correctness; stub content composition)
- `src/core/services/history_compaction_service.py` (idempotency detection without relying solely on metadata; clamp negative savings)
- `src/core/domain/configuration/compaction_config.py` (conservative default semantics when enabled)
- `src/core/services/backend_request_preparation_service.py` (threshold boundary alignment and/or compaction trigger logic)
- Tests: `tests/unit/test_compaction_domain.py`, `tests/unit/test_history_compaction_service.py`, `tests/integration/test_history_compaction_integration.py`

**Pros**:
- Minimal new abstraction surface; preserves existing DI and request flow.
- Most changes are localized and can be pinned with existing tests.

**Cons**:
- Risk of growing `ResourceIdentityExtractor` into a “bag of heuristics”.
- Conservative-default semantics may be a behavior change for existing deployments that enabled compaction without configuring allowlists.

### Option B: Introduce a dedicated “tool identity” registry (new component)

**Description**: Create a new domain component that maps tool names (and optionally tool categories) to explicit identity-extraction strategies, with a safe fallback of “no identity / ineligible”.

**Integration points**:
- `HistoryCompactionService` depends on the registry instead of heuristic categorization.
- Config determines which registry entries are enabled/eligible.

**Pros**:
- Makes correctness explicit per tool; reduces accidental staleness for unknown tools.
- Easier to extend to new tools while keeping safety defaults.

**Cons**:
- More files and interface design overhead.
- Requires deciding which tool names are “officially supported” vs “unknown”.

### Option C: Hybrid (minimal fixes now, registry later)

**Description**: Implement immediate correctness/safety fixes in place (Option A subset), and optionally add a registry later only if the extractor becomes too complex.

**Pros**:
- Delivers high-value bug fixes quickly with limited refactor risk.
- Keeps an escape hatch if tool diversity grows.

**Cons**:
- Requires discipline to avoid overloading the extractor with too many special cases.

## 4. Implementation Complexity & Risk

- **Effort: M (3–7 days)** — Changes are concentrated in the compaction domain/service and a small portion of request preparation; additional tests are required for paginated read identity and conservative defaults.
- **Risk: Medium** — Changes alter what is sent to LLM backends; correctness regressions can change agent behavior. However, the affected surface is small and has existing test coverage.

## 5. Recommendations for the Design Phase (Information, not final decisions)

### Likely preferred direction

- **Option C (Hybrid)** is a pragmatic starting point: implement the immediate correctness gaps (paginated read identity, stub transparency, safe defaults, diagnostics fixes) without introducing a new registry prematurely.

### Research Needed (carry into design)

1. **Redaction semantics**: does “redact resource identifiers” mean “remove secrets from identifiers” (current `redact_text` behavior) or “mask the identifier itself” (hide file paths/commands)? This impacts both stub contents and logs/metrics.
2. **Tool ecosystem inventory**: enumerate the actual tool call shapes seen in production (especially file readers with `index`/`page`/`chunk` parameters) to ensure identity extraction covers real-world tools.
3. **Idempotency across client history**: decide how to recognize prior compaction when the client re-submits messages (content marker vs structured metadata vs tool-result identity mapping).
4. **Eligibility defaults migration**: if the system changes to “deny unknown categories by default when enabled”, determine if a compatibility mode or explicit migration note is required.
5. **Token estimation strategy**: confirm whether the heuristic estimate is sufficient for governance semantics, or whether a consistent token counting utility (e.g., `src/core/utils/token_count.py`) should be used at the compaction decision point.

