# Follow-Up Refactoring Plan: DI Services LOC Compliance

## Executive Summary

This plan addresses the **P0 Critical** violations of Requirement 4.1 in the DI Services God-Object refactoring. Three files currently exceed the 600 LOC threshold:

| File | Current LOC | Target LOC | Excess | Strategy |
|------|-------------|------------|--------|----------|
| `streaming.py` | 955 | <600 | 355 (59%) | Split into 3 modules |
| `resilience.py` | 670 | <600 | 70 (12%) | Split into 2 modules |
| `core_processing.py` | 942 | <600 | 342 (57%) | Split into 3 modules |

**Estimated Effort**: 12-16 hours  
**Risk Level**: Low (structural refactoring only, no functional changes)

---

## Guiding Principles

### MUST Follow
1. **Preserve ALL public APIs** - No signature changes to existing `register()` functions
2. **Maintain registration order** - Preserve deterministic service registration sequence
3. **No functional changes** - Only structural file reorganization
4. **No test modifications** - Existing tests must pass without changes
5. **Zero behavioral impact** - Application must behave identically after refactoring

### Quality Gates
- **LOC**: Every file < 600 lines
- **CC**: No function > 50 cyclomatic complexity
- **Validation**: Update `analyze_complexity.py` from 1000 → 600 LOC threshold
- **Remove exclusions**: Delete `core_processing.py` from excluded_files list

---

## Refactoring Plan 1: `streaming.py` (955 → 3×~320 LOC)

### Current Structure Analysis
```
streaming.py (955 lines)
├── register()                                  [23-73]   # Main entry point
├── Session/Cancellation Services (470 lines)
│   ├── _register_end_of_session_service()      [585-667]
│   ├── _register_session_cancellation_*()      [669-711, 713-755, 757-852, 854-910]
│   └── _register_client_*()                    [757-852]
├── Streaming Pipeline Core (320 lines)
│   ├── _register_streaming_context_registry()  [75-95]
│   ├── _register_middleware_*()                [97-238, 240-293]
│   └── _register_stream_normalizer()           [295-418]
└── Response Processing (165 lines)
    ├── _register_stream_formatting_service()   [420-454]
    ├── _register_response_parser()             [456-477]
    └── _register_loop_detection_processor()    [549-583]
```

### Target Structure

#### File 1: `src/core/di/registrations/streaming/_session_lifecycle.py` (~470 LOC)
**Responsibility**: End-of-session, cancellation coordination, client termination

```python
"""
Session lifecycle and cancellation registrations.

Registers:
- EndOfSessionService / IEndOfSessionService
- SessionCancellationCoordinator / ISessionCancellationCoordinator
- ClientTerminationReasonMapper / IClientTerminationReasonMapper
- ClientEndOfSessionService / IClientEndOfSessionService
- SessionCancellationCleanupEosSubscriber
- ModelReplacementEosSubscriber
"""

def register_session_lifecycle_services(
    services: ServiceCollection, 
    app_config: AppConfig | None
) -> None:
    """Register all session lifecycle and cancellation services."""
    _register_end_of_session_service(services, app_config)
    _register_session_cancellation_coordinator(services, app_config)
    _register_client_termination_reason_mapper(services, app_config)
    _register_client_end_of_session_service(services, app_config)
    _register_session_cancellation_cleanup_subscriber(services, app_config)

# Move these private functions here (lines 585-955)
def _register_end_of_session_service(...) -> None: ...
def _register_session_cancellation_coordinator(...) -> None: ...
def _register_client_termination_reason_mapper(...) -> None: ...
def _register_client_end_of_session_service(...) -> None: ...
def _register_session_cancellation_cleanup_subscriber(...) -> None: ...
```

**Lines to move**: 585-955 (370 actual code lines)

---

#### File 2: `src/core/di/registrations/streaming/_pipeline.py` (~320 LOC)
**Responsibility**: Streaming pipeline, middleware, normalization

