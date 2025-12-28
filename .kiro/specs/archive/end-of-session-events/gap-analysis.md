# Gap Analysis: End-of-Session Events

## Executive Summary

The codebase already has a unified streaming/non-streaming response pipeline, an async EventBus, and session metrics storage, which are good foundations for EoS events. The core gaps are the absence of a centralized EoS detection/emission service, durable idempotency state in the DB, and explicit refactoring of existing completion detectors (test execution reminder, usage tracking, wire capture) to subscribe to EoS events. EventBus registration timing and dispatch timeout behavior must also be addressed to meet performance and reliability requirements.

**Effort**: L (1–2 weeks)

**Risk**: Medium (cross-cutting integrations + streaming/non-streaming parity)

## 1. Current State Investigation

### Key Files and Modules

- `src/core/services/response_pipeline.py`, `src/core/services/response_processor_service.py` — unified processing for streaming + non-streaming responses.
- `src/core/services/streaming/non_streaming_adapter.py` — wraps non-streaming responses as a single streaming chunk.
- `src/core/services/streaming/stream_normalizer.py`, `src/core/di/registrations/streaming.py` — processor chain where new EoS stream processor would be inserted.
- `src/core/ports/openai_normalizer.py`, `src/core/ports/anthropic_normalizer.py`, `src/core/ports/gemini_normalizer.py` — normalize provider-specific completion signals into metadata (`finish_reason`, `[DONE]`, `message_stop`).
- `src/core/services/event_bus.py`, `src/core/interfaces/event_bus_interface.py` — async pub/sub; currently registered in `src/core/app/stages/health_check.py`.
- `src/services/test_execution_reminder/test_execution_reminder_handler.py` + `src/services/test_execution_reminder/completion_signal_detector.py` — custom completion detection in tool-call flow.
- `src/core/services/usage_tracking_wrapper.py` — uses finish markers to decide valid completion tokens.
- `src/core/services/cbor_wire_capture_service.py`, `src/core/services/structured_wire_capture_service.py` — stream start/end markers for capture.
- `src/core/database/models/usage.py` (`SessionMetricsTable`) + `src/core/database/repositories/usage_repository.py` (`SessionMetricsRepository`) — existing persistence surface for session completion state.

### Architecture Patterns Observed

- Staged initialization via `src/core/app/stages/` with DI-driven service registration.
- Unified response pipeline treats non-streaming as single-chunk streaming, enabling shared stream processor logic.
- EventBus supports async handler dispatch but awaits handlers (`publish`) unless using `publish_nowait`.

### Testing Coverage and Seams

- Streaming/non-streaming parity is common in middleware and stream processors.
- No existing tests target EoS event lifecycle (feature is new); EventBus has unit-testable contract.

## 2. Requirements Feasibility Analysis

### Technical Needs From Requirements

- Central EoS detection and normalization (stream + tool-call + non-streaming).
- Event emission with exactly-once semantics, now requiring DB persistence for restart safety.
- Subscription mechanism with listener isolation and bounded dispatch time.
- Refactor legacy completion detection to EoS subscribers.
- Configurable enablement and schema validation.
- EoS metadata in wire capture and usage/session metrics.

### Gaps and Constraints

**Missing**:
- EndOfSessionService, EndOfSessionStreamProcessor, EndOfSessionToolCallHandler, EndOfSessionEvent model.
- DB persistence fields for EoS idempotency in `SessionMetricsTable` (or a new table) and repository methods.
- EoS subscriber implementations for ProxyMem, usage tracking, wire capture, and test reminder.
- EventBus registration earlier than HealthCheckStage (needed for EoS during processing).
- Dispatch timeout behavior to satisfy non-blocking requirement.

**Constraints**:
- Stream normalization and non-streaming adapter already control completion metadata; new logic must preserve metadata contracts.
- Tool-call reactor uses completion metadata for lifecycle resets; changes must maintain streaming/non-streaming parity.
- Config precedence and schema validation follow CLI > ENV > YAML.

