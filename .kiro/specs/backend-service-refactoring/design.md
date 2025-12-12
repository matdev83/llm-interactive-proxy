# Design Document: BackendService Refactoring

## Overview

This design document describes the refactoring of the `BackendService` class from a monolithic "God Object" into a set of focused, single-responsibility services. The current `BackendService` (~3200 lines) handles too many concerns including stream formatting, usage tracking, model aliasing, URI parameter resolution, reasoning configuration, planning phase management, backend lifecycle, and exception normalization.

The refactoring follows SOLID principles, particularly:
- **SRP**: Each new service has one clear responsibility
- **OCP**: Services are open for extension via interfaces
- **LSP**: All implementations are substitutable for their interfaces
- **ISP**: Interfaces are focused and minimal
- **DIP**: High-level modules depend on abstractions

## Invariants and Gotchas to Preserve

These are concrete, observable behaviors from the current `BackendService` implementation and its tests. Treat them as regression targets while extracting services.

### Streaming / SSE

- `_stream_as_sse_bytes` accepts an async iterator yielding `ProcessedResponse`, `dict`, `str`, or `bytes`, and always yields SSE‑encoded `bytes`.
- Content that already begins with `data:` (bytes or str) is passed through unchanged.
- Raw `[DONE]` / `["DONE"]` is normalized to exactly `b"data: [DONE]\n\n"`. If a stream ends without any done marker, one is appended.
- `StopChunkWithUsage` is special‑cased: serialize via `StreamingContent(..., usage=...)` so usage is top‑level, then mark done.
- `_chunk_signals_done` treats completion as signaled by any of: raw/sse `[DONE]`, `metadata.finish_reason`, `content.metadata.finish_reason`, or OpenAI‑style `choices[*].finish_reason` / empty deltas with finish_reason.

### Usage Tracking

- `_wrap_stream_for_usage` is a no‑op when `IUsageTrackingService` is not injected or both record IDs are `None`.
- TTFT is measured on the first *valid* completion token per `_is_valid_completion_token`.
- Final usage is sourced, in priority order: `StopChunkWithUsage.usage`, `dict["usage"]`, then `ProcessedResponse.usage`.
- On completion, wrapper records TTFT, total duration, and streaming TPS to both PTB and CTP records when present.

### Model Aliases

- Aliases are read from `AppConfig.model_aliases`; if missing or non‑iterable (e.g., mocks), return the original model.
- Matching uses `re.match` semantics (start‑anchored unless user‑anchored explicitly); first match wins.
- Replacements use `match.expand` to support capture groups.
- Invalid regex patterns never throw; log at WARNING and skip.

### URI Parameters

- `_apply_uri_parameters` early‑returns if `uri_params` is empty.
- Sources and precedence: session overrides > URI params > request/extra_body fields (headers) > backend/app config.
- Type coercion rules: `temperature` / `top_p` → float, `top_k` → int (reject non‑integer floats), `reasoning_effort` → str.
- Edit‑precision mode (`_edit_precision_mode` in `extra_body`) promotes one‑shot request fields into session‑level precedence.

### Reasoning Config

- If `session.get_reasoning_mode()` returns `None`, request is unchanged.
- Numeric overrides respect edit‑precision constraints.
- Prompt prefix/suffix is applied to user text in both string and multipart message content without altering non‑text parts.

### Planning Phase

- Enabled only when `session.state.planning_phase_config.enabled` and `strong_model` are set.
- When max turns or file writes are reached, restore original backend/model and clear original‑route fields.
- Original route is persisted only once per planning phase.

### Backend Lifecycle

- Permanently disabled backends are tracked by backend type; attempts to create them raise `BackendError`.
- Cache key rules:
  - With `session_id`: `f"{backend_type}:{session_id}"`.
  - Special case `gemini-cli-acp` without session_id: `f"{backend_type}:default"`.
  - Otherwise: `backend_type`.
- Per‑session cache is LRU via `OrderedDict`; eviction shuts down backends.
- `_discard_backend` disables globally and removes both global and per‑session variants.

### Exception Normalization