```python
"""
Streaming pipeline and middleware registrations.

Registers:
- StreamingContextRegistry
- MiddlewareApplicationManager (with all features)
- MiddlewareApplicationProcessor
- StreamNormalizer / IStreamNormalizer / IProcessingStreamNormalizer
- ToolCallReactorMiddleware (legacy)
- LoopDetectionProcessor
"""

def register_streaming_pipeline_services(
    services: ServiceCollection,
    app_config: AppConfig | None
) -> None:
    """Register all streaming pipeline services."""
    _register_streaming_context_registry(services)
    _register_middleware_application_manager(services)
    _register_middleware_application_processor(services)
    _register_stream_normalizer(services)
    _register_tool_call_reactor_middleware_legacy(services)
    _register_loop_detection_processor(services)

# Move these private functions here (lines 75-583)
def _register_streaming_context_registry(...) -> None: ...
def _register_middleware_application_manager(...) -> None: ...
def _register_middleware_application_processor(...) -> None: ...
def _register_stream_normalizer(...) -> None: ...
def _register_tool_call_reactor_middleware_legacy(...) -> None: ...
def _register_loop_detection_processor(...) -> None: ...
```

**Lines to move**: 75-583 (508 actual code lines, but excludes session lifecycle)

---

#### File 3: `src/core/di/registrations/streaming/_response.py` (~165 LOC)
**Responsibility**: Response formatting and parsing

```python
"""
Response processing service registrations.

Registers:
- StreamFormattingService / IStreamFormattingService
- ResponseParser / IResponseParser
"""

def register_response_processing_services(
    services: ServiceCollection
) -> None:
    """Register response processing services."""
    _register_stream_formatting_service(services)
    _register_response_parser(services)

# Move these private functions here
def _register_stream_formatting_service(...) -> None: ...
def _register_response_parser(...) -> None: ...
```

**Lines to move**: 420-477 (57 actual code lines)

---

#### File 4: `src/core/di/registrations/streaming.py` (NEW - ~55 LOC)
**Responsibility**: Public API facade - orchestrates sub-registrars

```python
"""
Streaming pipeline registrar.

Registers streaming response processors, middleware, and response handling services.
"""

from __future__ import annotations

import logging

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection

# Import sub-registrar functions
from src.core.di.registrations.streaming._session_lifecycle import (
    register_session_lifecycle_services,
)
from src.core.di.registrations.streaming._pipeline import (
    register_streaming_pipeline_services,
)
from src.core.di.registrations.streaming._response import (
    register_response_processing_services,
)

logger = logging.getLogger(__name__)


def register(services: ServiceCollection, app_config: AppConfig | None) -> None:
    """Register streaming pipeline services.

    This registrar handles:
    - EndOfSessionService and IEndOfSessionService
    - StreamingContextRegistry
    - MiddlewareApplicationManager
    - MiddlewareApplicationProcessor
    - StreamNormalizer and IProcessingStreamNormalizer
    - StreamFormattingService and IStreamFormattingService
    - Session cancellation and lifecycle services

    Args:
        services: The service collection to register into
        app_config: Optional application configuration
    """
    # CRITICAL: Preserve exact registration order for determinism
    
    # 1. Session lifecycle (must be before StreamNormalizer)
    register_session_lifecycle_services(services, app_config)
    
    # 2. Streaming pipeline core
    register_streaming_pipeline_services(services, app_config)
    
    # 3. Response processing
    register_response_processing_services(services)
```

**New file**: 55 lines

---

### Migration Steps for `streaming.py`

1. **Create directory structure**
   ```bash
   mkdir src/core/di/registrations/streaming
   touch src/core/di/registrations/streaming/__init__.py
   ```

2. **Extract `_session_lifecycle.py`**
   - Copy lines 585-955 to new file
   - Add imports (logging, typing, ServiceCollection, AppConfig, IServiceProvider)
   - Create `register_session_lifecycle_services()` orchestrator
   - Verify no external dependencies on moved functions

3. **Extract `_pipeline.py`**
   - Copy lines 75-583 to new file
   - Add imports
   - Create `register_streaming_pipeline_services()` orchestrator
   - Verify loop detection processor registration order

