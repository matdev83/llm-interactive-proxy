# Research & Design Decisions

---
**Purpose**: Capture discovery findings, architectural investigations, and rationale that inform the technical design.

**Project Context**: Universal LLM Proxy - FastAPI async, DI containers, staged initialization, adapter pattern.
---

## Summary
- **Feature**: `history-compaction-follow-up`
- **Discovery Scope**: Extension
- **Key Findings**:
  - The existing compaction service and pipeline wiring are in place; follow-up work is primarily correctness and safety hardening rather than a new subsystem.
  - Tool-result stubs are currently recognized via message `metadata`, but `ChatMessage.to_dict()` does not serialize `metadata`, so idempotency is not stable across client-submitted histories.
  - Pagination-aware file read identity currently keys only `(offset, limit)` for some tool categories; it does not cover `index`/`page`/`cursor`-style selectors and depends on tool categorization heuristics.
  - Redaction for “resource identifiers” currently uses `redact_text()` which primarily redacts secret patterns, not the identifier itself; logs/diagnostics can still leak file paths or command strings.

## Research Log

### Existing Codebase Analysis
- **Components Reviewed**:
  - `src/core/services/history_compaction_service.py` - current compaction algorithm and stub emission
  - `src/core/domain/compaction.py` - resource identity extraction + stub creation
  - `src/core/domain/configuration/compaction_config.py` - configuration surface and policy evaluation
  - `src/core/services/backend_request_preparation_service.py` - integration point before connector translation
  - `src/core/domain/chat.py` - message serialization behavior (notably metadata omission in `to_dict()`)
  - `src/core/services/non_forwardable_message_identity_service.py` - precedent for “identity stable across compaction rewrites”
  - Existing tests: `tests/unit/test_compaction_domain.py`, `tests/unit/test_history_compaction_service.py`, `tests/integration/test_history_compaction_integration.py`
- **Patterns Identified**:
  - Service-style transformations are performed in `src/core/services/` with DI registration in `src/core/di/registration_helpers/`.
  - Fail-open is preferred for non-critical transformations, but the current compaction implementation uses broad exception handling in the service.
  - Existing configuration precedence and schema surfaces exist for compaction (`config/schemas/app_config.schema.yaml`), but env/CLI only exposes a small subset.
- **Implications**:
  - The design should extend the current service/domain components rather than create a parallel pipeline.
  - Any idempotency marker must survive round-tripping through client history and connector translation; relying only on `metadata` is insufficient.

### Tool Result Identity and Pagination Parameters
- **Context**: Requirements mandate correct identity for paginated reads and stable identity across equivalent argument encodings.
- **Findings**:
  - Identity extraction already supports JSON-string and dict arguments, and numeric strings for offset/limit are normalized to integers.
  - Pagination awareness is conditional on a categorization heuristic; unknown file-read tool names may not include pagination keys even when they exist.
  - Some tool ecosystems represent pagination using `index`, `page`, `cursor`, and `chunk_size`/`length` rather than `offset`/`limit`.
- **Implications**:
  - Identity extraction needs an explicit list of selection parameters beyond offset/limit and should not rely solely on tool-name categorization to decide whether selection parameters matter.

### Stub Idempotency Across Client-Submitted History
- **Context**: Requirements require recognizing prior stubs even when message metadata is absent.
- **Findings**:
  - `ChatMessage.to_dict()` does not include `metadata`, which means a client replaying server-provided history will likely drop `_compacted` markers.
  - There is existing precedent in `NonForwardableMessageIdentityService` for making identity stable across compaction rewrites by excluding content for tool results.
- **Implications**:
  - Stub recognition must rely on content-level markers (a stable prefix and version marker) and/or structured content formats that survive serialization.

### Redaction Semantics for Resource Identifiers
- **Context**: Follow-up requirements require not emitting unredacted file paths and full command strings when redaction is enabled.
- **Findings**:
  - Current stub redaction relies on `redact_text()` which redacts secret-like substrings; it does not guarantee suppression of file paths or full command strings.
  - `CompactionResult.to_log_context()` includes `stale_resources`, which may leak identifiers unless explicitly redacted.
- **Implications**:
  - The design should treat “resource identifier redaction” as identifier masking (hash + minimal hints) rather than secret-pattern redaction.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Extend existing components | Update `HistoryCompactionService`, `ResourceIdentityExtractor`, and config semantics | Smallest change set, leverages tests | Risk of heuristic growth in extractor | Recommended baseline |