- HTTP 429 → `RateLimitExceededError` with message extracted from nested `detail` blocks when possible.
- Preserve retry‑after headers and compute `reset_at`.
- HTTP 4xx → `InvalidRequestError`; HTTP 5xx/other → `BackendError`.
- Normalizer never raises.

## Service Boundaries and State Ownership

| Service | Extracted logic | Owns state | Injected dependencies | Notes |
| --- | --- | --- | --- | --- |
| StreamFormattingService | `_stream_as_sse_bytes`, `_format_as_sse`, `_chunk_signals_done`, `_is_valid_completion_token` | None | None | Must be usable from static wrappers. |
| UsageTrackingWrapper | `_wrap_stream_for_usage` | None | `IUsageTrackingService`, `IStreamFormattingService` | Uses SFS for token validation. |
| ModelAliasResolver | `_apply_model_aliases` | None | `IConfig` (AppConfig) | Read‑only access to `model_aliases`. |
| URIParameterApplicator | `_apply_uri_parameters` | None | `IConfig` (AppConfig), `ParameterResolutionService`, `URIParameterValidator` | Existing services may be instantiated internally if not DI‑registered. |
| ReasoningConfigApplicator | `_apply_reasoning_config` | None | None | Keep current mock‑tolerant logic. |
| PlanningPhaseManager | `_apply_planning_phase_if_needed`, `_update_planning_phase_counters`, `_restore_planning_phase_route`, `_count_file_writes_in_response` | None | `ISessionService` | Pure session‑state mutations. |
| BackendLifecycleManager | `_get_or_create_backend`, `_shutdown_backend`, `_discard_backend`, cache helpers | `_backends`, `_per_session_backends`, `_disabled_backends`, `_backend_configs`, per‑session limit | `BackendFactory`, optional `IBackendConfigProvider`, `IConfig` | Must also support sync `get_backend` used in tests. |
| ExceptionNormalizer | `_normalize_provider_exception` | None | None | Pure translation, never throws. |

## Interface Style Conventions

- Default to `abc.ABC` + `@abstractmethod` for new interfaces under `src/core/interfaces/`. This matches most core service interfaces and provides explicit DI tokens.
- Use `Protocol` only for purely structural typing where no runtime identity or DI registration is required.
- Keep method signatures behavior‑compatible with existing helpers (avoid widening/renaming args).
- Public interface methods must have short, behavioral docstrings; implementation details belong in services.

## Architecture

The refactored architecture decomposes `BackendService` into a coordinator that delegates to specialized services:

```mermaid
graph TB
    subgraph "Public API (Unchanged)"
        IBS[IBackendService]
    end
    
    subgraph "Coordinator"
        BS[BackendService]
    end
    
    subgraph "Extracted Services"
        SFS[IStreamFormattingService]
        UTW[IUsageTrackingWrapper]
        MAR[IModelAliasResolver]
        UPA[IURIParameterApplicator]
        RCA[IReasoningConfigApplicator]
        PPM[IPlanningPhaseManager]
        BLM[IBackendLifecycleManager]
        EN[IExceptionNormalizer]
    end
    
    subgraph "Existing Dependencies"
        BF[BackendFactory]
        RL[IRateLimiter]
        SS[ISessionService]
        WC[IWireCapture]
        FC[IFailoverCoordinator]
        RC[IResilienceCoordinator]
        FHS[IFailureHandlingStrategy]
        UTS[IUsageTrackingService]
    end
    
    IBS --> BS
    BS --> SFS
    BS --> UTW
    BS --> MAR
    BS --> UPA
    BS --> RCA
    BS --> PPM
    BS --> BLM
    BS --> EN
    BS --> BF
    BS --> RL
    BS --> SS
    BS --> WC
    BS --> FC
    BS --> RC
    BS --> FHS
    UTW --> UTS
    UTW --> SFS
    PPM --> SS
```

## Components and Interfaces

### 1. IStreamFormattingService

**Location**: `src/core/interfaces/stream_formatting_interface.py`
**Implementation**: `src/core/services/stream_formatting_service.py`