4. **Extract `_response.py`**
   - Copy lines 420-477 to new file
   - Add imports
   - Create `register_response_processing_services()` orchestrator

5. **Rewrite `streaming.py` as facade**
   - Keep module docstring and logger
   - Import sub-registrar orchestrators
   - Implement `register()` as delegation to sub-modules
   - **CRITICAL**: Preserve exact call order from original file

6. **Validate**
   ```bash
   # Run unit tests
   ./.venv/Scripts/python.exe -m pytest tests/unit/core/di/registrations/test_streaming_registrar.py -v
   
   # Run integration tests
   ./.venv/Scripts/python.exe -m pytest tests/integration/test_di_container_integrity.py -v
   
   # Verify LOC
   wc -l src/core/di/registrations/streaming.py
   wc -l src/core/di/registrations/streaming/_*.py
   ```

---

## Refactoring Plan 2: `resilience.py` (670 → 2×~335 LOC)

### Current Structure Analysis
```
resilience.py (670 lines)
├── register()                                  [45-67]   # Main entry point
├── Failure Handling & Coordination (180 lines)
│   ├── _register_failure_handling_strategy()   [69-106]
│   ├── _register_resilience_coordinator()      [108-149]
│   ├── _register_failover_services()           [151-191]
│   └── _register_failover_planner()            [193-248]
└── Backend Completion Flow (420 lines)
    └── _register_backend_completion_flow()     [250-670]
```

### Target Structure

#### File 1: `src/core/di/registrations/resilience/_coordination.py` (~200 LOC)
**Responsibility**: Resilience coordination, failover, failure handling

```python
"""
Resilience coordination and failover registrations.

Registers:
- RateLimitStateManager
- ResilienceCoordinator / IResilienceCoordinator
- FailoverService / FailoverCoordinator / IFailoverCoordinator
- FailoverPlanner / IFailoverPlanner
- Failure handling strategy (config-gated)
"""

def register_resilience_coordination_services(
    services: ServiceCollection,
    app_config: AppConfig | None
) -> None:
    """Register resilience coordination and failover services."""
    _register_resilience_coordinator(services)
    _register_failover_services(services)
    _register_failover_planner(services)
    _register_failure_handling_strategy(services, app_config)

# Move these private functions here (lines 69-248)
def _register_failure_handling_strategy(...) -> None: ...
def _register_resilience_coordinator(...) -> None: ...
def _register_failover_services(...) -> None: ...
def _register_failover_planner(...) -> None: ...
```

**Lines to move**: 69-248 (~180 lines)

---

#### File 2: `src/core/di/registrations/resilience/_backend_flow.py` (~420 LOC)
**Responsibility**: Backend completion flow orchestration and collaborators

```python
"""
Backend completion flow registrations.

Registers all BackendCompletionFlow collaborators:
- BackendAvailabilityChecker / IBackendAvailabilityChecker
- CompletionSessionResolver / ICompletionSessionResolver
- BackendRequestPreparer / IBackendRequestPreparer
- BackendManager / IBackendInvoker
- FailureRecoveryExecutor / IFailureRecoveryExecutor
- WireCaptureOrchestrator / IWireCaptureOrchestrator
- UsageAccountingOrchestrator / IUsageAccountingOrchestrator
- BackendCompletionFlow / IBackendCompletionFlow
- BackendCompletionFlowEosAdapter (optional)
"""

def register_backend_completion_flow_services(
    services: ServiceCollection
) -> None:
    """Register backend completion flow and all collaborators."""
    _register_backend_completion_flow(services)

# Move these private functions here (lines 20-43, 250-670)
def _create_eos_adapter(...) -> Any | None: ...
def _register_backend_completion_flow(...) -> None: ...
```

**Lines to move**: 20-43, 250-670 (~420 lines)

---

#### File 3: `src/core/di/registrations/resilience.py` (NEW - ~50 LOC)
**Responsibility**: Public API facade