| Add tool identity registry | Add explicit per-tool identity strategies | Safer defaults for unknown tools | More surface area and migration effort | Consider if tool diversity grows |
| Hybrid | Implement core fixes now, keep registry as future refactor | Balances delivery and maintainability | Requires discipline to avoid “bag of heuristics” | Recommended plan |

## Design Decisions

### Decision: Treat this as an extension (light discovery)
- **Context**: The system already includes compaction implementation and wiring.
- **Alternatives Considered**:
  1. Full redesign of compaction pipeline
  2. Incremental hardening of existing components
- **Selected Approach**: Incrementally harden existing components with minimal new abstractions.
- **Rationale**: Preserves established DI and request flow, and aligns with existing tests and staging patterns.
- **Trade-offs**: Requires careful scoping to prevent complexity creep in the identity extractor.
- **Follow-up**: If identity extraction becomes too tool-specific, revisit the registry approach.

### Decision: Stub recognition must be content-based
- **Context**: Message metadata is not guaranteed to survive client round-tripping.
- **Alternatives Considered**:
  1. Use only message metadata markers
  2. Use a stable content prefix and version marker
  3. Use a structured (non-string) tool content payload for stubs
- **Selected Approach**: Use a stable content prefix and version marker, and preserve existing string content shape for connector compatibility.
- **Rationale**: Guarantees idempotency across client-submitted history without requiring connector changes.
- **Trade-offs**: Requires a robust parser and careful wording to prevent false positives.
- **Follow-up**: Define a canonical stub format and validation tests.

### Decision: Eligibility defaults must be conservative when enabled
- **Context**: Requirements require “no explicit permits ⇒ no compaction” and “unknown tools ⇒ preserved”.
- **Alternatives Considered**:
  1. Keep current behavior (empty allowlist allows all non-denied)
  2. Require explicit allowlist for compaction eligibility
  3. Introduce a compatibility flag for legacy behavior
- **Selected Approach**: Require explicit allowlist by default when compaction is enabled; allow an optional compatibility toggle if needed.
- **Rationale**: Safety-first behavior is critical for agentic workflows and avoids accidental removal of evidence.
- **Trade-offs**: Potential behavior change for existing deployments that only set `enabled=true`.
- **Follow-up**: Clarify migration guidance and defaults in design.md.

### Decision: Resource identifier redaction means identifier masking
- **Context**: Requirements prohibit emitting unredacted file paths/full commands in stubs/diagnostics when redaction is enabled.
- **Alternatives Considered**:
  1. Apply secret-pattern redaction only
  2. Mask the identifier (hash + minimal hint)
  3. Remove identifiers entirely from stubs
- **Selected Approach**: Mask identifiers in a stable way (hash + minimal hints) and apply consistently to both stubs and diagnostics.
- **Rationale**: Preserves traceability without leaking sensitive paths/commands.
- **Trade-offs**: Reduced debuggability; operators may need to correlate via local logs or captures.
- **Follow-up**: Define the masking scheme and ensure it is deterministic per request.

## Testing Strategy Research

### Existing Test Patterns
- Unit tests already exist for identity extraction and stub creation (`tests/unit/test_compaction_domain.py`).
- Unit tests already exist for core compaction behavior and policy allow/deny (`tests/unit/test_history_compaction_service.py`).
- Integration tests exist for request preparation integration and redaction flag behavior (`tests/integration/test_history_compaction_integration.py`).

### Coverage Requirements
- Add unit tests for `index`/`page`/`cursor` selection parameter identity and for stub recognition when `metadata` is absent.
- Add unit tests for conservative defaults when enabled with empty allowlists.
- Add tests for negative savings clamping and for redaction of identifiers in both stubs and diagnostics.

## Risks & Mitigations
- Risk: Over-aggressive identity correlation causes incorrect staleness. Mitigation: default to “no identity ⇒ no compaction” and require explicit allowlist.
- Risk: Stub detection false positives. Mitigation: versioned stub format with strict prefix and structured key lines.
- Risk: Behavior change for existing compaction-enabled deployments. Mitigation: compatibility toggle and explicit documentation in config examples.

## Performance Considerations
- Maintain O(n) traversal; avoid heavy tokenization in tight loops.
- Prefer byte-size heuristics for incremental selection of candidates; only re-estimate tokens when required by policy thresholds.

## References
- `.kiro/steering/structure.md` - staged init + DI structure
- `.kiro/steering/tech.md` - tech stack and testing posture
- `.kiro/steering/testing.md` - TDD and executable specification expectations
- Existing compaction spec (archived): `.kiro/specs/archive/context-compaction-stale-tool-results/design.md`