**Responsibility**: Convert domain chunks to SSE-encoded bytes and validate completion tokens.

```python
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

class IStreamFormattingService(ABC):
    @abstractmethod
    def stream_as_sse_bytes(self, stream: AsyncIterator[Any]) -> AsyncIterator[bytes]:
        """Convert domain chunks to SSE-encoded bytes."""
    
    @abstractmethod
    def is_valid_completion_token(self, chunk: Any) -> bool:
        """Check if chunk contains valid completion content."""
    
    @abstractmethod
    def format_chunk_as_sse(self, content: Any) -> bytes:
        """Format a single chunk as SSE bytes."""
    
    @abstractmethod
    def chunk_signals_done(self, content: Any, metadata: dict[str, Any] | None) -> bool:
        """Check if chunk signals stream completion."""
```

### 2. IUsageTrackingWrapper

**Location**: `src/core/interfaces/usage_tracking_wrapper_interface.py`
**Implementation**: `src/core/services/usage_tracking_wrapper.py`

**Responsibility**: Wrap streams to track usage metrics (TTFT, TPS, completion tokens).

```python
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

class IUsageTrackingWrapper(ABC):
    @abstractmethod
    def wrap_stream_for_usage(
        self,
        stream: AsyncIterator[Any],
        ctp_record_id: str | None,
        ptb_record_id: str | None,
        start_time: float,
    ) -> AsyncIterator[Any]:
        """Wrap stream to track usage metrics."""
```

### 3. IModelAliasResolver

**Location**: `src/core/interfaces/model_alias_resolver_interface.py`
**Implementation**: `src/core/services/model_alias_resolver.py`

**Responsibility**: Apply regex-based model name transformations.

```python
from abc import ABC, abstractmethod
from typing import Any

class IModelAliasResolver(ABC):
    @abstractmethod
    def resolve(self, model: str) -> str:
        """Apply configured model aliases and return resolved model name."""
```

### 4. IURIParameterApplicator

**Location**: `src/core/interfaces/uri_parameter_applicator_interface.py`
**Implementation**: `src/core/services/uri_parameter_applicator.py`

**Responsibility**: Resolve and apply URI parameters with proper precedence.

```python
from abc import ABC, abstractmethod
from typing import Any
from src.core.domain.chat import ChatRequest

class IURIParameterApplicator(ABC):
    @abstractmethod
    def apply(
        self,
        request: ChatRequest,
        uri_params: dict[str, Any],
        backend_type: str,
        session: Any | None = None,
    ) -> ChatRequest:
        """Apply URI parameters to request with precedence resolution."""
```

### 5. IReasoningConfigApplicator

**Location**: `src/core/interfaces/reasoning_config_applicator_interface.py`
**Implementation**: `src/core/services/reasoning_config_applicator.py`

**Responsibility**: Apply reasoning configuration from session to requests.

```python
from abc import ABC, abstractmethod
from typing import Any
from src.core.domain.chat import ChatRequest

class IReasoningConfigApplicator(ABC):
    @abstractmethod
    def apply(self, request: ChatRequest, session: Any) -> ChatRequest:
        """Apply reasoning configuration from session to request."""
```

### 6. IPlanningPhaseManager

**Location**: `src/core/interfaces/planning_phase_manager_interface.py`
**Implementation**: `src/core/services/planning_phase_manager.py`

**Responsibility**: Manage planning phase model overrides and counter tracking.

```python
from abc import ABC, abstractmethod
from typing import Any

class IPlanningPhaseManager(ABC):
    @abstractmethod
    async def apply_if_needed(
        self, session: Any, default_backend: str
    ) -> None:
        """Apply planning phase model override if conditions are met."""
    
    @abstractmethod
    async def update_counters(self, session_id: str, response: Any) -> None:
        """Update planning phase counters after completion."""
    
    @abstractmethod
    def count_file_writes(self, response: Any) -> int:
        """Count file write tool calls in response."""
```

### 7. IBackendLifecycleManager

**Location**: `src/core/interfaces/backend_lifecycle_manager_interface.py`
**Implementation**: `src/core/services/backend_lifecycle_manager.py`

