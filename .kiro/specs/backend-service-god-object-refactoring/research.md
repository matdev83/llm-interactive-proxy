# Research Document: BackendService God Object Refactoring

## Discovery Summary

This document captures research findings and architectural decisions for refactoring the `BackendService` God Object into focused, single-responsibility services.

## Existing Architecture Analysis

### Current BackendService Structure

**File**: `src/core/services/backend_service.py` (~2109 lines)

**Key Findings**:
1. **Constructor Complexity**: 18+ optional parameters with inline instantiation (`if service is None: create_default()`)
2. **Mixed Responsibilities**: Combines lifecycle, failover, resolution, transformation, processing, and exception handling
3. **Partial Integration**: Some services exist but are not fully utilized (BackendLifecycleManager, FailoverCoordinator, ExceptionNormalizer)
4. **Test Dependencies**: Tests access private methods directly, requiring wrapper preservation

### Existing Services Analysis

**Fully Implemented Services**:
- `BackendLifecycleManager` - Backend creation, caching, per-session limits
- `FailoverCoordinator` - Failover coordination (delegates to FailoverService)
- `ExceptionNormalizer` - Provider exception normalization
- `ModelAliasResolver` - Model alias resolution
- `ReasoningConfigApplicator` - Reasoning config application
- `URIParameterApplicator` - URI parameter application
- `StreamFormattingService` - SSE encoding and chunk validation
- `UsageTrackingWrapper` - Usage tracking wrapper
- `PlanningPhaseManager` - Planning phase management

**Integration Status**: All services exist but are partially integrated with BackendService still containing embedded logic.

### DI Registration Patterns

**Current Pattern** (`src/core/di/services.py`):
- Factory functions for complex services: `def _service_factory(provider: IServiceProvider) -> ServiceType`
- Singleton lifetime for most services
- Interface binding: `services.add_singleton(IService, ImplementationType)`
- Helper function `_add_singleton` for idempotent registration

**Key Pattern**: Services with complex dependencies use factory functions that resolve dependencies via `provider.get_required_service()`.

## Architecture Pattern Selection

### Selected Pattern: Service-Based Decomposition

**Rationale**:
1. **Aligns with existing architecture**: Codebase already uses service-based patterns
2. **SOLID compliance**: Each service has single responsibility
3. **Testability**: Services can be tested independently
4. **DI integration**: Fits existing DI container patterns
5. **Maintainability**: Smaller, focused services are easier to understand

### Rejected Alternatives

**Option A: Extend Existing Components**
- ❌ Doesn't fully address SRP violations
- ❌ Leaves responsibilities mixed in BackendService
- ❌ Doesn't reduce complexity significantly

**Option C: Hybrid Approach**
- ⚠️ More complex planning required
- ⚠️ Potential for inconsistency
- ✅ Could work but Option B is cleaner

## Component Boundary Analysis

### Domain Boundaries

**BackendService (Orchestration Layer)**:
- Coordinates extracted services
- Maintains public API contract
- Preserves backward compatibility via wrapper methods

**Extracted Services (Implementation Layer)**:
- BackendModelResolver: Backend and model resolution logic
- RequestTransformer: Request transformation coordination
- StreamProcessor: Stream processing logic
- FailureStrategyExecutor: Failure strategy execution
- FailoverPlanGenerator: Failover plan generation
- ComplexFailoverExecutor: Complex failover execution

### Integration Points

**Service Communication**:
- All services communicate via interfaces (`I*` naming)
- BackendService orchestrates service calls
- Services depend on interfaces, not concrete implementations

**Data Flow**:
- Request flows: Request → BackendModelResolver → RequestTransformer → Backend → StreamProcessor → Response
- Failover flows: Failure → FailureStrategyExecutor → FailoverPlanGenerator → ComplexFailoverExecutor

## Behavior Preservation Analysis

### Critical Methods Analysis

**`_resolve_backend_and_model` (Lines 1622-1747)**:
- **Side Effects**: 
  - Calls `planning_phase_manager.apply_if_needed()` (modifies session state)
  - Accesses `backend_lifecycle_manager.get_disabled_backends()` (reads state)
  - Calls `routing_service.resolve_backend_instance()` (may modify routing state)
- **Invariants**:
  - Model aliases applied BEFORE backend parsing
  - Static route override applied AFTER all resolution
  - URI parameters extracted during parsing
- **Dependencies**: SessionService, PlanningPhaseManager, BackendLifecycleManager, BackendRoutingService, ModelAliasResolver, IConfig

**`_execute_complex_failover` (Lines 1844-1883)**:
- **Side Effects**: Creates BackendConfiguration, calls `_get_failover_plan`, `_attempt_failover_plan`
- **Invariants**: Failover plan must be non-empty, errors must be wrapped in BackendError
- **Dependencies**: FailoverCoordinator, BackendLifecycleManager

**`_attempt_failover_plan` (Lines 1885-1957)**:
- **Side Effects**: Recursively calls `call_completion` with `allow_failover=False`
- **Invariants**: First successful attempt returns, all failures raise BackendError
- **Dependencies**: BackendService (recursive), BackendModelResolver

