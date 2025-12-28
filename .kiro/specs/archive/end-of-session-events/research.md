# Research & Design Decisions

---
**Purpose**: Capture discovery findings, architectural investigations, and rationale that inform the technical design.

**Usage**:
- Log research activities and outcomes during the discovery phase.
- Document design decision trade-offs that are too detailed for `design.md`.
- Provide references and evidence for future audits or reuse.

**Project Context**: Universal LLM Proxy - FastAPI async, DI containers, staged initialization, adapter pattern.
---

## Summary
- **Feature**: end-of-session-events
- **Discovery Scope**: Complex Integration
- **Key Findings**:
  - Completion signals are detected across streaming normalizers and formatting, but there is no unified End-of-Session event or session-level dedupe.
  - The async EventBus is implemented and used for health checks, yet it is registered late and not available for core lifecycle events.
  - ProxyMem, usage tracking, wire capture, and test execution reminder require refactoring to consume a centralized EoS event instead of bespoke completion detection.

## Research Log
Document notable investigation steps and their outcomes. Group entries by topic for readability.

### Existing Codebase Analysis
- **Components Reviewed**:
  - `src/core/services/event_bus.py`, `src/core/interfaces/event_bus_interface.py`
  - `src/core/domain/events/health_events.py`, `src/core/domain/events/__init__.py`
  - `src/core/services/stream_formatting_service.py`, `src/core/domain/streaming/sentinels.py`
  - `src/core/services/response_processor_service.py`, `src/core/services/response_pipeline.py`, `src/core/services/streaming/stream_normalizer.py`
  - `src/services/test_execution_reminder/completion_signal_detector.py`, `src/services/test_execution_reminder/test_execution_reminder_handler.py`
  - `src/core/memory/completion_detector.py`, `src/core/memory/service.py`
  - `src/core/services/usage_tracking_wrapper.py`, `src/core/services/usage_tracking_service.py`
  - `src/core/services/cbor_wire_capture_service.py`, `src/core/domain/cbor_capture.py`
- **Patterns Identified**:
  - Streaming and non-streaming responses flow through a unified stream processor pipeline via `UnifiedResponsePipeline`.
  - Event bus usage patterns are established in health check services with subscribe/unsubscribe lifecycle.
  - Completion signals appear as `[DONE]`, `finish_reason`, `message_stop`, and `response.completed` in different normalizers and translators.
- **Implications**:
  - An EoS stream processor can observe completion for both streaming and non-streaming responses.
  - A centralized EoS publisher can reuse the EventBus to dispatch to subsystem subscribers.
  - Subsystems need dedicated EoS subscribers to replace their local completion detection.

### External Research (WebSearch/WebFetch)
- **Context**: Required by discovery rules for external best practices.
- **Sources Consulted**: None (WebSearch/WebFetch tools unavailable in this environment).
- **Findings**: External best-practice validation deferred.
- **Implications**: Design decisions rely on internal patterns; confirm external guidance during implementation if needed.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Extend Existing Components | Emit EoS from stream formatting/normalizers and wire subscribers inline | Minimal new files, fast iteration | Coupled to formatting path; harder to dedupe cross-sources | Viable but brittle for tool-call completions |
| New EoS Service | Dedicated EoS service + signal normalization + event bus publisher | Clear responsibility, centralized dedupe | More wiring and DI registrations | Preferred for long-term clarity |
| Hybrid | Stream processor + tool-call observer feed a central EoS publisher | Balanced approach, covers all sources | Requires careful ordering in pipeline | Selected approach |

## Design Decisions

### Decision: Centralized EndOfSessionService
- **Context**: Completion signals originate from multiple sources and must dedupe to a single EoS event.
- **Alternatives Considered**:
  1. Inline emission from stream formatting service
  2. Dedicated service that normalizes and emits
- **Selected Approach**: Introduce `EndOfSessionService` to normalize signals and publish an `EndOfSessionEvent` once per session.
- **Rationale**: Centralizes dedupe, supports multiple signal sources, aligns with EventBus patterns.
- **Trade-offs**: Additional DI wiring; new state tracking for emitted sessions.
- **Follow-up**: Define TTL cleanup for emitted session tracking.

### Decision: Stream Processor Integration Point
- **Context**: Completion detection should apply to both streaming and non-streaming responses.
- **Alternatives Considered**:
  1. Hook in response adapters only
  2. Add an `IStreamProcessor` in the unified pipeline
- **Selected Approach**: Add `EndOfSessionStreamProcessor` to the StreamNormalizer chain.
- **Rationale**: Unified pipeline already wraps non-streaming responses; processor sees canonical `StreamingContent`.
- **Trade-offs**: Requires correct processor ordering to preserve metadata.
- **Follow-up**: Confirm processor order with existing ContentAccumulation and middleware processors.

### Decision: EventBus Registration Stage
- **Context**: EoS events are core lifecycle events and must be available before health stage.
- **Alternatives Considered**:
  1. Keep registration in HealthCheckStage
  2. Register in CoreServicesStage
- **Selected Approach**: Register EventBus in CoreServicesStage.
- **Rationale**: Ensures availability for core services and early subscribers.
- **Trade-offs**: Requires moving registration code or ensuring idempotent registration.
- **Follow-up**: Validate no duplicate registrations occur across stages.

### Decision: Subsystem Refactoring
- **Context**: Existing completion detection is duplicated across subsystems.
- **Alternatives Considered**:
  1. Keep local detection and add EoS as secondary signal
  2. Replace local detection with EoS subscribers
- **Selected Approach**: Replace local detection where possible with EoS subscribers as mandated by Requirement 7.
- **Rationale**: Ensures a single source of truth for session completion.
- **Trade-offs**: Requires refactoring of TestExecutionReminder and ProxyMem completion triggers.
- **Follow-up**: Identify any subsystem that must retain local detection for backward compatibility.

## Testing Strategy Research

### Existing Test Patterns
- Unit tests in `tests/unit/` with mocked dependencies
- Integration tests in `tests/integration/` with DI container
- Property tests in `tests/property/` using Hypothesis
- Behavior tests in `tests/behavior/` for scenarios

### Test Infrastructure
- Fixtures in `tests/conftest.py`
- Mock backends in `tests/mocks/`
- Test utilities in `tests/utils/`

### Coverage Requirements
- Target: EoS detection and emission paths, subscriber side-effects, and config gating
- Critical paths: streaming done markers, finish_reason normalization, tool-call completion
- Edge cases: duplicate signals, missing session_id, disabled emission

## Risks & Mitigations
- Risk 1: Duplicate EoS emissions across sources - Mitigation: centralized dedupe with per-session state and TTL cleanup.
- Risk 2: Missing or inconsistent session identifiers - Mitigation: use pipeline metadata and enforce session_id in NonStreamingAdapter.
- Risk 3: EventBus not available early in lifecycle - Mitigation: register EventBus in CoreServicesStage.

## Performance Considerations
- Async I/O impact: EoS processing must be non-blocking and keep per-signal work O(1).
- Memory footprint: Track only active session IDs with TTL cleanup to prevent leaks.
- Wire capture overhead: Add minimal metadata entries only on EoS emission.

## References
- `src/core/services/event_bus.py` - Event bus implementation
- `src/core/services/response_processor_service.py` - Unified streaming/non-streaming pipeline
- `src/core/services/streaming/stream_normalizer.py` - Stream processor chain
- `src/services/test_execution_reminder/completion_signal_detector.py` - Completion tool detection
- `src/core/memory/completion_detector.py` - ProxyMem completion logic
- `.kiro/settings/rules/design-principles.md` - Design rules and constraints