**Responsibility**: Manage backend instance creation, caching, and shutdown.

```python
from abc import ABC, abstractmethod
from typing import Any
from src.connectors.base import LLMBackend

class IBackendLifecycleManager(ABC):
    @abstractmethod
    async def get_or_create(
        self, backend_type: str, session_id: str | None = None
    ) -> LLMBackend:
        """Get existing backend or create new one."""
    
    @abstractmethod
    async def shutdown(self, backend: LLMBackend) -> None:
        """Shutdown backend with proper cleanup."""
    
    @abstractmethod
    def discard(
        self, backend_type: str, session_id: str | None, reason: str
    ) -> None:
        """Discard and disable a backend instance."""
    
    @abstractmethod
    def is_disabled(self, backend_type: str) -> bool:
        """Check if backend is permanently disabled."""
    
    @abstractmethod
    def get_active_backends(self) -> dict[str, LLMBackend]:
        """Get all active backend instances."""
```

### 8. IExceptionNormalizer

**Location**: `src/core/interfaces/exception_normalizer_interface.py`
**Implementation**: `src/core/services/exception_normalizer.py`

**Responsibility**: Translate provider exceptions to domain-specific errors.

```python
from abc import ABC, abstractmethod

class IExceptionNormalizer(ABC):
    @abstractmethod
    def normalize(self, exc: Exception, backend_type: str) -> Exception:
        """Translate provider exception to domain error."""
```

## Data Models

No new data models are required. The refactoring uses existing domain models:

- `ChatRequest`: Request payload for chat completions
- `ResponseEnvelope`: Non-streaming response wrapper
- `StreamingResponseEnvelope`: Streaming response wrapper
- `ProcessedResponse`: Processed chunk from response processor
- `BackendError`, `RateLimitExceededError`, `InvalidRequestError`: Domain exceptions

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: SSE Format Consistency
*For any* valid domain chunk (ProcessedResponse, dict, str, or bytes), `format_chunk_as_sse` SHALL: (a) pass through content already framed as SSE (`data:` prefix), (b) normalize raw `[DONE]` / `["DONE"]` to `data: [DONE]\n\n`, and (c) otherwise return bytes framed as `data: {payload}\n\n`.
**Validates: Requirements 5.1, 5.3**

### Property 2: Done Marker Detection
*For any* chunk containing raw/sse `[DONE]` / `["DONE"]`, `metadata.finish_reason`, `content.metadata.finish_reason`, or `choices[*].finish_reason`, the formatter SHALL detect it as signaling completion and emit exactly one done marker for the stream.
**Validates: Requirements 5.4**

### Property 3: Valid Token Identification
*For any* chunk, the token validator SHALL return true only if the chunk contains actual content (not empty, not [DONE], not keepalive).
**Validates: Requirements 5.2**

### Property 4: Usage Accumulation
*For any* stream with usage data in chunks, the usage wrapper SHALL accumulate and report the final usage on completion.
**Validates: Requirements 6.2, 6.3**

### Property 5: Model Alias Round-Trip
*For any* model name and configured aliases, the resolver SHALL apply at most one rewrite using the first matching `re.match` rule and `match.expand` replacement semantics.
**Validates: Requirements 7.1, 7.2**

### Property 6: Alias Graceful Degradation
*For any* invalid regex pattern in aliases, the resolver SHALL skip it, log at WARNING, and return the original model name when no valid match exists.
**Validates: Requirements 7.3, 7.4**

### Property 7: Parameter Precedence
*For any* conflicting parameter values from different sources, the applicator SHALL apply session > URI > headers > config precedence.
**Validates: Requirements 8.1, 8.2**

### Property 8: Parameter Type Coercion
*For any* parameter value, the applicator SHALL coerce to the correct type (float for temperature/top_p, int for top_k, str for reasoning_effort).
**Validates: Requirements 8.3**

### Property 9: Reasoning Config Application
*For any* session with reasoning configuration, applying it to a request SHALL update the request with the configured parameters.
**Validates: Requirements 9.1, 9.2**

