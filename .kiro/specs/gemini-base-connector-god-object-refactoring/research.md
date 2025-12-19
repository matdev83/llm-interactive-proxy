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
- **Feature**: `gemini-base-connector-god-object-refactoring`
- **Discovery Scope**: Extension
- **Key Findings**:
  - `src/connectors/gemini_base/connector.py` is ~2.1k LOC and still owns health checks, model discovery/cache, and orchestration despite existing helper modules.
  - Compatibility constraints exist via `src/connectors/gemini_oauth_base.py` and tests that assert method presence or scan connector source patterns.
  - Backend registration uses direct class registration (`backend_registry.register_backend(...)`), so DI usage must be optional and backward compatible.

## Research Log

### Existing Codebase Analysis
- **Components Reviewed**:
  - `src/connectors/gemini_base/connector.py` - current monolith and responsibilities
  - `src/connectors/gemini_base/chat_request_preparer.py` - request preparation flow
  - `src/connectors/gemini_base/orchestrator.py` - streaming and non-streaming orchestration
  - `src/connectors/gemini_base/streaming_executor.py` - streaming HTTP execution
  - `src/connectors/gemini_base/token_manager.py` and `src/connectors/gemini_base/credential_loader.py` - credential lifecycle
  - `src/connectors/gemini_base/file_watcher.py` - credential change watching
  - `src/connectors/gemini_oauth_base.py` - facade and compatibility wrapper
  - `src/core/services/backend_registry.py` - backend registration
- **Patterns Identified**:
  - Strategy and protocol interfaces in `src/connectors/gemini_base/interfaces.py` and `src/connectors/gemini_base/connector_context.py`.
  - Connector factory registration is class-based with no DI provider input.
  - Streaming flow is centralized in `StreamingExecutor` and `CodeAssistOrchestrator` with translation handled by `TranslationService`.
- **Implications**: The refactor should further isolate responsibilities without changing public connector methods or registration patterns.

### Compatibility Constraints from Tests
- **Context**: Requirements demand behavior stability and ease of testing.
- **Sources Consulted**:
  - `tests/unit/connectors/test_simple_duplicate_detection.py`
  - `tests/behavior/test_gemini_oauth_auth_retry_behavior.py`
  - `tests/unit/connectors/test_gemini_oauth_auth_retry.py`
- **Findings**:
  - Tests assert presence of `_chat_completions_code_assist` and `_chat_completions_code_assist_streaming` on the connector.
  - Some tests scan source for specific call patterns and method bodies.
- **Implications**: The connector facade must keep method names and compatibility shims; refactoring must avoid renaming or removing these methods.

### DI and Registration Constraints
- **Context**: Requirement 3 emphasizes DI and interface boundaries.
- **Sources Consulted**:
  - `src/core/di/container.py`
  - `src/core/di/services.py`
  - `src/connectors/gemini_oauth_plan.py`
- **Findings**:
  - Backends are registered by class and instantiated outside DI, but connector constructors already accept optional injected services.
- **Implications**: DI integration should be additive, using optional dependency injection and factory helpers without altering backend registration semantics.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
| --- | --- | --- | --- | --- |
| Facade + Service Composition | Keep `GeminiOAuthBaseConnector` as facade delegating to internal services | Preserves compatibility, isolates responsibilities | Requires adapter methods in facade | Recommended |
| Monolith Preservation | Keep most logic in connector.py | Lowest change risk | Fails modularity and testability goals | Not aligned |
| Full DI Conversion | Move all subcomponents to DI-managed services and inject via provider | Strong separation and test seams | Risky given registration patterns and tests | Defer |

## Design Decisions

### Decision: Preserve Connector Facade and Public Methods
- **Context**: Tests and facade modules depend on method names and behavior.
- **Alternatives Considered**:
  1. Rename and replace connector class
  2. Keep connector class and delegate internally
- **Selected Approach**: Keep `GeminiOAuthBaseConnector` as a thin facade that delegates to new internal services.
- **Rationale**: Avoids breaking tests and maintains backend registration compatibility.
- **Trade-offs**: Requires adapter methods in the facade layer.
- **Follow-up**: Validate reflection-based tests after changes.

### Decision: Introduce Internal Coordinator Services
- **Context**: Requirements demand modularity and isolated responsibilities.
- **Alternatives Considered**:
  1. Extract discrete services for credentials, models, health checks, chat flow
  2. Consolidate into fewer services to minimize new files
- **Selected Approach**: Introduce focused services aligned to existing boundaries.
- **Rationale**: Matches existing patterns and simplifies testing.
- **Trade-offs**: More files and DI wiring overhead.
- **Follow-up**: Ensure connector remains the only public entrypoint.

### Decision: DI Lifetime Selection
- **Context**: Services hold backend-specific state (credentials, models).
- **Selected Approach**:
  - **Transient** for per-connector services (created once during connector construction).
  - **Singleton** for stateless shared utilities (token estimator, auth provider).
- **Rationale**: Avoids cross-backend state leakage while enabling DI.

### Decision: DI Integration Approach
- **Context**: Connector factories are class-registered and do not receive DI providers directly.
- **Alternatives Considered**:
  1. Pass provider into connector constructors
  2. Resolve optional services via `get_service_provider()` at runtime
- **Selected Approach**: Use `get_service_provider()` to resolve optional services when available, with fallback to default constructors.
- **Rationale**: Matches existing connector patterns and preserves backend registry behavior.
- **Trade-offs**: Requires explicit fallback handling when DI services are not registered.

### Decision: Error Handling Strategy
- **Context**: Preserve error mapping and resilience behavior.
- **Selected Approach**: Reuse existing `LLMProxyError` subclasses and keep error mapping centralized in a dedicated error-mapping helper.
- **Rationale**: Maintains stable semantics for resilience and failover logic.

## Testing Strategy Research

### Existing Test Patterns
- Unit tests in `tests/unit/` with mocked dependencies
- Behavior tests in `tests/behavior/` for connector resilience and auth retry flows

### Coverage Requirements
- Critical paths: streaming and non-streaming chat completions, credential refresh, health checks
- Edge cases: expired tokens, 401/429 handling, credential file change events

## Risks & Mitigations
- Risk 1: Compatibility regressions from method refactors - Mitigation: keep facade methods and add delegation tests.
- Risk 2: DI wiring mismatch with backend registration - Mitigation: optional DI via `get_service_provider()` with default fallback instantiation.
- Risk 3: Streaming behavior changes - Mitigation: keep `StreamingExecutor` and `CodeAssistOrchestrator` unchanged.

## Performance Considerations
- Async I/O paths remain unchanged; new services should avoid additional network calls.
- Caching (models, credentials) remains local to the connector instance to avoid contention.

## References
- `src/connectors/gemini_base/connector.py`
- `src/connectors/gemini_base/chat_request_preparer.py`
- `src/connectors/gemini_base/orchestrator.py`
- `src/connectors/gemini_base/streaming_executor.py`
- `src/connectors/gemini_oauth_base.py`
- `src/core/di/container.py`
- `src/core/services/backend_registry.py`
- Project `AGENTS.md`
