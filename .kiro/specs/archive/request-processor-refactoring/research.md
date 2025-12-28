# Research and Discovery: Request Processor Refactoring

## Discovery Date
2025-12-15

## Feature Classification
**Type**: Brownfield Refactoring (Extension of existing system)
**Complexity**: High (architectural refactoring with multiple components)
**Discovery Approach**: Light Discovery (existing patterns, integration analysis)

## Current Architecture Analysis

### Request Processing Flow (Current)
1. **Session Resolution** (lines 84-85)
   - Resolve session ID from context
   - Load session from ISessionManager

2. **Session State Updates** (lines 87-113)
   - Update session agent if different
   - Client OS detection (if not detected)
   - VTC detection (if not enabled)

3. **Streaming Tool Registry Update** (best-effort)
   - Extract allowed tool names from the inbound request (when present)
   - Store allowed tool names in the global streaming context registry for the session

4. **Project Directory Resolution** (lines 178-199)
   - Auto-detect project directory if needed
   - Uses ProjectDirectoryResolutionService

5. **Memory Context Injection** (lines 201-210)
   - Inject memory context via ContextInjectionMiddleware
   - Captures user request via MemoryCaptureMiddleware

6. **Command Processing** (lines 227-244)
   - Process commands via ICommandProcessor
   - Expand truncated tool outputs
   - Handle command-only path

7. **Model Replacement** (conditional)
   - Apply model replacement only when a replacement service is available to RequestProcessor
   - Note: In staged initialization wiring, the replacement service is currently not injected into RequestProcessor, so this code path is typically inactive.

8. **Context Window Enforcement** (lines 314-529)
   - Enforce per-model token limits
   - Validate input tokens and total tokens
   - Apply CLI context window override

9. **Request Redaction** (lines 530-675)
   - Apply RedactionMiddleware
   - Redact API keys and proxy commands
   - Session-level caching for performance

10. **Edit Precision Tuning** (lines 676-868)
   - Apply EditPrecisionTuningMiddleware
   - Adjust temperature and top_p parameters
   - Handle hybrid reasoning overrides

11. **Tool Access Control** (lines 887-989)
    - Filter tool definitions via ToolAccessPolicyService
    - Update tool_choice if referenced tool is filtered

12. **Backend Call** (lines 1002-1036)
    - Process backend request via IBackendRequestManager
    - Update session history
    - Update session fingerprint

### Middleware Execution Order (Current)
**Critical Finding**: Middleware execution order is hardcoded and must be preserved:
1. RedactionMiddleware (first - removes sensitive data)
2. EditPrecisionTuningMiddleware (second - adjusts parameters)
3. Tool Access Control (third - filters tools after parameter adjustment)

**Dependencies**:
- Redaction must run before Edit Precision (to avoid redacting precision-tuned parameters)
- Edit Precision must run before Tool Access Control (tool filtering may depend on parameters)
- Tool Access Control must run last (needs final tool list after all modifications)

### Existing Patterns

**Service Registration Pattern**:
- Services registered in `src/core/app/stages/processor.py`
- Factory pattern used for complex initialization
- Singleton lifetime for most services
- Interface binding via `add_singleton_factory`

**Error Handling Pattern**:
- Fail-open for middleware and best-effort enrichments (log and continue)
- Fail-fast for validation (raise InvalidRequestError)
- Structured exceptions via LLMProxyError hierarchy
- Error propagation through async chains

**Interface Pattern**:
- `I*` naming convention for interfaces
- Interfaces in `src/core/interfaces/`
- Abstract base classes with `@abstractmethod`
- Type hints required (no `any` types)

**Dependency Injection Pattern**:
- `ServiceCollection` container
- `IServiceProvider` for service resolution
- Factory functions for complex wiring
- Optional dependencies via `get_service()` (returns None if not found)

### Component Boundaries

**Existing Handler Components** (to be reused):
- `ICommandProcessor` - Command processing
- `ISessionManager` - Session management
- `IBackendRequestManager` - Backend request preparation
- `IResponseManager` - Command result response handling (command-only flows)
- `IModelReplacementService` - Model replacement
- `ProjectDirectoryResolutionService` - Project directory resolution
- `ToolAccessPolicyService` - Tool access control

**Existing Middleware** (to be integrated):
- `RedactionMiddleware` (IRequestMiddleware)
- `EditPrecisionTuningMiddleware` (IRequestMiddleware)
- `MemoryCaptureMiddleware` - Memory capture
- `ContextInjectionMiddleware` - Context injection

**Utility Functions** (to be extracted):
- `detect_vtc_client()` in `src/core/services/vtc_detection.py`
- Client OS detection logic (embedded in RequestProcessor)

## Tooling Notes

### Complexity Tooling Compatibility

