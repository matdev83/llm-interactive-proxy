# Tool-Call Reactor Subsystem

This directory contains the refactored tool-call reactor subsystem, which processes tool calls detected in LLM responses and applies policy/handler logic.

## Architecture Principles

### No Global State Required

**CRITICAL CONSTRAINT**: Components in this subsystem **SHALL NOT** call `get_global_streaming_context_registry()` directly.

#### Rationale

The tool-call reactor subsystem must be constructible via dependency injection (DI) without requiring global mutable state. This constraint ensures:

1. **Testability**: Components can be tested in isolation with injected mocks
2. **DI Compatibility**: Components integrate cleanly with the project's staged initialization and DI container
3. **Dependency Direction**: Interfaces (`src/core/interfaces/`) remain free of dependencies on concrete service-layer types

#### Implementation Pattern

Stream-state access must be provided via **injected collaborators**:

- Use `IToolCallStreamContextResolver` (to be implemented in Phase 2) to resolve stream keys and buffer state
- Inject `StreamingContextRegistry` via DI rather than accessing it globally
- Use `IToolCallBufferState` interface (via `StreamBufferAdapter`) to access buffered tool calls

#### Degraded Mode Behavior

When buffer state is unavailable (e.g., in non-streaming responses or when context is missing), the subsystem operates in **safe degraded mode**:

- Components gracefully handle `None` buffer state
- Processing continues without crashing the request
- Tool calls are still detected and processed from the current response (non-streaming path)

#### Enforcement

A static check script (`scripts/check_no_globals.py`) scans this directory for violations of the no-global-state constraint. This check should be run as part of CI and local development workflows.

## Component Structure

- `stream_buffer_adapter.py`: Adapter wrapping `ToolCallBufferState` to implement `IToolCallBufferState`
- (Additional components to be added in subsequent phases)

## Related Interfaces

- `src/core/interfaces/tool_call_buffer_state.py`: Abstract buffer state contract
- `src/core/interfaces/tool_call_reactor_internal.py`: Typed internal contracts for tool arguments

## Migration Notes

Legacy code in `src/core/services/tool_call_reactor_middleware.py` may still use global registry access as a fallback. This is acceptable for backward compatibility during the transition period, but **all new code** in this subsystem must follow the no-global-state constraint.