**Research Needed**:
1. Confirm the canonical session identifier used across streaming and non-streaming paths to key DB idempotency.
2. Identify all remaining completion detectors that should be migrated (beyond the known test reminder + usage + capture) to satisfy Requirement 7.6.
3. Validate EventBus dispatch semantics under load and decide whether `publish_nowait` + timeout wrapper is sufficient.

## 3. Requirement-to-Asset Map (With Gaps)

Legend for Gap Tag: **Missing / Unknown / Constraint**

| Requirement Area | Existing Assets | Gap Tag | Notes |
|---|---|---|---|
| Req 1: EoS Detection | Stream normalizers + unified pipeline | Missing | No centralized EoS detection service or stream processor. |
| Req 2: EoS Emission + DB Idempotency | EventBus, SessionMetricsTable (is_completed) | Missing | No EoS event model; DB fields for EoS emission state not present. |
| Req 3: Listener Subscription | EventBus | Constraint | EventBus exists, but EoS-specific subscribers are missing. |
| Req 4: Listener Isolation | EventBus | Constraint | EventBus isolates failures; needs bounded dispatch time. |
| Req 5: Config & Controls | Config system + schemas | Missing | EndOfSessionConfig not defined; schema updates needed. |
| Req 6: Signal Normalization | Provider normalizers, stream formatting | Constraint | Signals exist in metadata; must be normalized into EoS signal. |
| Req 7: Subsystem Refactor | Test reminder handler, usage wrapper, wire capture services | Missing | Explicit EoS subscriber replacements required. |
| NFR 1: Performance | Async pipeline, streaming processors | Unknown | Dispatch timeout strategy needed; performance impact to be validated. |
| NFR 2: Reliability | SessionMetricsTable, EventBus | Missing | DB idempotency fields and logic absent. |
| NFR 3: Observability | Structlog, wire capture | Missing | EoS metadata in capture not currently sourced from EoS events. |
| NFR 4: Security | Existing logging & redaction | Constraint | Must ensure EoS payload excludes secrets. |

## 4. Implementation Approach Options

### Option A: Extend Existing Components
**Description**: Add EoS detection inside `StreamNormalizer` or `ResponseProcessor` and emit directly from those services, with minimal new types.

**Trade-offs**:
- ✅ Smaller number of new files
- ✅ Fast initial wiring
- ❌ Risks bloating existing pipeline components
- ❌ Harder to reuse for tool-call completion and subscriber refactors

### Option B: Create New Components (Event-Driven EoS Core)
**Description**: Introduce dedicated EoS service + stream processor + tool-call handler, with subscriber adapters for existing subsystems.

**Trade-offs**:
- ✅ Clear separation of concerns and testability
- ✅ Matches DI/service patterns and staged init
- ✅ Clean migration path for legacy detectors
- ❌ More integration points and wiring

### Option C: Hybrid Migration
**Description**: Implement core EoS service and stream processor first, then migrate subsystems incrementally to subscribers (test reminder, usage, wire capture), leaving legacy detectors behind temporary feature flags.

**Trade-offs**:
- ✅ Safer incremental rollout
- ✅ Easier to validate EoS event correctness before refactors
- ❌ Requires temporary dual logic and careful gating

## 5. Complexity & Risk Assessment

- **Effort: L (1–2 weeks)** — new services, DB migration, multiple subsystem integrations, and tests.
- **Risk: Medium** — cross-cutting changes across streaming, tool-call reactor, and persistence; risk is manageable with phased rollout and targeted tests.

## 6. Recommendations for Design Phase

- Preferred approach: **Option C (Hybrid Migration)** to de-risk cross-cutting refactors while validating EoS emission semantics.
- Define DB persistence strategy for EoS state (extend `SessionMetricsTable` with EoS fields + repo method).
- Specify EventBus dispatch timeout behavior and error handling semantics.
- Produce a concrete migration checklist for legacy detectors (test reminder, usage tracking finalization, wire capture metadata) and a gating plan to avoid duplicated behavior.