```python
"""
Resilience registrar.

Registers failover, rate limiting, failure strategy, and backend completion flow services.
"""

from __future__ import annotations

import logging

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection

from src.core.di.registrations.resilience._coordination import (
    register_resilience_coordination_services,
)
from src.core.di.registrations.resilience._backend_flow import (
    register_backend_completion_flow_services,
)

logger = logging.getLogger(__name__)


def register(services: ServiceCollection, app_config: AppConfig | None) -> None:
    """Register resilience services.

    This registrar handles:
    - Failure handling strategies (optional, based on config)
    - Rate limiting (registered in infrastructure stage)
    - Failover coordination (optional)
    - Backend completion flow collaborators (registered in core)

    Note: Many resilience services are registered elsewhere (e.g., RateLimiter in
    InfrastructureStage, BackendCompletionFlow in core registrar). This registrar
    focuses on failure handling strategy registration when enabled.

    Args:
        services: The service collection to register into
        app_config: Optional application configuration
    """
    # CRITICAL: Preserve exact registration order
    register_resilience_coordination_services(services, app_config)
    register_backend_completion_flow_services(services)
```

**New file**: 50 lines

---

### Migration Steps for `resilience.py`

1. **Create directory structure**
   ```bash
   mkdir src/core/di/registrations/resilience
   touch src/core/di/registrations/resilience/__init__.py
   ```

2. **Extract `_coordination.py`**
   - Copy lines 69-248 to new file
   - Add imports
   - Create orchestrator function
   - Verify no circular dependencies

3. **Extract `_backend_flow.py`**
   - Copy lines 20-43 (helper) and 250-670 to new file
   - Add imports (extensive interface imports needed)
   - Keep `_create_eos_adapter()` as module-level helper
   - Verify all collaborator registrations are complete

4. **Rewrite `resilience.py` as facade**
   - Keep module docstring
   - Import sub-registrars
   - Implement `register()` as delegation
   - Preserve call order

5. **Validate**
   ```bash
   ./.venv/Scripts/python.exe -m pytest tests/unit/core/di/registrations/ -k resilience -v
   ./.venv/Scripts/python.exe -m pytest tests/integration/test_di_extracted_services.py -v
   wc -l src/core/di/registrations/resilience.py
   wc -l src/core/di/registrations/resilience/_*.py
   ```

---

## Refactoring Plan 3: `core_processing.py` (942 → 3×~315 LOC)

### Current Structure Analysis
```
core_processing.py (942 lines)
├── register_request_processing_orchestration() [22-752]  # Mega-function (51 CC!)
│   ├── Response Handlers                      [52-69]
│   ├── BackendProcessor                       [71-98]
│   ├── AgentResponseFormatter + ResponseMgr   [99-151]
│   ├── AngelServiceFactory                    [152-166]
│   ├── ResponseProcessor                      [167-213]
│   ├── BackendRequestManager (LARGE)          [214-310]
│   ├── StructuredOutputEnforcer               [311-338]
│   ├── ToolCallRetryCoordinator               [339-378]
│   ├── BackendNonStreamingResponseHandler     [379-442]
│   ├── BackendRequestPreparationService       [443-482]
│   ├── LoopDetectorFactory                    [483-510]
│   ├── AngelStreamVerifier                    [511-553]
│   ├── BackendStreamingResponseHandler        [554-612]
│   ├── LoopDetector                           [613-668]
│   └── RequestProcessor                       [669-752]
└── register_phase_components()                [754-942]
    ├── ArtifactService                        [776-782]
    ├── CommandHandler                         [783-820]
    ├── BackendPreparer                        [822-846]
    ├── SessionEnricher                        [848-868]
    ├── RequestSideEffects                     [870-896]
    ├── RequestTransformPipeline               [898-913]
    └── BackendExecutor                        [915-942]
```

### Target Structure

#### File 1: `src/core/di/registration_helpers/request_processing/_orchestration_core.py` (~320 LOC)
**Responsibility**: Core orchestration services (processors, managers)