### Property 10: Planning Phase Transition
*For any* session in planning phase that exceeds max_turns or max_file_writes, the manager SHALL restore the original route.
**Validates: Requirements 10.1, 10.3**

### Property 11: File Write Counting
*For any* response with tool calls, the manager SHALL correctly count file write operations.
**Validates: Requirements 10.4**

### Property 12: Backend Cache LRU
*For any* sequence of backend requests exceeding the cache limit, the lifecycle manager SHALL evict the least recently used backend.
**Validates: Requirements 11.1**

### Property 13: Exception Translation
*For any* HTTPException with status 429, the normalizer SHALL produce a RateLimitExceededError with preserved retry-after.
**Validates: Requirements 12.1, 12.4**

### Property 14: API Signature Preservation
*For any* call to BackendService public methods, the signature and return type SHALL match the IBackendService interface.
**Validates: Requirements 3.1-3.6**

## Error Handling

Each extracted service follows consistent error handling:

1. **StreamFormattingService**: Catches encoding errors, logs at DEBUG, returns safe fallback bytes
2. **UsageTrackingWrapper**: Catches tracking errors in finally block, logs at ERROR, does not propagate
3. **ModelAliasResolver**: Catches regex errors, logs at WARNING, returns original model
4. **URIParameterApplicator**: Catches validation/resolution errors, logs at ERROR, returns original request
5. **ReasoningConfigApplicator**: Catches config errors, logs at DEBUG, returns original request
6. **PlanningPhaseManager**: Catches session errors, logs at WARNING, continues without planning phase
7. **BackendLifecycleManager**: Catches shutdown errors, logs at EXCEPTION level, continues cleanup
8. **ExceptionNormalizer**: Never throws, always returns a normalized exception

## Testing Strategy

### Unit Testing

Each extracted service will have dedicated unit tests:

- `tests/unit/core/services/test_stream_formatting_service.py`
- `tests/unit/core/services/test_usage_tracking_wrapper.py`
- `tests/unit/core/services/test_model_alias_resolver.py`
- `tests/unit/core/services/test_uri_parameter_applicator.py`
- `tests/unit/core/services/test_reasoning_config_applicator.py`
- `tests/unit/core/services/test_planning_phase_manager.py`
- `tests/unit/core/services/test_backend_lifecycle_manager.py`
- `tests/unit/core/services/test_exception_normalizer.py`

### Property-Based Testing

Property-based tests will use **Hypothesis** (already used in the project) to verify correctness properties:

- Each property test will run a minimum of 100 iterations
- Tests will be tagged with the format: `**Feature: backend-service-refactoring, Property {number}: {property_text}**`
- Generators will be designed to produce valid domain objects

### Regression Testing

All existing tests in `tests/unit/core/services/test_backend_service*.py` must pass without modification after refactoring.

## Implementation Notes

### Refactored BackendService Constructor

```python
class BackendService(IBackendService):
    def __init__(
        self,
        factory: BackendFactory,
        rate_limiter: IRateLimiter,
        config: IConfig,
        session_service: ISessionService,
        app_state: IApplicationState,
        # Existing optional dependencies
        backend_config_provider: IBackendConfigProvider | None = None,
        failover_coordinator: IFailoverCoordinator | None = None,
        failover_strategy: IFailoverStrategy | None = None,
        wire_capture: IWireCapture | None = None,
        routing_service: BackendRoutingService | None = None,
        resilience_coordinator: IResilienceCoordinator | None = None,
        failure_handling_strategy: IFailureHandlingStrategy | None = None,
        usage_tracking_service: IUsageTrackingService | None = None,
        # NEW extracted service dependencies
        stream_formatting_service: IStreamFormattingService | None = None,
        usage_tracking_wrapper: IUsageTrackingWrapper | None = None,
        model_alias_resolver: IModelAliasResolver | None = None,
        uri_parameter_applicator: IURIParameterApplicator | None = None,
        reasoning_config_applicator: IReasoningConfigApplicator | None = None,
        planning_phase_manager: IPlanningPhaseManager | None = None,
        backend_lifecycle_manager: IBackendLifecycleManager | None = None,
        exception_normalizer: IExceptionNormalizer | None = None,
    ):
        # ... initialization with fallback to default implementations
```

