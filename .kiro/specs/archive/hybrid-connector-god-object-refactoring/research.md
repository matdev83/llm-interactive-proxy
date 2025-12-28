# Gap Analysis - Hybrid Connector God Object Refactoring

## Overview

This document analyzes the implementation gap between the requirements in `requirements.md` and the existing codebase to inform the design phase strategy.

**Feature**: `hybrid-connector-god-object-refactoring`  
**Analysis Date**: 2025-12-18  
**Type**: Brownfield Refactoring (decomposition of existing monolith)

---

## 1. Current State Investigation

### 1.1 Key Files and Modules

| Asset | Path | Size | Purpose |
|-------|------|------|---------|
| **Hybrid Connector** | `src/connectors/hybrid.py` | 2,301 lines | God Object - main target for refactoring |
| **Base LLM Backend** | `src/connectors/base.py` | 460 lines | Abstract base class (`LLMBackend`) |
| **Model Capabilities** | `src/connectors/utils/model_capabilities.py` | 158 lines | ✅ Already extracted - reasoning params registry |
| **Stream Processor** | `src/connectors/utils/reasoning_stream_processor.py` | 832 lines | ✅ Already extracted - stream capture logic |
| **Gemini Base Package** | `src/connectors/gemini_base/` | 33 files | Reference architecture for connector decomposition |

### 1.2 Existing Domain Models (in hybrid.py)

| Model | Location | Status |
|-------|----------|--------|
| `HybridModelSpec` | Lines 61-70 | Dataclass - ready to extract |
| `ReasoningPhaseResult` | Lines 73-87 | Dataclass - ready to extract |

### 1.3 Existing Method Count by Responsibility

| Concern | Methods | Lines (Est.) |
|---------|---------|--------------|
| Model Spec Parsing | 1 | ~150 |
| Parameter Application | 2 | ~130 |
| Identity Resolution | 1 | ~30 |
| Reasoning Markup | 8 | ~200 |
| Message Augmentation | 4 | ~150 |
| Response Filtering | 5 | ~170 |
| Response Building | 4 | ~250 |
| Phase Execution | 3 | ~540 |
| Main Orchestration | 3 | ~500 |
| **Total** | **31+** | **~2,120** |

### 1.4 Established Patterns in Codebase

#### Protocol Pattern (gemini_base)

The `gemini_base` package uses Protocol interfaces extensively:

- `src/connectors/gemini_base/interfaces.py` - 20+ Protocols defined
- `@runtime_checkable` decorator used consistently
- Protocol-to-implementation mapping is clean

```python
# Example from gemini_base/interfaces.py
@runtime_checkable
class ICredentialProvider(Protocol):
    """Protocol for OAuth credential providers."""
    def load(self, force_reload: bool = False, silent: bool = False) -> dict[str, Any] | None: ...
```

#### CLI Refactoring Pattern (cli_support)

Recent CLI God Object refactoring created modular structure:

- `src/core/cli_support/` - package with submodules
- `protocols.py` - all interfaces in one file
- `applicators/` - subdirectory for domain applicators
- `configuration_applicator.py`, `error_handler.py`, etc. - focused services

### 1.5 Test Organization

| Test File | Lines | Tested Concerns |
|-----------|-------|-----------------|
| `test_hybrid_connector.py` | 1,365 | Core parsing, spec validation, end-to-end |
| `test_hybrid_augmentation.py` | 48 | Message augmentation |
| `test_hybrid_response_filtering.py` | ~200 | Response tag filtering |
| `test_hybrid_connector_probability.py` | ~600 | Injection probability logic |
| `test_hybrid_uri_params.py` | ~150 | URI parameter handling |
| `test_hybrid_backend_integration.py` | ~200 | Integration tests |

**Observation**: Tests are already somewhat modular, making migration easier.

### 1.6 External Dependencies

| Dependency | Usage in hybrid.py | Impact |
|------------|-------------------|--------|
| `BackendService` | Reasoning phase execution | DI resolution via `get_required_service()` |
| `BackendFactory` | Execution phase backend creation | DI resolution via `get_required_service()` |
| `TranslationService` | Request translation | Constructor injection (✅ good) |
| `URIParameterValidator` | Parameter validation | Inline instantiation (needs refactor) |
| `ReasoningStreamProcessor` | Stream capture | Inline instantiation (could improve) |
| `backend_registry` | Backend registration | Module-level import (acceptable) |

### 1.7 Integration Surfaces

| Surface | Direction | Contract |
|---------|-----------|----------|
| `BackendRegistry.register_backend()` | Outbound | `("hybrid", HybridConnector)` |
| `LLMBackend.chat_completions()` | Inbound | Abstract method signature |
| `LLMBackend.initialize()` | Inbound | Abstract method signature |
| `LLMBackend.get_available_models()` | Inbound | Abstract method signature |
| `ProcessedResponse` | Data | Response chunk contract |
| `StreamingResponseEnvelope` | Data | Streaming response contract |

---

## 2. Requirement-to-Asset Mapping