```python
"""
Core request processing orchestration registrations.

Registers:
- Response handlers (non-streaming, streaming)
- BackendProcessor / IBackendProcessor
- AgentResponseFormatter / IAgentResponseFormatter
- ResponseManager / IResponseManager
- AngelServiceFactory / IAngelServiceFactory
- ResponseProcessor / IResponseProcessor
- BackendRequestManager / IBackendRequestManager
- RequestProcessor / IRequestProcessor
"""

def register_orchestration_core_services(services: ServiceCollection) -> None:
    """Register core orchestration services."""
    _register_response_handlers(services)
    _register_backend_processor(services)
    _register_response_manager(services)
    _register_angel_service_factory(services)
    _register_response_processor(services)
    _register_backend_request_manager(services)
    _register_request_processor(services)

# Extract and refactor sections from lines 52-310, 669-752
# Split mega-factory into smaller helper functions
```

**Lines to move**: 52-310, 669-752 (~390 lines, but needs CC reduction)

---

#### File 2: `src/core/di/registration_helpers/request_processing/_backend_components.py` (~330 LOC)
**Responsibility**: Backend request handling components

```python
"""
Backend request handling component registrations.

Registers:
- StructuredOutputEnforcer / IStructuredOutputEnforcer
- ToolCallRetryCoordinator / IToolCallRetryCoordinator
- BackendNonStreamingResponseHandler / INonStreamingBackendResponseHandler
- BackendRequestPreparationService / IBackendRequestPreparation
- LoopDetectorFactory / ILoopDetectorFactory
- AngelStreamVerifier / IAngelStreamVerifier
- BackendStreamingResponseHandler / IStreamingBackendResponseHandler
- LoopDetector / ILoopDetector (HybridLoopDetector)
"""

def register_backend_component_services(services: ServiceCollection) -> None:
    """Register backend request handling components."""
    _register_structured_output_enforcer(services)
    _register_tool_call_retry_coordinator(services)
    _register_backend_non_streaming_response_handler(services)
    _register_backend_request_preparation_service(services)
    _register_loop_detector_factory(services)
    _register_angel_stream_verifier(services)
    _register_backend_streaming_response_handler(services)
    _register_loop_detector(services)

# Move lines 311-668
```

**Lines to move**: 311-668 (~358 lines)

---

#### File 3: `src/core/di/registration_helpers/request_processing/_phase_components.py` (~190 LOC)
**Responsibility**: Request processor phase components

```python
"""
Request processor phase component registrations.

Registers internal RequestProcessor collaborators:
- ArtifactService
- CommandHandler / ICommandHandler
- BackendPreparer / IBackendPreparer
- SessionEnricher / ISessionEnricher
- RequestSideEffects / IRequestSideEffects
- RequestTransformPipeline / IRequestTransformPipeline
- BackendExecutor / IBackendExecutor
"""

def register_request_phase_components(services: ServiceCollection) -> None:
    """Register request processor phase components."""
    _register_artifact_service(services)
    _register_command_handler(services)
    _register_backend_preparer(services)
    _register_session_enricher(services)
    _register_request_side_effects(services)
    _register_request_transform_pipeline(services)
    _register_backend_executor(services)

# Move lines 776-942 (excluding function header)
```

**Lines to move**: 776-942 (~167 lines)

---

#### File 4: `src/core/di/registration_helpers/core_processing.py` (NEW - ~60 LOC)
**Responsibility**: Public API facade

```python
"""
Core request processing registration helper.

Registers:
- Request processing orchestration (RequestProcessor, BackendProcessor, BackendRequestManager)
- Phase components (SessionEnricher, RequestSideEffects, CommandHandler, BackendPreparer, RequestTransformPipeline, BackendExecutor)
"""

from __future__ import annotations

import logging

from src.core.di.container import ServiceCollection

from src.core.di.registration_helpers.request_processing._orchestration_core import (
    register_orchestration_core_services,
)
from src.core.di.registration_helpers.request_processing._backend_components import (
    register_backend_component_services,
)
from src.core.di.registration_helpers.request_processing._phase_components import (
    register_request_phase_components,
)

logger = logging.getLogger(__name__)


def register_request_processing_orchestration(services: ServiceCollection) -> None:
    """Register request processing orchestration services.
    
    CRITICAL: This function is called by core.py registrar and MUST preserve
    exact registration order for compatibility.
    """
    # Order matters - core services first, then components
    register_orchestration_core_services(services)
    register_backend_component_services(services)


def register_phase_components(services: ServiceCollection) -> None:
    """Register request processor phase components.
    
    CRITICAL: This function is called by core.py registrar and MUST preserve
    exact registration order for compatibility.
    """
    register_request_phase_components(services)
```

