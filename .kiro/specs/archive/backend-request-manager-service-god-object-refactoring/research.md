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
- **Feature**: `backend-request-manager-service-god-object-refactoring`
- **Discovery Scope**: Extension
- **Key Findings**:
  - `BackendRequestManager` concentrates request prep, non-streaming, streaming, retries, and safety in a single 1832 LOC module.
  - Existing patterns for decomposition and DI already exist in request processing (`request_processor_internal` interfaces and CoreServicesStage wiring).
  - Streaming and retry behavior depends on stable metadata keys (tool-call swallow, steering replacement, retry counts) consumed by downstream services.

## Research Log
Document notable investigation steps and their outcomes. Group entries by topic for readability.

### Existing Codebase Analysis
- **Components Reviewed**:
  - `src/core/services/backend_request_manager_service.py` - monolithic request manager implementation
  - `src/core/interfaces/backend_request_manager_interface.py` - public contract
  - `src/core/di/registration_helpers/core_processing.py` - DI registration and optional collaborators
  - `src/core/services/backend_preparer.py`, `src/core/services/backend_executor.py` - adjacent request processor phases
  - `src/core/services/streaming/content_accumulation_processor.py`, `src/core/services/steering_leak_protection.py` - metadata consumers
- **Patterns Identified**:
  - Orchestrator + phase components pattern in request processing
  - DI registration via factory functions in `core_processing`
  - Optional collaborators and fail-open behavior
  - Runtime DI lookup used for structured output middleware and loop detection
- **Implications**: Refactor should follow the orchestrator pattern, keep DI wiring in CoreServicesStage, and replace runtime service lookups with injected collaborators where feasible.

### Metadata Contract Dependencies
- **Context**: Tool-call retry and streaming accumulation rely on metadata keys.
- **Sources Consulted**: `src/core/services/backend_request_manager_service.py`, `src/core/services/streaming/content_accumulation_processor.py`, `src/core/services/steering_leak_protection.py`, `src/core/services/streaming/vtc_response_wrapper.py`.
- **Findings**:
  - `tool_call_swallowed` and `_steering_replacement` are used to trigger streaming reset and leak protection.
  - Retry counters (`dangerous_command_retry_count`, `tool_call_reactor_retry_count`) are consumed by retry logic and diagnostics.
  - `session_id` and `original_request` are attached to streaming chunks for downstream processors.
- **Implications**: Metadata keys must remain stable, and any refactor must preserve when they are set and how they are propagated.

### Structured Output Middleware Integration
- **Context**: Non-streaming responses apply structured output validation based on processing context.
- **Sources Consulted**: `src/core/services/backend_request_manager_service.py`.
- **Findings**:
  - Structured output middleware is retrieved via runtime DI lookup in the request manager.
  - Processing context carries schema identifiers and request identifiers used in validation logs.
- **Implications**: Replace runtime lookup with an injected collaborator to make dependencies explicit and testable.

### Testing Surface
- **Context**: Existing tests instantiate `BackendRequestManager` directly and exercise streaming edge cases.
- **Sources Consulted**: `tests/unit/core/services/test_backend_request_manager_*`, `tests/integration/test_retry_on_swallow_integration.py`, `tests/integration/test_history_compaction_integration.py`.
- **Findings**:
  - Unit and integration tests cover compaction, deduplication, tool-call retry, and streaming recovery.
  - Construction defaults (optional collaborators) are part of the test contract.
- **Implications**: Maintain constructor compatibility and provide adapter-friendly interfaces for new components.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Orchestrator + Components | Thin `BackendRequestManager` delegating to dedicated services | Aligns with existing patterns, improves testability | Requires careful DI wiring and migration | Recommended |
| Extract-only Helpers | Move logic to helper functions inside the same file | Low disruption | Does not solve modularity | Not sufficient |
| Streaming-first Split | Isolate streaming pipeline only | Targets the largest complexity block | Leaves non-streaming and retry logic monolithic | Partial improvement |

## Design Decisions

### Decision: Componentized Backend Request Manager
- **Context**: Requirements demand modularity and testability without behavior change.
- **Alternatives Considered**:
  1. Extract helper methods only
  2. Move entire class to a new module without decomposition
  3. Decompose into focused services with explicit interfaces
- **Selected Approach**: Decompose into request preparation, non-streaming response handling, streaming response handling, and tool-call retry coordination, with the existing manager as a thin orchestrator.
- **Rationale**: Matches established request processor decomposition and keeps DI seams explicit.
- **Trade-offs**: Additional services and DI wiring increase the number of files but reduce per-file complexity.
- **Follow-up**: Confirm constructor compatibility for tests that instantiate the manager directly.

### Decision: Structured Output Middleware Injection
- **Context**: Runtime service lookups hide dependencies and complicate testing.
- **Alternatives Considered**:
  1. Keep runtime lookup via service provider
  2. Inject a dedicated structured output enforcer interface
- **Selected Approach**: Inject a structured output enforcer into the non-streaming response handler.
- **Rationale**: Makes dependencies explicit and aligns with DI patterns in CoreServicesStage.
- **Trade-offs**: Requires a small adapter around existing middleware.
- **Follow-up**: Ensure optional behavior remains fail-open when schemas are absent.

### Decision: Loop Detector Factory
- **Context**: Loop detector creation currently relies on runtime DI or fallback instantiation.
- **Alternatives Considered**:
  1. Keep runtime DI fallback inside streaming handler
  2. Inject a loop detector factory interface
- **Selected Approach**: Add an injected factory that encapsulates DI lookup and fallback behavior.
- **Rationale**: Keeps streaming pipeline deterministic and testable.
- **Trade-offs**: Adds one extra interface and DI binding.
- **Follow-up**: Preserve current reset behavior for each stream.

### Decision: DI Lifetime Selection
- **Context**: New services are stateless coordinators over existing dependencies.
- **Selected Approach**: Singleton for orchestrators and handlers, consistent with existing DI registrations.
- **Rationale**: Services are stateless and safe to reuse across requests.

### Decision: Error Handling Strategy
- **Context**: Errors are already normalized to `LLMProxyError` subclasses.
- **Selected Approach**: Keep error types unchanged and preserve fail-open behaviors for optional collaborators.

## Testing Strategy Research

### Existing Test Patterns
- Unit tests in `tests/unit/core/services/` with mocked dependencies
- Integration tests in `tests/integration/` for compaction, retry, and streaming

### Coverage Requirements
- Critical paths: empty-response retry, tool-call swallow retry, streaming recovery and loop detection
- Edge cases: no compaction service, no loop detector in DI, Angel verification disabled or failing

## Risks & Mitigations
- Risk 1: Behavior drift in streaming retry logic - Mitigation: characterization tests for streaming recovery and tool-call swallow paths.
- Risk 2: Metadata contract regression - Mitigation: add targeted tests verifying downstream metadata keys.
- Risk 3: DI wiring gaps - Mitigation: update `core_processing` registrations and add DI registration tests.

## Performance Considerations
- Streaming should not buffer unless Angel verification is enabled.
- No additional backend calls beyond existing retry limits.

## References
- Project `AGENTS.md` - Development guidelines
- `src/core/services/backend_request_manager_service.py` - Current implementation
- `src/core/interfaces/backend_request_manager_interface.py` - Public contract
- `src/core/di/registration_helpers/core_processing.py` - DI registration
- `src/core/services/streaming/content_accumulation_processor.py` - Steering replacement handling