### 2.1 Functional Requirements Coverage

| Req # | Requirement | Existing Asset | Gap |
|-------|-------------|----------------|-----|
| **1** | Modular Package Structure | None | **Missing** - Package doesn't exist |
| **2.1** | ModelSpecParser extraction | `_parse_hybrid_model_spec()` | Method exists, needs extraction |
| **2.2** | ParameterApplicator extraction | `_apply_reasoning_params()`, `_apply_parameter_overrides()` | Methods exist, need extraction |
| **2.3** | MessageAugmentor extraction | `_augment_messages()`, `_inject_as_system_message()`, `_inject_to_user_message()` | Methods exist, need extraction |
| **2.4** | ReasoningMarkupProcessor extraction | `_normalize_reasoning_markup()`, `_format_reasoning_for_model()`, etc. | 8 methods exist, need extraction |
| **2.5** | ResponseFilter extraction | `_filter_response_content()`, `_filter_response_stream()`, `_filter_json_content()` | Methods exist, need extraction |
| **2.6** | ResponseBuilder extraction | `_build_reasoning_stream_chunk()`, `_build_tool_call_only_response()`, `_prepend_reasoning_*` | Methods exist, need extraction |
| **3** | Protocol interfaces | None in hybrid.py | **Missing** - Need to create protocols.py |
| **4** | Dependency Inversion | Partial - some DI, some inline | **Constraint** - Need to refactor DI usage |
| **5** | Layered Architecture | None | **Missing** - Need to design layers |
| **6** | Domain Model Extraction | `HybridModelSpec`, `ReasoningPhaseResult` exist | Move to `models/` subpackage |
| **7** | Orchestrator Extraction | Logic in `chat_completions()` | **Missing** - 480+ lines need extraction |
| **8** | Injection Policy Extraction | Logic scattered in `chat_completions()` | **Missing** - Need new service |
| **9** | Phase Executor Extraction | `_execute_reasoning_phase()`, `_execute_execution_phase()` | Methods exist, need extraction |
| **10** | Backward Compatibility | `HybridConnector` class | **Constraint** - Must preserve facade |
| **11** | Test Preservation | 12+ test files | **Constraint** - Must migrate carefully |

### 2.2 Gap Summary

| Gap Type | Count | Details |
|----------|-------|---------|
| **Missing** | 4 | Package structure, Protocols, Orchestrator, InjectionPolicy |
| **Extraction** | 7 | All existing methods need extraction to services |
| **Constraint** | 3 | Public API, Test compatibility, DI patterns |

---

## 3. Implementation Approach Options

### Option A: Extend Existing Components (NOT RECOMMENDED)

**Description**: Keep methods in `hybrid.py`, add Protocol interfaces as type hints only.

**Trade-offs**:

- ✅ Minimal risk - no file moves
- ✅ Quick implementation
- ❌ **Does NOT solve the God Object problem**
- ❌ File remains at 2,300+ lines
- ❌ Single Responsibility still violated
- ❌ Testing not improved

**Assessment**: ⛔ **REJECTED** - Does not meet requirements.

---

### Option B: Create New Package (RECOMMENDED)

**Description**: Create `src/connectors/hybrid_backend/` package with full layered architecture.

**Structure**:

```
src/connectors/hybrid_backend/
├── __init__.py              # Public exports
├── protocols.py             # All Protocol interfaces (~100 lines)
├── models/
│   ├── __init__.py
│   ├── model_spec.py        # HybridModelSpec
│   ├── phase_result.py      # ReasoningPhaseResult
│   ├── reasoning_text.py    # NEW: ReasoningText
│   └── injection_decision.py# NEW: InjectionDecision
├── services/
│   ├── __init__.py
│   ├── model_spec_parser.py
│   ├── parameter_applicator.py
│   ├── message_augmentor.py
│   ├── reasoning_markup_processor.py
│   ├── response_filter.py
│   └── response_builder.py
├── orchestration/
│   ├── __init__.py
│   ├── orchestrator.py      # HybridOrchestrator
│   └── injection_policy.py  # InjectionPolicy
└── infrastructure/
    ├── __init__.py
    ├── phase_executor.py    # PhaseExecutor
    └── identity_resolver.py # IdentityResolver
```

**Which files to create**:

- 15-17 new Python files in `hybrid_backend/`
- Convert `hybrid.py` to thin facade

**Integration points**:

- `hybrid.py` imports `HybridOrchestrator` and delegates
- Backend registration unchanged
- Test imports update to new paths

**Trade-offs**:

- ✅ Fully addresses God Object problem
- ✅ Clean separation of concerns (SRP)
- ✅ Protocol-first design (ISP, DIP)
- ✅ Follows `gemini_base` and `cli_support` patterns
- ✅ Each file < 300 lines (maintainable)
- ✅ Unit testing per service possible
- ⚠️ More files to navigate (mitigated by clear structure)
- ⚠️ Requires careful migration (mitigated by phased approach)