**New file**: 60 lines

---

### Migration Steps for `core_processing.py`

1. **Create directory structure**
   ```bash
   mkdir src/core/di/registration_helpers/request_processing
   touch src/core/di/registration_helpers/request_processing/__init__.py
   ```

2. **Extract `_orchestration_core.py`**
   - Copy lines 52-310, 669-752 to new file
   - **CRITICAL**: Refactor `_backend_request_manager_factory()` (currently 80 lines) into smaller helpers:
     ```python
     def _create_deduplication_service(provider, config):
         """Extract dedup service creation logic (15 lines)."""
         ...
     
     def _resolve_backend_request_manager_dependencies(provider):
         """Resolve all required dependencies (20 lines)."""
         ...
     
     def _backend_request_manager_factory(provider):
         """Main factory - now < 50 lines."""
         deps = _resolve_backend_request_manager_dependencies(provider)
         dedup = _create_deduplication_service(provider, deps.config)
         return BackendRequestManager(...)
     ```
   - Ensure each factory function < 50 CC
   - Create orchestrator function

3. **Extract `_backend_components.py`**
   - Copy lines 311-668 to new file
   - **CRITICAL**: Refactor `_loop_detector_factory()` (56 lines, complex):
     ```python
     def _get_loop_detection_config(config):
         """Extract config parsing logic (20 lines)."""
         ...
     
     def _create_hybrid_detector_config():
         """Create detector config (15 lines)."""
         ...
     
     def _loop_detector_factory(provider):
         """Main factory - simplified (< 25 lines)."""
         config = provider.get_service(AppConfig)
         if _should_use_noop_detector(config):
             return NoOpLoopDetector()
         short_cfg, long_cfg = _create_hybrid_detector_config()
         return HybridLoopDetector(short_detector_config=short_cfg, long_detector_config=long_cfg)
     ```
   - Create orchestrator function

4. **Extract `_phase_components.py`**
   - Copy lines 776-942 to new file (straightforward, already well-structured)
   - Create orchestrator function

5. **Rewrite `core_processing.py` as facade**
   - Keep original function signatures EXACTLY
   - Delegate to sub-modules
   - Preserve call order

6. **Fix `analyze_complexity.py`**
   ```python
   # Line 218: Change threshold
   MAX_LOC = 600  # Was 1000
   
   # Lines 457-461: Remove exclusion
   excluded_files = set()  # Remove core_processing.py
   ```

7. **Update `pyproject.toml`**
   ```toml
   # Remove C901 exclusion for core_processing.py
   # Before:
   # "src/core/di/registration_helpers/core_processing.py" = ["C901"]
   # After: (delete this line)
   ```

8. **Validate**
   ```bash
   # Lint and format
   ./.venv/Scripts/python.exe -m ruff check --fix src/core/di/registration_helpers/
   ./.venv/Scripts/python.exe -m black src/core/di/registration_helpers/
   
   # Check complexity
   ./.venv/Scripts/python.exe dev/scripts/analyze_complexity.py --validate-di-services-scope
   
   # Run tests
   ./.venv/Scripts/python.exe -m pytest tests/unit/core/di/ -v
   ./.venv/Scripts/python.exe -m pytest tests/integration/test_di_container_integrity.py -v
   
   # Verify LOC
   wc -l src/core/di/registration_helpers/core_processing.py
   wc -l src/core/di/registration_helpers/request_processing/_*.py
   ```

---

## Quality Gate Updates

### 1. Update `dev/scripts/analyze_complexity.py`

