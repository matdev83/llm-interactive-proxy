# Implementation Plan: Hybrid Connector God Object Refactoring

## Overview

This implementation plan decomposes the 2,301-line `HybridConnector` God Object into a modular, layered architecture following TDD principles. The work is organized into 5 phases executed incrementally, with each phase producing a shippable checkpoint.

**Estimated Total Effort**: L (8-10 days)

**Implementation Strategy**: Bottom-up (Models → Services → Infrastructure → Orchestration → Facade)

---

## Phase 1: Foundation - Package Structure and Models

### Goal

Create the `hybrid_backend/` package skeleton and extract domain models. This phase has no behavioral changes - existing tests continue to pass.

- [x] 1. Create package structure for `src/connectors/hybrid_backend/`
  - Create `__init__.py` with public exports placeholder
  - Create `protocols.py` skeleton with docstring
  - Create `models/`, `services/`, `orchestration/`, `infrastructure/` subdirectories with `__init__.py`
  - _Requirements: 1_

- [x] 2. Extract `HybridModelSpec` dataclass to `models/model_spec.py`
  - Move dataclass from `hybrid.py` with `frozen=True`
  - Add comprehensive docstring and type hints
  - Re-export from `models/__init__.py`
  - Add backward-compatible re-export in `hybrid.py`
  - Run QA: `ruff check --fix && black && mypy`
  - _Requirements: 6.1_

- [x] 3. Extract `ReasoningPhaseResult` dataclass to `models/phase_result.py`
  - Move dataclass from `hybrid.py` (keep mutable - has list fields)
  - Use `TYPE_CHECKING` for `ProcessedResponse` import
  - Add `has_tool_calls()` method
  - Re-export from `models/__init__.py`
  - Add backward-compatible re-export in `hybrid.py`
  - Run QA: `ruff check --fix && black && mypy`
  - _Requirements: 6.2_

- [x] 4. Create new `ReasoningText` dataclass in `models/reasoning_text.py`
  - Implement with `frozen=True` for immutability
  - Fields: `tagged: str`, `plain: str`, `backend: str`
  - Add comprehensive docstring
  - Re-export from `models/__init__.py`
  - Run QA
  - _Requirements: 6.3_

- [x] 5. Create new `InjectionDecision` dataclass in `models/injection_decision.py`
  - Implement with `frozen=True` for immutability
  - Fields: `should_inject: bool`, `reason: str`, `is_first_turn: bool`, `probability_used: float`
  - Add comprehensive docstring
  - Re-export from `models/__init__.py`
  - Run QA
  - _Requirements: 6.4_

- [x] 6. **CHECKPOINT**: Verify existing tests still pass
  - Run: `.venv\Scripts\python.exe -m pytest tests/unit/connectors/test_hybrid*.py -v`
  - Run: `.venv\Scripts\python.exe -m pytest tests/integration/connectors/test_hybrid*.py -v`
  - Verify no import errors or behavioral changes
  - _Requirements: 10, 11_

---

## Phase 2: Protocol Definitions

### Goal

Define all Protocol interfaces in `protocols.py`. Pure type definitions - no implementation yet.

- [x] 7. Define `IModelSpecParser` protocol in `protocols.py`
  - Single method: `parse(model_spec: str) -> HybridModelSpec`
  - Add `@runtime_checkable` decorator
  - Document preconditions (valid format), postconditions (parsed spec), exceptions (ValueError)
  - _Requirements: 3_

- [x] 8. Define `IParameterApplicator` protocol in `protocols.py`
  - Methods: `apply_reasoning_params()`, `apply_execution_params()`
  - Accept `DomainModel | InternalDTO | dict[str, Any]` for flexibility
  - Add `@runtime_checkable` decorator
  - _Requirements: 3_

- [x] 9. Define `IReasoningMarkupProcessor` protocol in `protocols.py`
  - Methods: `normalize()`, `format_for_model()`, `extract_plain_text()`
  - Return `ReasoningText` from `normalize()`
  - Add `@runtime_checkable` decorator
  - _Requirements: 3_

- [x] 10. Define `IMessageAugmentor` protocol in `protocols.py`
  - Single method: `augment(messages, reasoning_output, execution_backend) -> list`
  - Add `@runtime_checkable` decorator
  - _Requirements: 3_

- [x] 11. Define `IResponseFilter` protocol in `protocols.py`
  - Methods: `filter_content(content: Any) -> Any`, `filter_stream(response) -> StreamingResponseEnvelope`
  - Note: `filter_stream` is async
  - Add `@runtime_checkable` decorator
  - _Requirements: 3_

