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

- Use `IToolCallStreamContextResolver` to resolve stream keys and buffer state
- Inject `StreamingContextRegistry` via DI rather than accessing it globally
- Use `IToolCallBufferState` interface (via `StreamBufferAdapter`) to access buffered tool calls

#### Degraded Mode Behavior

When buffer state is unavailable (e.g., in non-streaming responses or when context is missing), the subsystem operates in **safe degraded mode**:

- Components gracefully handle `None` buffer state
- Processing continues without crashing the request
- Tool calls are still detected and processed from the current response (non-streaming path)

#### Enforcement

The no-global-state constraint is enforced via:

1. **Static analysis script**: `dev/scripts/check_no_globals.py` scans this directory for violations. Run manually or add to CI:

   ```bash
   python dev/scripts/check_no_globals.py
   ```

2. **Integration tests**: `tests/integration/test_tool_call_reactor_no_globals.py` verifies that the subsystem can be constructed and operated via DI without global state.

## Component Structure

- `orchestrator.py`: Main orchestrator coordinating tool-call processing flow
- `extractor.py`: Extracts tool calls from response objects
- `normalizer.py`: Normalizes tool-call objects to dictionary format
- `deduplicator.py`: Deduplicates tool calls and tracks processed state
- `arguments_parser.py`: Parses tool arguments with JSON repair
- `arguments_fixup_pipeline.py`: Applies composable fixups (path normalization, Windows separators)
- `replacement_response_factory.py`: Creates client-safe replacement responses for swallowed calls
- `stream_context_resolver.py`: DI-first resolver for stream keys and buffer state
- `stream_buffer_adapter.py`: Adapter wrapping `ToolCallBufferState` to implement `IToolCallBufferState`
- `fixups/`: Directory containing individual fixup implementations

## Related Interfaces

- `src/core/interfaces/tool_call_buffer_state.py`: Abstract buffer state contract
- `src/core/interfaces/tool_call_reactor_internal.py`: Typed internal contracts for tool arguments
- `src/core/interfaces/tool_call_reactor_orchestrator_interface.py`: Orchestrator interface and context model

## Migration Notes

Legacy code in `src/core/services/tool_call_reactor_middleware.py` may still use global registry access as a fallback. This is acceptable for backward compatibility during the transition period, but **all new code** in this subsystem must follow the no-global-state constraint.