```python
# Line 218: Fix threshold (CRITICAL)
MAX_LOC = 600  # Changed from 1000

# Lines 457-461: Remove exclusion (CRITICAL)
excluded_files = set()  # Remove core_processing.py from excluded list
```

### 2. Update `pyproject.toml`

```toml
# Remove C901 exclusion for core_processing.py
# Find and delete this line:
# "src/core/di/registration_helpers/core_processing.py" = ["C901"]
```

### 3. Validation Command

```bash
# This MUST pass after refactoring
./.venv/Scripts/python.exe dev/scripts/analyze_complexity.py --validate-di-services-scope
```

Expected output:
```
====================================================================================================
DI SERVICES REFACTOR SCOPE VALIDATION
====================================================================================================

Checking 31 files against thresholds:
  - LOC per file: < 600
  - Max function CC: < 50

====================================================================================================
[PASS] VALIDATION PASSED: All 31 files meet thresholds
====================================================================================================
```

---

## Testing Strategy

### Test Execution Order

1. **Unit Tests** (after each file split)
   ```bash
   # Streaming
   ./.venv/Scripts/python.exe -m pytest tests/unit/core/di/registrations/test_streaming_registrar.py -v
   
   # Resilience
   ./.venv/Scripts/python.exe -m pytest tests/unit/core/di/registrations/ -k resilience -v
   
   # Core (no dedicated test, relies on integration)
   ./.venv/Scripts/python.exe -m pytest tests/unit/core/di/ -v
   ```

2. **Integration Tests** (after all splits)
   ```bash
   ./.venv/Scripts/python.exe -m pytest tests/integration/test_di_container_integrity.py -v
   ./.venv/Scripts/python.exe -m pytest tests/integration/test_di_extracted_services.py -v
   ```

3. **Regression Tests** (final validation)
   ```bash
   ./.venv/Scripts/python.exe -m pytest tests/regression/test_backend_service_di_regression.py -v
   ```

4. **Full DI Test Suite** (comprehensive)
   ```bash
   ./.venv/Scripts/python.exe -m pytest tests/unit/core/di/ tests/integration/ -v
   ```

### Test Success Criteria

- **Zero test modifications required**
- **100% existing tests pass**
- **No new test failures**
- **Same service resolution behavior** (verify with DI integrity tests)

---

## Implementation Checklist

### Phase 1: Prepare Infrastructure
- [ ] Create `streaming/` subdirectory and `__init__.py`
- [ ] Create `resilience/` subdirectory and `__init__.py`
- [ ] Create `request_processing/` subdirectory and `__init__.py`

### Phase 2: Refactor `streaming.py`
- [ ] Extract `_session_lifecycle.py` (470 LOC)
- [ ] Extract `_pipeline.py` (320 LOC)
- [ ] Extract `_response.py` (165 LOC)
- [ ] Rewrite `streaming.py` as facade (55 LOC)
- [ ] Run unit tests: `test_streaming_registrar.py`
- [ ] Verify LOC: `wc -l streaming.py` < 600
- [ ] Verify LOC: All sub-files < 600

### Phase 3: Refactor `resilience.py`
- [ ] Extract `_coordination.py` (200 LOC)
- [ ] Extract `_backend_flow.py` (420 LOC)
- [ ] Rewrite `resilience.py` as facade (50 LOC)
- [ ] Run unit tests: `test_*resilience*.py`
- [ ] Verify LOC: `wc -l resilience.py` < 600
- [ ] Verify LOC: All sub-files < 600

### Phase 4: Refactor `core_processing.py` (MOST COMPLEX)
- [ ] Extract `_orchestration_core.py` with CC refactoring (320 LOC)
  - [ ] Refactor `_backend_request_manager_factory()` to < 50 CC
  - [ ] Verify no function > 50 CC
- [ ] Extract `_backend_components.py` with CC refactoring (330 LOC)
  - [ ] Refactor `_loop_detector_factory()` to < 50 CC
  - [ ] Verify no function > 50 CC
