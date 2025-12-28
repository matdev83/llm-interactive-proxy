# Research & Design Decisions

## Summary

- **Feature**: context-compaction-stale-tool-results
- **Discovery Scope**: Extension (light discovery)
- **Key Findings**:
  - Steering directory missing; proceeding with project defaults (service-based DI, staged init, adapters).
  - Compaction should sit in the request pipeline before connector translation to avoid backend-specific logic.
  - Token estimation exists; compaction can reuse existing estimation hooks to trigger reductions.

## Research Log

### Existing Codebase Analysis

- **Components Reviewed**:
  - Request processing pipeline (controllers + services) for insertion point before connector dispatch.
  - Token estimation/usage recalculation logic available for budget checks.
  - Connectors (`src/connectors/`) rely on prebuilt message history; avoid coupling compaction to them.
- **Patterns Identified**:
  - DI registration via service collection; services typically singleton for stateless transformations.
  - Adapter pattern for backends; keep compaction upstream of adapters.
  - Error handling uses `LLMProxyError` with logging `exc_info=True`.
- **Implications**: Implement compaction as a service/middleware with DI, preserving connector contracts.

### Compaction Scope Clarification

- **Context**: Only stale tool results with newer superseding outputs should be compacted.
- **Findings**:
  - Resource identity (file path, command signature) is required to correlate staleness.
  - Latest tool output for a resource must remain intact; older ones can be stubbed.
  - Stub content must be explicit to keep the LLM aware of truncation.
- **Implications**: Compaction policy needs correlation keys and explicit stub templates.

## Architecture Pattern Evaluation

List candidate patterns or approaches that were considered. Use the table format where helpful.

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Pipeline Service + Middleware | Insert compaction into request processing before connector translation | Aligns with staged init, keeps connectors unchanged | Requires clear contract to avoid reordering messages | Selected |
| Connector-level Trimming | Each backend trims messages | Backend-specific drift, duplicated logic | Breaks adapter boundary | Rejected |
| Background Preprocessor | Offline compaction prior to request | Adds latency and statefulness | Diverges from request-scoped behavior | Rejected |

## Design Decisions

Record major decisions that influence `design.md`. Focus on choices with significant trade-offs.

### Decision: Placement in Pipeline

- **Context**: Compaction must occur before backend-specific formatting.
- **Alternatives Considered**:
  1. In RequestProcessor prior to connector translation (selected)
  2. Inside connectors (rejected: duplicates, adapter boundary violation)
- **Selected Approach**: Service invoked from request processing middleware just before connector dispatch.
- **Rationale**: Maintains adapter purity and single implementation point.
- **Trade-offs**: Requires consistent message schema at call site.
- **Follow-up**: Verify call site receives full conversation with tool metadata.

### Decision: DI Lifetime

- **Context**: Stateless rules; per-request state passed in.
- **Alternatives Considered**: Singleton vs Scoped.
- **Selected Approach**: Singleton service with per-request state objects.
- **Rationale**: Pure functions; avoids per-request allocations.
- **Trade-offs**: Ensure no shared mutable state.
- **Follow-up**: Validate internal caches are request-local only.

### Decision: Failure Mode (Fail Open)

- **Context**: Compaction must not block requests.
- **Alternatives Considered**: Fail-open vs fail-closed.
- **Selected Approach**: Fail-open; log with `exc_info=True`, forward original messages.
- **Rationale**: Availability priority.
- **Trade-offs**: Oversized prompts may pass through on error.
- **Follow-up**: Metric to detect repeated failures.

### Decision: Stub Shape

- **Context**: LLM needs awareness of truncation.
- **Alternatives Considered**: Silent removal vs explicit stub.
- **Selected Approach**: Explicit stub with resource identity and “newer data exists” marker.
- **Rationale**: Preserves conversational integrity.
- **Trade-offs**: Adds small tokens; acceptable.
- **Follow-up**: Keep stub phrasing concise and consistent.

## Testing Strategy Research

### Existing Test Patterns

- Unit tests in `tests/unit/` with mocked dependencies.
- Integration tests in `tests/integration/` with DI container.
- Property tests possible for token estimation invariants.

### Test Infrastructure

- Fixtures in `tests/conftest.py`
- Mock backends in `tests/mocks/`
- Test utilities in `tests/utils/`

### Coverage Requirements

- Unit coverage for staleness detection, stub generation, fail-open.
- Integration coverage for request pipeline compaction vs connector inputs.

## Risks & Mitigations

- Risk: Misidentifying resources without stable identity — Mitigation: skip compaction when identity missing.
- Risk: Performance overhead on large histories — Mitigation: O(n) pass with lightweight correlation maps.
- Risk: Observability gaps — Mitigation: metrics + logs with redaction, compaction summary in capture metadata.

## Performance Considerations

- Single-pass correlation by resource key to keep latency low.
- Avoid deep copies; mutate copies only when compacting.

## References

- Project `AGENTS.md` - Development guidelines
- `.claude/commands/kiro/spec-design.md` - Phase rules