The refactoring goals reference cyclomatic complexity and maintainability index metrics. In the current repository configuration, the installed `radon`/`xenon` tooling may fail when parsing `pyproject.toml` due to config interpolation issues. The implementation tasks should include selecting a repeatable measurement approach (tool version/configuration) that is runnable in this repo and can be used to validate complexity reduction over time.

## Technology Alignment

### No New Dependencies Required
- All required patterns exist in codebase
- Middleware interface (`IRequestMiddleware`) already defined
- DI container supports factory pattern
- Async/await patterns established

### Existing Utilities to Leverage
- Token counting: `src/core/utils/token_count.py`
- Model parsing: `src/core/domain/model_utils.py`
- Exception hierarchy: `src/core/common/exceptions.py`
- Logging: Standard Python logging with structlog

## Integration Points

### DI Container Integration
- New components registered in `ProcessorStage` (`src/core/app/stages/processor.py`)
- Factory pattern for complex initialization
- Singleton lifetime for stateless handlers
- Interface bindings for testability

### Stage Dependencies
- RequestProcessor registered in ProcessorStage
- Depends on: CommandStage, BackendStage
- Must be available before ControllerStage

### Error Propagation
- InvalidRequestError for validation failures (HTTP 400/422)
- BackendError for backend failures (HTTP 502)
- RateLimitExceededError for rate limits (HTTP 429)
- All errors extend LLMProxyError base class

## Performance Considerations

### Current Performance Characteristics
- RequestProcessor.process_request() is synchronous in structure but async
- Middleware application is sequential (no parallelization)
- Token counting may be expensive for large requests
- Artifact processing involves file I/O

### Refactoring Impact
- Additional method calls: ~8-10 per request
- Abstraction overhead: Minimal (Python method calls are fast)
- Memory overhead: Negligible (components are stateless)
- Expected impact: < 5ms overhead per request

## Testing Strategy

### Existing Test Coverage
- `tests/unit/core/test_request_processor.py` - Main unit tests
- `tests/unit/core/services/test_request_processor_os_detection.py` - OS detection
- `tests/unit/services/test_request_processor_truncated_outputs.py` - Artifacts
- `tests/unit/services/test_request_processor_tool_filtering.py` - Tool filtering
- `tests/property/test_request_processor_integration.py` - Integration tests

### Test Migration Approach
1. Extract component logic to new handler
2. Create component-level unit tests
3. Update RequestProcessor tests to mock handlers
4. Preserve integration tests unchanged
5. Add handler-specific unit tests

## Security Considerations

### Current Security Measures
- API key redaction via RedactionMiddleware
- Command filtering via ProxyCommandFilter
- Tool access control via ToolAccessPolicyService
- Input validation via InvalidRequestError

### Refactoring Impact
- No security degradation expected
- Redaction middleware must remain first in chain
- Tool access control must remain last in chain
- All security checks must be preserved

## Unknowns and Risks

### Research Items Resolved
1. ✅ Middleware execution order: Documented dependencies above
2. ✅ Error handling strategy: Fail-open for middleware, fail-fast for validation
3. ✅ DI registration pattern: Factory pattern with singleton lifetime
4. ✅ Component boundaries: Clear separation identified

### Remaining Risks
1. **Behavior Preservation**: Must ensure exact behavior preservation during extraction
2. **Test Migration**: Existing tests may need updates to mock new components
3. **Performance**: Additional abstraction layers may add overhead
4. **Integration**: Component coordination must preserve exact execution order

## Architectural Decisions

### Decision 1: Component Extraction Strategy
**Decision**: Extract all handler components as new services
**Rationale**: RequestProcessor is already a God Object; extension would worsen it
**Impact**: 8-10 new service files, improved testability

### Decision 2: Request Transformation Pipeline
**Decision**: Implement a dedicated transformation pipeline component with fixed ordering
**Rationale**: Preserves current ordering and fail-open behavior while isolating cross-cutting concerns
**Impact**: New TransformPipeline component (redaction, edit precision, tool filtering)

### Decision 3: Interface Design
**Decision**: Create focused interfaces for each handler
**Rationale**: Improves testability and follows Interface Segregation Principle
**Impact**: 6-8 new interface files

### Decision 4: Backward Compatibility
**Decision**: Preserve IRequestProcessor interface unchanged
**Rationale**: Maintains compatibility with existing code and tests
**Impact**: RequestProcessor becomes thin orchestrator

## Supporting References

### Code Locations
- RequestProcessor: `src/core/services/request_processor_service.py`
- Interfaces: `src/core/interfaces/request_processor_interface.py`
- DI Registration: `src/core/app/stages/processor.py`
- Exception Hierarchy: `src/core/common/exceptions.py`

### Related Patterns
- BackendService refactoring: Similar God Object refactoring (see `backend-service-refactoring` spec)
- Middleware pattern: Existing IRequestMiddleware interface
- Handler pattern: Similar to command handlers in `src/core/commands/handlers/`