### DI Wiring Pattern (src/core/di/services.py)

Use the existing DI helpers and singleton lifetimes (these services are stateless or manage shared caches):

```python
def register_core_services(services: ServiceCollection, config: AppConfig | None) -> None:
    services.add_singleton(IStreamFormattingService, implementation_type=StreamFormattingService)
    services.add_singleton(IUsageTrackingWrapper, implementation_type=UsageTrackingWrapper)
    services.add_singleton(IModelAliasResolver, implementation_type=ModelAliasResolver)
    services.add_singleton(IURIParameterApplicator, implementation_type=URIParameterApplicator)
    services.add_singleton(IReasoningConfigApplicator, implementation_type=ReasoningConfigApplicator)
    services.add_singleton(IPlanningPhaseManager, implementation_type=PlanningPhaseManager)
    services.add_singleton(IBackendLifecycleManager, implementation_type=BackendLifecycleManager)
    services.add_singleton(IExceptionNormalizer, implementation_type=ExceptionNormalizer)

    def _backend_service_factory(provider: IServiceProvider) -> BackendService:
        return BackendService(
            factory=provider.get_required_service(BackendFactory),
            rate_limiter=provider.get_required_service(IRateLimiter),
            config=provider.get_required_service(AppConfig),
            session_service=provider.get_required_service(ISessionService),
            app_state=provider.get_required_service(IApplicationState),
            stream_formatting_service=provider.get_required_service(IStreamFormattingService),
            usage_tracking_wrapper=provider.get_required_service(IUsageTrackingWrapper),
            model_alias_resolver=provider.get_required_service(IModelAliasResolver),
            uri_parameter_applicator=provider.get_required_service(IURIParameterApplicator),
            reasoning_config_applicator=provider.get_required_service(IReasoningConfigApplicator),
            planning_phase_manager=provider.get_required_service(IPlanningPhaseManager),
            backend_lifecycle_manager=provider.get_required_service(IBackendLifecycleManager),
            exception_normalizer=provider.get_required_service(IExceptionNormalizer),
            # keep existing optional deps resolution as today
        )
```

### Backward Compatibility

To maintain backward compatibility:

1. All new dependencies are optional with `None` default
2. When `None`, BackendService creates default implementations internally
3. This allows gradual migration and doesn't break existing instantiation code
4. DI container will be updated to inject the new services
5. BackendService keeps existing helper/private methods as thin delegating wrappers to avoid breaking existing tests and debugging scripts
6. Some helpers are invoked in tests as unbound methods with a dummy `self` (e.g., `_apply_reasoning_config`, `_stream_as_sse_bytes`); wrappers MUST continue to work in that mode by not requiring initialized instance state, or by falling back to local default implementations.

### File Organization

```
src/core/
├── interfaces/
│   ├── stream_formatting_interface.py      # NEW
│   ├── usage_tracking_wrapper_interface.py # NEW
│   ├── model_alias_resolver_interface.py   # NEW
│   ├── uri_parameter_applicator_interface.py # NEW
│   ├── reasoning_config_applicator_interface.py # NEW
│   ├── planning_phase_manager_interface.py # NEW
│   ├── backend_lifecycle_manager_interface.py # NEW
│   └── exception_normalizer_interface.py   # NEW
├── services/
│   ├── stream_formatting_service.py        # NEW
│   ├── usage_tracking_wrapper.py           # NEW
│   ├── model_alias_resolver.py             # NEW
│   ├── uri_parameter_applicator.py         # NEW
│   ├── reasoning_config_applicator.py      # NEW
│   ├── planning_phase_manager.py           # NEW
│   ├── backend_lifecycle_manager.py        # NEW
│   ├── exception_normalizer.py             # NEW
│   └── backend_service.py                  # MODIFIED (reduced from ~3200 to ~800 lines)
└── di/
    └── services.py                         # MODIFIED (register new services)
```