- [x] 12. Define `IResponseBuilder` protocol in `protocols.py`
  - Methods: `build_reasoning_chunk()`, `build_tool_call_response()`, `prepend_reasoning_to_stream()`
  - Add `@runtime_checkable` decorator
  - _Requirements: 3_

- [x] 13. Define `IInjectionPolicy` protocol in `protocols.py`
  - Methods: `should_inject() -> InjectionDecision`, `update_backoff(success: bool) -> None`
  - Add `@runtime_checkable` decorator
  - Document stateful nature in docstring
  - _Requirements: 3_

- [x] 14. Define `IPhaseExecutor` protocol in `protocols.py`
  - Async methods: `execute_reasoning_phase()`, `execute_execution_phase()`
  - Document timeout and error handling in docstrings
  - Add `@runtime_checkable` decorator
  - _Requirements: 3_

- [x] 15. Define `IHybridOrchestrator` protocol in `protocols.py`
  - Single async method: `execute() -> ResponseEnvelope | StreamingResponseEnvelope`
  - Add `@runtime_checkable` decorator
  - _Requirements: 3_

- [x] 16. Run QA on `protocols.py`
  - Run: `.venv\Scripts\python.exe -m ruff check --fix src/connectors/hybrid_backend/protocols.py`
  - Run: `.venv\Scripts\python.exe -m mypy src/connectors/hybrid_backend/protocols.py`
  - _Requirements: NFR 1_

---

## Phase 3: Service Implementations (TDD)

### Goal

Implement all service layer components following TDD (test first, then implement).

### 3.1 ModelSpecParser

- [x] 17. Write unit tests for `ModelSpecParser` (RED)
  - Create `tests/unit/connectors/hybrid_backend/test_model_spec_parser.py`
  - Test valid formats: single backend, dual backend, with params
  - Test invalid formats: missing brackets, invalid syntax, empty string
  - Test edge cases: URL-encoded params, special characters
  - _Requirements: 2.1_

- [x] 18. Implement `ModelSpecParser` in `services/model_spec_parser.py` (GREEN)
  - Extract `_parse_hybrid_model_spec()` logic from `hybrid.py`
  - Implement `IModelSpecParser` protocol
  - Preserve existing error messages for backward compatibility
  - Run tests: `.venv\Scripts\python.exe -m pytest tests/unit/connectors/hybrid_backend/test_model_spec_parser.py -v`
  - Run QA on source file
  - _Requirements: 2.1_

### 3.2 ReasoningMarkupProcessor

- [x] 19. Write unit tests for `ReasoningMarkupProcessor` (RED) (P)
  - Create `tests/unit/connectors/hybrid_backend/test_reasoning_markup_processor.py`
  - Test `normalize()`: canonical tags, closure, partial input
  - Test `format_for_model()`: backend-specific tag selection
  - Test `extract_plain_text()`: tag stripping, nested tags
  - _Requirements: 2.4_

- [x] 20. Implement `ReasoningMarkupProcessor` in `services/reasoning_markup_processor.py` (GREEN)
  - Extract tag processing methods from `hybrid.py`:
    - `_normalize_reasoning_markup()`
    - `_apply_reasoning_tag_wrapping()`
    - `_extract_reasoning_inner_text()`
    - `_format_reasoning_for_model()`
    - `_assemble_reasoning_markup()`
    - `_truncate_after_reasoning_close()`
    - `_has_reasoning_content()`
    - `_prepare_reasoning_texts()`
  - Compile regex patterns as class attributes
  - Return `ReasoningText` from `normalize()`
  - Run tests and QA
  - _Requirements: 2.4_

### 3.3 ResponseFilter

- [x] 21. Write unit tests for `ResponseFilter` (RED) (P)
  - Create `tests/unit/connectors/hybrid_backend/test_response_filter.py`
  - Test `filter_content()`: string, dict, bytes, SSE chunks
  - Test `filter_stream()`: async generator filtering
  - Test nested JSON filtering
  - _Requirements: 2.5_

- [x] 22. Implement `ResponseFilter` in `services/response_filter.py` (GREEN)
  - Extract filtering methods from `hybrid.py`:
    - `_strip_reasoning_tags()`
    - `_filter_response_content()`
    - `_filter_json_content()`
    - `_filter_response_stream()`
  - Compile regex patterns as class attributes
  - Preserve async generator behavior for streaming
  - Run tests and QA
  - _Requirements: 2.5_

### 3.4 ParameterApplicator