**Assessment**: ✅ **RECOMMENDED** - Best alignment with requirements.

---

### Option C: Hybrid Approach (VIABLE ALTERNATIVE)

**Description**: Extract only the most critical services initially, then iterate.

**Phase 1** (minimal viable):

- Create `hybrid_backend/` with:
  - `protocols.py`
  - `models/` (move dataclasses)
  - `orchestration/orchestrator.py`
- Keep remaining logic in `hybrid.py`

**Phase 2** (full extraction):

- Extract services one by one
- Update tests incrementally
- Convert `hybrid.py` to pure facade

**Trade-offs**:

- ✅ Lower immediate risk
- ✅ Allows iterative validation
- ✅ Can pause mid-refactor if issues arise
- ⚠️ Temporary inconsistency during transition
- ⚠️ Longer overall timeline
- ⚠️ `hybrid.py` remains intermediate size until complete

**Assessment**: ✅ **VIABLE** - Consider if timeline is constrained.

---

## 4. Implementation Complexity & Risk

### 4.1 Effort Estimate

| Approach | Effort | Justification |
|----------|--------|---------------|
| **Option A** | S (1-3 days) | Minimal changes, just type hints |
| **Option B** | L (1-2 weeks) | Full package creation, 15+ files, test migration |
| **Option C** | M (3-7 days) | Phased approach, can be paused |

**Recommended**: **Option B** with effort **L (8-10 working days)**

### 4.2 Risk Assessment

| Risk Factor | Level | Mitigation |
|-------------|-------|------------|
| **Test Regression** | Medium | Run full suite at each checkpoint, preserve test logic |
| **Public API Breakage** | Low | Facade pattern explicitly preserves signatures |
| **DI Integration Issues** | Low | Follow established `cli_support` patterns |
| **Performance Regression** | Low | No new allocations, same logic paths |
| **Streaming Breakage** | Medium | Careful attention to async generator delegation |

**Overall Risk**: **Medium** - Manageable with phased approach and test coverage.

### 4.3 Complexity Signals

| Signal | Assessment |
|--------|------------|
| Type of logic | Orchestration + data transformation (no complex algorithms) |
| External integrations | Minimal (uses existing BackendService/BackendFactory) |
| State management | Minimal (mostly stateless, one backoff counter) |
| Concurrency concerns | Moderate (async generators need careful handling) |
| Test coverage | Good (12+ test files covering most paths) |

---

## 5. Recommendations for Design Phase

### 5.1 Preferred Approach

**Option B: Create New Package** with the following adjustments:

1. **Start with models and protocols** - Low risk, establishes contracts
2. **Extract services in dependency order** - Bottom-up to avoid circular imports
3. **Orchestrator last** - After all services are extracted
4. **Facade conversion final step** - When all logic is delegated

### 5.2 Key Decisions for Design Phase

| Decision | Recommendation | Rationale |
|----------|----------------|-----------|
| **Protocol location** | Single `protocols.py` file | Follows `cli_support` pattern, easier discovery |
| **Layer enforcement** | Import linting via tests | Add tests that verify import constraints |
| **Test migration** | Update imports only initially | Avoid test logic changes until stable |
| **DI usage** | Inject via constructor | Consistent with existing DI patterns |
| **Streaming handling** | Pass-through delegation | Avoid wrapping async generators |

### 5.3 Research Items for Design Phase

| Item | Question | Priority |
|------|----------|----------|
| **Async generator delegation** | How to preserve cancel_callback when wrapping streams? | High |
| **Dataclass immutability** | Use `frozen=True` for all models or selectively? | Medium |
| **Protocol runtime checking** | Performance impact of `@runtime_checkable` in hot paths? | Low |
| **Import cycle prevention** | Best pattern for avoiding circular imports between layers? | High |

### 5.4 Potential Blockers

| Blocker | Likelihood | Mitigation |
|---------|------------|------------|
| Test mocking complexity | Medium | May need to update fixtures to inject mocks |
| Circular import issues | Medium | Use TYPE_CHECKING imports, careful layer design |
| Streaming edge cases | Low | Existing tests cover most cases |

---

## 6. Checklist Summary

- [x] Requirement-to-Asset Map with gaps (Section 2)
- [x] Options A/B/C with rationale and trade-offs (Section 3)
- [x] Effort (L) and Risk (Medium) with justification (Section 4)
- [x] Recommendations for design phase (Section 5)
- [x] Research items carried forward (Section 5.3)

---

## 7. Conclusion

The gap analysis confirms that **Option B: Create New Package** is the recommended approach for the hybrid connector refactoring. The existing codebase provides strong reference patterns (`gemini_base`, `cli_support`) that can be followed.

**Key takeaways**:

1. Existing methods can be extracted with minimal logic changes
2. Protocol-first design is well-established in the codebase
3. Test organization already supports modular extraction
4. Risk is manageable with phased implementation
5. Estimated effort: **8-10 working days**

**Next Step**: Proceed to design phase (`/kiro:spec-design`) to create detailed technical specification.