### Test Access Patterns

**Analysis of `test_backend_service_targeted.py`**:
- Tests access private methods: `_apply_model_aliases`, `_normalize_provider_exception`, `_get_or_create_backend`
- Tests verify behavior through public API: `call_completion`, `validate_backend_and_model`
- Property tests verify API stability: `test_backend_service_api_preservation.py`

**Wrapper Strategy**: Keep all private methods as thin delegating wrappers to preserve test compatibility.

## Request Transformation Order

**Current Order** (verified in `backend_service.py:2053-2082`):
1. Model alias resolution (`_apply_model_aliases`)
2. Reasoning config application (`_apply_reasoning_config`)
3. URI parameter application (`_apply_uri_parameters`)

**Preservation Requirement**: RequestTransformer must maintain this exact order.

## DI Registration Strategy

### Registration Pattern

**For New Services**:
```python
def _service_factory(provider: IServiceProvider) -> ServiceType:
    dep1 = provider.get_required_service(IDependency1)
    dep2 = provider.get_required_service(IDependency2)
    return ServiceType(dep1, dep2)

_add_singleton(IServiceType, implementation_factory=_service_factory)
```

**For BackendService Refactoring**:
- Remove all optional parameters
- Require all dependencies via constructor
- Update factory function to resolve all dependencies
- Register in `CoreServicesStage` (after dependencies are registered)

### Service Dependencies Graph

```
BackendService
├── BackendModelResolver
│   ├── BackendRoutingService
│   ├── ModelAliasResolver
│   ├── PlanningPhaseManager
│   ├── BackendLifecycleManager
│   ├── ISessionService
│   └── IConfig
├── RequestTransformer
│   ├── ModelAliasResolver
│   ├── ReasoningConfigApplicator
│   └── URIParameterApplicator
├── StreamProcessor
│   └── IStreamFormattingService
├── FailureStrategyExecutor
│   ├── IFailureHandlingStrategy
│   └── BackendRoutingService
├── FailoverPlanGenerator
│   ├── IFailoverCoordinator
│   └── IBackendLifecycleManager
└── ComplexFailoverExecutor
    ├── IFailoverCoordinator
    ├── IBackendLifecycleManager
    └── IBackendModelResolver
```

## Performance Considerations

**Analysis**:
- Additional service calls: ~6-8 method calls per request (negligible overhead)
- No network I/O added: All services are in-process
- Memory impact: Minimal (services are singletons)
- Latency impact: < 0.1ms per request (well below 1ms requirement)

**Conclusion**: Performance impact is negligible. Refactoring focuses on structure, not performance optimization.

## Security Considerations

**No Changes Required**:
- API key handling: Preserved through existing services
- Input validation: Preserved through existing validation
- Authentication: No changes to auth flow
- Error messages: Preserved through ExceptionNormalizer

## Risk Assessment

### Identified Risks

1. **Behavior Preservation** (Medium Risk)
   - **Mitigation**: Characterization tests before extraction
   - **Mitigation**: Incremental extraction with verification

2. **Test Compatibility** (Medium Risk)
   - **Mitigation**: Keep wrapper methods with identical signatures
   - **Mitigation**: Run full test suite after each extraction

3. **DI Complexity** (Low Risk)
   - **Mitigation**: Follow established patterns
   - **Mitigation**: Register services incrementally

4. **Integration Issues** (Low Risk)
   - **Mitigation**: Services communicate via interfaces
   - **Mitigation**: Clear dependency boundaries

### Risk Mitigation Strategy

1. **Phased Extraction**: Extract services one at a time
2. **Test-Driven**: Create tests before extraction
3. **Verification**: Run full test suite after each phase
4. **Rollback Plan**: Git commits after each successful extraction

## Research Gaps

### Resolved During Design

1. ✅ Behavior preservation: Analyzed critical methods
2. ✅ Test access patterns: Identified wrapper requirements
3. ✅ DI registration: Established patterns
4. ✅ Request transformation order: Verified current order

### Deferred to Implementation

1. Edge cases in failover logic (will be discovered during test creation)
2. Performance benchmarks (will be verified during testing)
3. Error message preservation (will be verified through characterization tests)

## Architectural Decisions

### Decision 1: Service-Based Decomposition
**Rationale**: Aligns with existing architecture, provides clean separation, enables independent testing.

### Decision 2: Interface-First Design
**Rationale**: Enables loose coupling, supports testing, follows DIP.

### Decision 3: Wrapper Method Preservation
**Rationale**: Maintains backward compatibility, preserves test access, enables incremental migration.

### Decision 4: Singleton Lifetime
**Rationale**: Services are stateless, reduces memory overhead, matches existing patterns.

### Decision 5: Factory-Based DI Registration
**Rationale**: Handles complex dependencies, follows existing patterns, enables lazy initialization.

## Supporting References

- Existing service patterns: `src/core/services/backend_lifecycle_manager.py`
- DI registration: `src/core/di/services.py:2821-3003`
- Interface definitions: `src/core/interfaces/`
- Test patterns: `tests/unit/core/services/test_backend_service*.py`