- [ ] Extract `_phase_components.py` (190 LOC)
- [ ] Rewrite `core_processing.py` as facade (60 LOC)
- [ ] Run unit tests: `test_*di*.py`
- [ ] Verify LOC: `wc -l core_processing.py` < 600
- [ ] Verify LOC: All sub-files < 600
- [ ] Verify CC: No function > 50

### Phase 5: Update Quality Gates
- [ ] Update `analyze_complexity.py`: Change `MAX_LOC = 600`
- [ ] Update `analyze_complexity.py`: Remove `core_processing.py` from exclusions
- [ ] Update `pyproject.toml`: Remove C901 exclusion for `core_processing.py`
- [ ] Run validation: `--validate-di-services-scope` (MUST PASS)

### Phase 6: Final Validation
- [ ] Run full DI unit test suite (100% pass)
- [ ] Run integration tests (100% pass)
- [ ] Run regression tests (100% pass)
- [ ] Verify all files < 600 LOC
- [ ] Verify all functions < 50 CC
- [ ] Lint: `ruff check --fix src/core/di/`
- [ ] Format: `black src/core/di/`
- [ ] Type check: `mypy src/core/di/`

### Phase 7: Documentation
- [ ] Update `spec.json`: Set `implementation_status: "complete"` (for real this time)
- [ ] Document file splits in `tasks.md` completion notes
- [ ] Update this plan with "COMPLETED" status

---

## Risk Mitigation

### High-Risk Areas

1. **Registration Order Changes**
   - **Risk**: Sub-module imports change effective registration order
   - **Mitigation**: Explicitly document and preserve call order in facade `register()` functions
   - **Validation**: DI determinism tests

2. **Circular Import Introduction**
   - **Risk**: Sub-modules import each other, creating cycles
   - **Mitigation**: Use local imports inside factories, enforce one-way dependencies
   - **Validation**: `python -c "import src.core.di.registrations.streaming"` must succeed

3. **CC Refactoring Breaking Logic**
   - **Risk**: Splitting complex factories changes behavior
   - **Mitigation**: Extract pure helper functions only, preserve exact factory logic
   - **Validation**: Integration tests must pass without modification

### Rollback Plan

If any phase fails validation:

1. **Revert last commit**: `git revert HEAD`
2. **Review test failures**: Identify broken assumptions
3. **Re-attempt with smaller scope**: Split one file at a time, validate before proceeding

---

## Success Criteria

### Quantitative Metrics
- ✅ All DI files < 600 LOC
- ✅ All functions < 50 CC
- ✅ Quality gate validation passes with 600 LOC threshold
- ✅ Zero test modifications required
- ✅ 100% test pass rate maintained

### Qualitative Metrics
- ✅ Code is more navigable (smaller files)
- ✅ Responsibilities are clearer (focused modules)
- ✅ Complexity violations eliminated (no C901 exclusions)
- ✅ Spec requirements 4.1 and 4.2 fully satisfied

---

## Estimated Timeline

| Phase | Task | Estimated Time |
|-------|------|----------------|
| 1 | Infrastructure setup | 0.5h |
| 2 | Refactor `streaming.py` | 3h |
| 3 | Refactor `resilience.py` | 2h |
| 4 | Refactor `core_processing.py` (with CC fixes) | 5h |
| 5 | Quality gate updates | 0.5h |
| 6 | Final validation | 1h |
| 7 | Documentation | 1h |
| **Total** | | **13h** |

**Buffer**: +3h for unexpected issues = **16h total**

---

## Completion Definition

This refactoring is **COMPLETE** when:

1. ✅ `streaming.py` is < 600 LOC
2. ✅ `resilience.py` is < 600 LOC
3. ✅ `core_processing.py` is < 600 LOC
4. ✅ All sub-files are < 600 LOC
5. ✅ All functions are < 50 CC
6. ✅ `MAX_LOC = 600` in `analyze_complexity.py`
7. ✅ `core_processing.py` removed from exclusions
8. ✅ `--validate-di-services-scope` passes
9. ✅ All DI tests pass (unit + integration + regression)
10. ✅ No test modifications required
11. ✅ Spec status updated to `implementation_status: "complete"`

**Only then** can the spec be legitimately marked as finished.