- [x] 23. Write unit tests for `ParameterApplicator` (RED) (P)
  - Create `tests/unit/connectors/hybrid_backend/test_parameter_applicator.py`
  - Test Pydantic model handling
  - Test dict handling
  - Test dataclass handling
  - Test URI parameter overrides
  - _Requirements: 2.2_

- [x] 24. Implement `ParameterApplicator` in `services/parameter_applicator.py` (GREEN)
  - Extract parameter methods from `hybrid.py`:
    - `_apply_reasoning_params()`
    - `_apply_parameter_overrides()`
  - Import from `model_capabilities` for phase params
  - Handle all request data types uniformly
  - Run tests and QA
  - _Requirements: 2.2_

### 3.5 MessageAugmentor

- [x] 25. Write unit tests for `MessageAugmentor` (RED) (P)
  - Create `tests/unit/connectors/hybrid_backend/test_message_augmentor.py`
  - Test system message injection (backend supports system role)
  - Test user message prepending (backend doesn't support system role)
  - Test repeat-message mode (assistant message injection)
  - Mock `IReasoningMarkupProcessor` dependency
  - _Requirements: 2.3_

- [x] 26. Implement `MessageAugmentor` in `services/message_augmentor.py` (GREEN)
  - Extract augmentation methods from `hybrid.py`:
    - `_augment_messages()`
    - `_inject_as_system_message()`
    - `_inject_to_user_message()`
    - `_supports_system_messages()`
  - Inject `IReasoningMarkupProcessor` via constructor
  - Inject `AppConfig` for `hybrid_backend_repeat_messages` setting
  - Run tests and QA
  - _Requirements: 2.3_

### 3.6 ResponseBuilder

- [x] 27. Write unit tests for `ResponseBuilder` (RED) (P)
  - Create `tests/unit/connectors/hybrid_backend/test_response_builder.py`
  - Test `build_reasoning_chunk()`: streaming chunk construction
  - Test `build_tool_call_response()`: tool-call-only scenarios
  - Test `prepend_reasoning_to_stream()`: async generator wrapping, cancel_callback preservation
  - Mock `IReasoningMarkupProcessor` dependency
  - _Requirements: 2.6_

- [x] 28. Implement `ResponseBuilder` in `services/response_builder.py` (GREEN)
  - Extract builder methods from `hybrid.py`:
    - `_build_reasoning_stream_chunk()`
    - `_build_tool_call_only_response()`
    - `_prepend_reasoning_chunk_to_stream()`
    - `_prepend_reasoning_to_non_streaming_content()`
    - `_format_reasoning_for_client()`
  - Inject `IReasoningMarkupProcessor` via constructor
  - Preserve `cancel_callback` in stream wrapping
  - Run tests and QA
  - _Requirements: 2.6_

- [x] 29. **CHECKPOINT**: Run all Phase 3 tests
  - Run: `.venv\Scripts\python.exe -m pytest tests/unit/connectors/hybrid_backend/ -v`
  - Verify all services pass their unit tests
  - Run: `.venv\Scripts\python.exe -m mypy src/connectors/hybrid_backend/services/`
  - _Requirements: 11, NFR 1_

---

## Phase 4: Infrastructure and Orchestration

### Goal

Implement infrastructure layer (backend interaction) and orchestration layer (flow coordination).

### 4.1 IdentityResolver

- [x] 30. Write unit tests for `IdentityResolver` (RED)
  - Create `tests/unit/connectors/hybrid_backend/test_identity_resolver.py`
  - Test preference order: backend-specific → request → global
  - Test None handling at each level
  - _Requirements: 9_

- [x] 31. Implement `IdentityResolver` in `infrastructure/identity_resolver.py` (GREEN)
  - Extract `_resolve_backend_identity()` from `hybrid.py`
  - Simple utility class (no protocol needed)
  - Inject `AppConfig` via constructor
  - Run tests and QA
  - _Requirements: 9_

### 4.2 PhaseExecutor

- [x] 32. Write unit tests for `PhaseExecutor` (RED)
  - Create `tests/unit/connectors/hybrid_backend/test_phase_executor.py`
  - Test `execute_reasoning_phase()`: backend resolution, streaming capture, timeout
  - Test `execute_execution_phase()`: backend resolution, augmented messages
  - Test error handling: backend not found, timeout, backend errors
  - Mock `BackendService`, `BackendFactory`, `URIParameterValidator`
  - _Requirements: 9_

- [x] 33. Implement `PhaseExecutor` in `infrastructure/phase_executor.py` (GREEN)
  - Extract phase execution methods from `hybrid.py`:
    - `_execute_reasoning_phase()`
    - `_execute_execution_phase()`
    - `_prepare_backend_request()`
  - Inject dependencies: `client`, `config`, `backend_registry`, `IParameterApplicator`, `IdentityResolver`
  - Use `ReasoningStreamProcessor` for reasoning phase
  - Apply URI parameters via `URIParameterValidator`
  - **Observability**: Add entry/exit logging with timing for each phase (NFR 4)
  - **Error context**: Include backend name and model in exception messages (NFR 4)
  - Run tests and QA
  - _Requirements: 9, NFR 4_

### 4.3 InjectionPolicy

- [x] 34. Write unit tests for `InjectionPolicy` (RED)
  - Create `tests/unit/connectors/hybrid_backend/test_injection_policy.py`
  - Test first-turn forcing (`forced_initial_turns` window)
  - Test probability-based injection (deterministic with seed)
  - Test adaptive backoff: `update_backoff()` state changes
  - Test `InjectionDecision` return values and reasons
  - _Requirements: 8_

- [x] 35. Implement `InjectionPolicy` in `orchestration/injection_policy.py` (GREEN)
  - Extract injection logic from `chat_completions()` in `hybrid.py`:
    - `_is_first_user_turn()`
    - Probability calculation
    - Backoff state management
  - Inject `AppConfig` via constructor
  - Implement `IInjectionPolicy` protocol
  - Maintain `_reasoning_backoff_remaining` state
  - Run tests and QA
  - _Requirements: 8_

### 4.4 HybridOrchestrator

- [x] 36. Write unit tests for `HybridOrchestrator` (RED)
  - Create `tests/unit/connectors/hybrid_backend/test_orchestrator.py`
  - Test full flow: parse → inject → reasoning → augment → execution → filter → build
  - Test short-circuit: tool-call-only response (Req 7.5)
  - Test non-injection flow: skip reasoning phase
  - Test timeout handling: proceed to execution with empty reasoning (Req 7.4)
  - Test error propagation
  - Mock all service dependencies
  - _Requirements: 7_

- [x] 37. Implement `HybridOrchestrator` in `orchestration/orchestrator.py` (GREEN)
  - Extract orchestration logic from `chat_completions()` in `hybrid.py`
  - Inject all 7 service dependencies via constructor:
    - `IModelSpecParser`
    - `IParameterApplicator`
    - `IInjectionPolicy`
    - `IPhaseExecutor`
    - `IMessageAugmentor`
    - `IResponseFilter`
    - `IResponseBuilder`
  - Inject `AppConfig` for additional settings
  - Implement `IHybridOrchestrator` protocol
  - Keep `execute()` method ≤100 lines
  - Run tests and QA
  - _Requirements: 7, 4_

- [x] 38. **CHECKPOINT**: Run all Phase 4 tests
  - Run: `.venv\Scripts\python.exe -m pytest tests/unit/connectors/hybrid_backend/ -v`
  - Verify orchestrator and infrastructure pass tests
  - Run: `.venv\Scripts\python.exe -m mypy src/connectors/hybrid_backend/infrastructure/ src/connectors/hybrid_backend/orchestration/`
  - _Requirements: 11, NFR 1_

---

## Phase 5: Facade Integration and Migration

### Goal

Convert `HybridConnector` to thin facade, update exports, run full regression suite.

- [x] 39. Implement `_build_orchestrator()` method in `hybrid.py`
  - Follow the wiring order from design.md:
    1. Stateless services (no dependencies)
    2. Services with service dependencies
    3. Infrastructure (external I/O)
    4. Orchestration (stateful policy)
    5. Main orchestrator
  - Match constructor signatures exactly
  - Run QA on `hybrid.py`
  - _Requirements: 4, 10_

- [x] 40. Update `HybridConnector.chat_completions()` to delegate to orchestrator
  - Replace method body with single delegation call
  - Preserve method signature exactly
  - Run QA on `hybrid.py`
  - _Requirements: 10_

- [x] 41. Update `HybridConnector.initialize()` to slim façade version
  - Handle backend registry resolution if not provided
  - Add logging for successful initialization
  - Run QA on `hybrid.py`
  - _Requirements: 10_

- [x] 42. Clean up `hybrid.py` - remove extracted methods
  - Remove all methods that were extracted to services
  - Keep only facade methods: `__init__`, `initialize`, `get_available_models`, `chat_completions`, `_build_orchestrator`
  - Keep backward-compatible re-exports for models
  - Target size: ~150 lines (down from 2,301)
  - Run QA on `hybrid.py`
  - _Requirements: 1, 10_

- [x] 43. Update `hybrid_backend/__init__.py` public exports
  - Export: `HybridOrchestrator`, `HybridModelSpec`, `ReasoningPhaseResult`, `ReasoningText`, `InjectionDecision`
  - Export all `I*` protocols for type checking
  - _Requirements: 1_

- [x] 44. Write architectural layer boundary tests
  - Create `tests/unit/connectors/hybrid_backend/test_layer_boundaries.py`
  - Implement `test_no_upward_layer_imports()`
  - Implement `test_models_have_no_internal_dependencies()`
  - Run: `.venv\Scripts\python.exe -m pytest tests/unit/connectors/hybrid_backend/test_layer_boundaries.py -v`
  - _Requirements: 5_

- [x] 45. **CHECKPOINT**: Run existing hybrid tests (regression)
  - Run: `.venv\Scripts\python.exe -m pytest tests/unit/connectors/test_hybrid*.py -v`
  - Run: `.venv\Scripts\python.exe -m pytest tests/integration/connectors/test_hybrid*.py -v`
  - All tests must pass WITHOUT modification
  - _Requirements: 10, 11_

- [x] 46. Run full test suite
  - Run: `.venv\Scripts\python.exe -m pytest -m "not slow" -v`
  - Verify zero regressions across entire codebase
  - _Requirements: 11_

- [x] 47. Run final quality checks
  - Run: `.venv\Scripts\python.exe -m ruff check src/connectors/hybrid_backend/ src/connectors/hybrid.py`
  - Run: `.venv\Scripts\python.exe -m mypy src/connectors/hybrid_backend/ src/connectors/hybrid.py`
  - Run: `.venv\Scripts\python.exe -m black --check src/connectors/hybrid_backend/ src/connectors/hybrid.py`
  - _Requirements: NFR 1_

---

## Post-Implementation Verification

- [x] 48. Verify all requirements are satisfied
  - [x] Req 1: Package structure created with 4 subdirectories
  - [x] Req 2.1-2.6: All 6 services extracted with SRP
  - [x] Req 3: All 9 protocols defined with `@runtime_checkable`
  - [x] Req 4: Orchestrator uses constructor injection
  - [x] Req 5: Layer boundaries enforced (architectural test passes)
  - [x] Req 6: All 4 domain models in `models/` package (6.1-6.4), with immutability (6.5)
  - [x] Req 7: `HybridOrchestrator.execute()` ≤100 lines, timeout handling, tool-call short-circuit
  - [x] Req 8: `InjectionPolicy` encapsulates decision logic
  - [x] Req 9: `PhaseExecutor` handles backend interaction with observability
  - [x] Req 10: Public API unchanged, backward compatible
  - [x] Req 11: 100% existing tests pass
  - [x] NFR 1-4: Code quality, performance, maintainability, observability
  - _Requirements: All_

- [x] 49. Update spec.json to implementation-complete
  - Set `phase` to `implementation-complete`
  - Set `implementation_status` to `complete`
  - Set `ready_for_implementation` to `false` (done)
  - _Requirements: All_

---

## CRITICAL: Post-Edit QA Workflow

**MANDATORY**: After editing ANY Python (*.py) file, immediately run:

```powershell
./.venv/Scripts/python.exe -m ruff check --fix <modified_filename> && ./.venv/Scripts/python.exe -m black <modified_filename> && ./.venv/Scripts/python.exe -m mypy <modified_filename>
```

---

## Task Summary

| Phase | Tasks | Effort | Parallel Work |
|-------|-------|--------|---------------|
| 1. Foundation | 1-6 | S (0.5 day) | Limited |
| 2. Protocols | 7-16 | S (0.5 day) | Sequential |
| 3. Services | 17-29 | M (2-3 days) | Tasks 19, 21, 23, 25, 27 parallel |
| 4. Infrastructure | 30-38 | M (2 days) | Limited |
| 5. Facade | 39-49 | M (2 days) | Sequential |
| **Total** | **49** | **L (8-10 days)** | |

---

## Checklist Before Marking Complete

- [x] All acceptance criteria from requirements are covered
- [x] Unit tests pass with good coverage (one per service)
- [x] Integration tests verify full flow (existing tests pass)
- [x] Architectural tests verify layer boundaries
- [x] No lint errors (`ruff check .`)
- [x] Type checks pass (`mypy src/connectors/hybrid_backend/`)
- [x] Error handling uses existing exception hierarchy
- [x] Async/await used correctly (no blocking I/O)
- [x] `HybridConnector` reduced from 2,301 to ~150 lines
- [x] Each service file ≤300 lines
