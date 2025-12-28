# Typed Data Contracts

## Introduction

This document describes the canonical typed data contracts used for cross-layer and cross-domain data exchange in the LLM Interactive Proxy. These contracts provide strict typing for data flowing between transport, core services, and connector layers, reducing reliance on ad hoc `dict[str, Any]` and `Any` types.

### Purpose

The typed data contracts system ensures:

- **Type Safety**: Cross-layer boundaries use explicit, typed contracts instead of `Any` or unconstrained dictionaries
- **Maintainability**: Clear data shapes make the codebase easier to understand and modify
- **Debuggability**: Explicit contracts improve error messages and debugging workflows
- **Consistency**: Single canonical representation per concept reduces conversion overhead

### Scope

This guidance applies to:

- **Cross-layer boundaries**: Transport ↔ Core ↔ Connector interfaces
- **Cross-domain boundaries**: Routing, failover, usage tracking, capture, and connector interfaces
- **Boundary conversion points**: Explicit points where data representation changes

This guidance does **not** apply to:

- Internal implementation details within a single layer
- Test utilities and fixtures (though tests should use canonical contracts when testing boundaries)
- Legacy compatibility shims (documented exceptions)

## Canonical Contract Set v1

The following contracts are the canonical representations used for cross-layer data exchange. These are the **source of truth** for their respective concepts.

### Request Payloads

#### `CanonicalChatRequest`

**Location**: `src/core/domain/chat.py`

**Purpose**: Canonical representation of chat completion requests flowing through the core processing pipeline.

**Key Fields**:
- `model: str` - Model identifier
- `messages: list[ChatMessage]` - Conversation messages
- `temperature: float | None` - Sampling temperature
- `max_completion_tokens: int | None` - Token limit
- `tools: list[dict[str, Any]] | None` - Tool definitions
- `extra_body: dict[str, Any] | None` - Protocol-specific extensions

**Usage**: 
- Controllers convert inbound HTTP payloads to `CanonicalChatRequest` before invoking core services
- Core services and connectors receive `CanonicalChatRequest` as input
- All protocol-specific request formats normalize to this canonical shape

**Alias**: `ChatRequest` is a compatibility alias for `CanonicalChatRequest`.

### Request Context

#### `RequestContext`

**Location**: `src/core/domain/request_context.py`

**Purpose**: Transport-agnostic request context carrying cross-layer metadata and correlation identifiers.

**Key Fields**:
- `domain_request: CanonicalChatRequest | None` - Canonical request payload
- `raw_body: bytes | None` - Raw HTTP body bytes (for capture)
- `backend: str | None` - Resolved backend identifier
- `effective_model: str | None` - Effective model after resolution
- `extensions: dict[str, JsonValue]` - Single extension container (see Extension-Field Policy)
- `session_id: str | None` - Session correlation identifier
- `request_id: str | None` - Request correlation identifier
- `original_domain_request: CanonicalChatRequest | None` - Original request before mutations (provenance)

**Usage**:
- Populated by transport adapters during request adaptation
- Passed through core services for session resolution, routing, and capture
- Preserves original request for debugging and accounting

**Important**: All cross-layer context data must use explicit typed fields. Dynamic attribute assignment (`context.attr = value`) is **not allowed** in boundary code.

### Backend Routing

#### `BackendTarget`

**Location**: `src/core/domain/backend_target.py`

**Purpose**: Canonical contract for resolved backend target (backend + model + URI parameters).

**Key Fields**:
- `backend: str` - Backend identifier (e.g., "openai", "anthropic", "gemini")
- `model: str` - Model identifier (e.g., "gpt-4", "claude-3-5-sonnet")
- `uri_params: dict[str, JsonValue]` - URI parameters extracted from model string

**Usage**:
- Output of backend model resolver
- Input to backend completion flow
- Handoff between routing and completion orchestration

**Compatibility**: Provides `from_resolved_target()` and `to_resolved_target()` for migration from legacy `ResolvedTarget` NamedTuple.

### Usage and Metrics

#### `UsageSummary`

**Location**: `src/core/domain/usage_summary.py`

**Purpose**: Canonical contract for token usage and provider-specific usage metadata.

**Key Fields**:
- `prompt_tokens: int | None` - Prompt token count
- `completion_tokens: int | None` - Completion token count
- `total_tokens: int | None` - Total token count
- `extensions: dict[str, JsonValue]` - Provider-specific usage details

**Usage**:
- Returned by connectors in response metadata
- Recorded in wire capture and usage tracking
- Merged across multiple backend calls (failover scenarios)

**Compatibility**: Provides `from_dict()` for parsing provider API responses.

### Response Envelopes

#### `ResponseEnvelope`

**Location**: `src/core/domain/responses.py`

**Purpose**: Transport-agnostic container for non-streaming responses.

**Key Fields**:
- `content: dict[str, Any] | str | bytes | None` - Response content (JSON dict, string, bytes, or None)
- `usage: UsageSummary | None` - Token usage summary
- `metadata: dict[str, JsonValue] | None` - Response metadata
- `headers: dict[str, str] | None` - HTTP headers
- `status_code: int` - HTTP status code
- `media_type: str` - Content type

**Usage**:
- Returned by connectors to core services
- Adapted by transport layer to HTTP responses
- Captured in wire capture for replay

**Note**: `content` field narrowed from `Any` to `dict[str, Any] | str | bytes | None` in Phase B+. This provides type safety while maintaining flexibility for the known response types used across the codebase.

#### `StreamingResponseEnvelope`

**Location**: `src/core/domain/responses.py`

**Purpose**: Transport-agnostic container for streaming responses.

**Key Fields**:
- `content: AsyncIterator[ProcessedResponse] | None` - Stream iterator
- `metadata: dict[str, JsonValue] | None` - Response metadata
- `headers: dict[str, str] | None` - HTTP headers
- `cancel_callback: Callable[[], Awaitable[None]] | None` - Cancellation handler

**Usage**:
- Returned by connectors for streaming responses
- Adapted by transport layer to SSE/streaming HTTP responses
- Captured incrementally in wire capture

### Streaming Chunks

#### `StreamingContent`

**Location**: `src/core/domain/streaming/streaming_content.py`

**Purpose**: Canonical internal representation for streaming chunks flowing through the pipeline.

**Key Fields**:
- `content: str | dict | bytes` - Chunk content
- `metadata: dict[str, Any]` - Chunk metadata
- `is_done: bool` - Completion marker
- `is_empty: bool | None` - Empty chunk indicator
- `stream_id: str | None` - Stream correlation identifier
- `usage: dict[str, Any] | None` - Token usage for this chunk

**Usage**:
- Internal representation in streaming processors
- Lightweight dataclass for performance-sensitive hot paths
- Converted to `StreamingChunk` at serialization boundaries

#### `StreamingChunk`

**Location**: `src/core/domain/streaming/contracts.py`

**Purpose**: Typed serialization/validation contract for streaming chunks at boundaries.

**Key Fields**:
- `payload: StreamingPayload` - Typed payload (text, opaque_json, binary, empty)
- `metadata: StreamingMetadata` - Typed metadata (provider, finish_reason, tool_calls, etc.)
- `is_done: bool` - Completion marker
- `is_empty: bool` - Empty chunk indicator
- `is_cancellation: bool` - Cancellation marker

**Usage**:
- Used by SSE serializer for validation
- Used in error envelopes and done markers
- Provides strong schema validation at boundaries

**Conversion**: `StreamingContent.to_typed_chunk()` and `StreamingContent.from_typed_chunk()` provide bidirectional conversion.

## Boundary Conversion Points

Data representation changes occur only at **explicit boundary conversion points**. These are the only places where conversions between representations are allowed.

### Transport ↔ Domain

**Location**: `src/core/transport/fastapi/request_adapters.py` and controller adapters

**Conversions**:
- **Inbound**: HTTP request body → `CanonicalChatRequest`
- **Inbound**: HTTP headers/cookies → `RequestContext` (with `domain_request` and `raw_body` populated)
- **Outbound**: `ResponseEnvelope` / `StreamingResponseEnvelope` → HTTP response

**Rules**:
- Controllers must convert to canonical contracts **before** invoking core services
- Transport-specific types (FastAPI `Request`, `Response`) must not leak into core services
- Raw body bytes must be captured in `RequestContext.raw_body` for wire capture

**Example**:
```python
# Controller receives HTTP request
async def chat_completion(request: Request):
    # Convert to canonical contract
    domain_request = await adapt_request_to_canonical(request)
    context = RequestContext(
        headers=request.headers,
        cookies=request.cookies,
        domain_request=domain_request,
        raw_body=await request.body(),
        # ... other fields
    )
    # Pass canonical contracts to core service
    result = await request_processor.process(domain_request, context)
    # Adapt response envelope to HTTP
    return adapt_envelope_to_http(result)
```

### Domain ↔ Connector

**Location**: `src/core/services/backend_completion_flow/` and connector interfaces

**Conversions**:
- **Outbound**: `CanonicalChatRequest` + `BackendTarget` → Provider-specific request format (inside connector)
- **Inbound**: Provider response → `ResponseEnvelope` / `StreamingResponseEnvelope`

**Rules**:
- Connectors receive canonical contracts as input
- Provider-specific request construction happens **inside** connectors
- Connectors return transport-agnostic envelopes, not provider-specific types

**Example**:
```python
# Connector receives canonical contracts
async def complete(
    self,
    request: CanonicalChatRequest,
    target: BackendTarget,
    context: RequestContext,
) -> ResponseEnvelope:
    # Convert to provider format (internal to connector)
    provider_request = self._to_provider_format(request, target)
    # Call provider API
    provider_response = await self._client.chat(provider_request)
    # Convert to canonical envelope
    return self._to_envelope(provider_response)
```

### Domain ↔ Capture/Replay

**Location**: `src/core/simulation/capture_decoder.py` and wire capture services

**Conversions**:
- **Capture**: Canonical contracts → CBOR bytes (deterministic serialization)
- **Replay**: CBOR bytes → Canonical contracts (best-effort decoding)

**Rules**:
- Raw bytes are the source of truth for capture fidelity
- Decoding failures are non-blocking (best-effort)
- Decoded contracts are used for simulation/debugging, not as authoritative source

**Example**:
```python
# Capture: contract → bytes
capture_entry = CaptureEntry(
    request=domain_request.model_dump_json(),
    response=envelope.model_dump_json(),
    # ... other fields
)
cbor_bytes = encode_cbor(capture_entry)

# Replay: bytes → contract (best-effort)
try:
    decoded = decode_cbor(cbor_bytes)
    request = CanonicalChatRequest.model_validate_json(decoded.request)
except Exception as e:
    logger.warning(f"Failed to decode contract: {e}")
    # Fall back to raw bytes inspection
```

## Extension-Field Policy

### Single Extension Container Rule

Each canonical contract may have **at most one** explicitly named extension container:

- `RequestContext.extensions: dict[str, JsonValue]`
- `UsageSummary.extensions: dict[str, JsonValue]`
- `ResponseEnvelope.metadata: dict[str, JsonValue] | None`

**Rationale**: Multiple extension containers create ambiguity about where to place new fields. A single container makes the policy clear.

### JSON-Serializable Constraint

Extension values must be JSON-serializable. Use `pydantic.types.JsonValue` type:

```python
from pydantic.types import JsonValue

extensions: dict[str, JsonValue] = {}
# JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
```

**Rationale**: 
- Extensions must be serializable for wire capture and debugging
- JSON serialization ensures deterministic capture metadata
- Type checker can validate JSON-serializable constraint

### When to Use Extensions

Extensions are appropriate when:

1. **Vendor/Protocol-Specific**: Data is specific to a single provider or protocol
2. **Unstable**: Field shape changes frequently or is experimental
3. **Low-Frequency Access**: Field is rarely accessed in core logic
4. **Cross-Layer Necessity**: Data must flow across layers but doesn't warrant a typed field

Extensions are **not** appropriate when:

1. **Stable and Frequently Used**: Field is stable and accessed frequently → promote to typed field
2. **Core Semantic Data**: Field is part of the core contract semantics → use typed field
3. **Type Safety Critical**: Field shape affects correctness → use typed field

### Examples

**Good**: Protocol-specific metadata
```python
# OpenAI-specific request metadata
context.extensions["openai_service_tier"] = "priority"

# Gemini-specific generation config
request.extra_body = {"generation_config": {...}}  # extra_body is protocol-specific
```

**Bad**: Core semantic data in extensions
```python
# BAD: Core semantic field should be typed
context.extensions["backend"] = "openai"  # Should use context.backend

# BAD: Frequently accessed field should be typed
context.extensions["session_id"] = session_id  # Should use context.session_id
```

## Promotion Process

When an extension key becomes stable and frequently used, it should be **promoted** to a first-class typed field.

### Promotion Criteria

An extension key should be promoted when:

1. **Stability**: Field shape has been stable for multiple releases
2. **Frequency**: Field is accessed in multiple places across layers
3. **Semantic Importance**: Field affects core contract semantics or correctness
4. **Type Safety**: Stronger typing would catch bugs or improve maintainability

### Promotion Steps

1. **Add Typed Field**: Add the field to the canonical contract with appropriate type
2. **Migration Period**: Support both extension key and typed field during migration
3. **Update Writers**: Update all code that writes the extension key to use the typed field
4. **Update Readers**: Update all code that reads the extension key to use the typed field
5. **Deprecation**: Mark extension key access as deprecated (if still supported)
6. **Removal**: Remove extension key support after migration period

### Example: Promoting `backend` Extension

**Before** (extension):
```python
# Writers
context.extensions["backend"] = "openai"

# Readers
backend = context.extensions.get("backend")
```

**After** (typed field):
```python
# Contract definition
class RequestContext:
    backend: str | None = None
    extensions: dict[str, JsonValue] = field(default_factory=dict)

# Writers
context.backend = "openai"

# Readers
backend = context.backend
```

**Migration** (support both):
```python
# Writers: use typed field
context.backend = "openai"

# Readers: check typed field first, fall back to extension for compatibility
backend = context.backend or context.extensions.get("backend")
```

## Examples

### Before/After: Function Signatures

**Before** (ad hoc types):
```python
async def process_request(
    request_data: dict[str, Any],
    context: Any,
    backend_info: dict[str, Any],
) -> dict[str, Any]:
    # Type checker can't validate shapes
    # Runtime errors possible from missing keys
    backend = backend_info.get("backend")
    model = backend_info.get("model")
    # ...
```

**After** (canonical contracts):
```python
async def process_request(
    request: CanonicalChatRequest,
    context: RequestContext,
    target: BackendTarget,
) -> ResponseEnvelope:
    # Type checker validates shapes
    # IDE autocomplete works
    backend = target.backend
    model = target.model
    # ...
```

### Before/After: Extension Usage

**Before** (unconstrained dict):
```python
# No type safety
metadata: dict[str, Any] = {}
metadata["usage"] = {"tokens": 100}  # Could be anything
metadata["custom_field"] = SomeComplexObject()  # Not serializable
```

**After** (constrained extensions):
```python
from pydantic.types import JsonValue

# Type-safe extensions
extensions: dict[str, JsonValue] = {}
extensions["usage"] = {"tokens": 100}  # Validated as JSON-serializable
# extensions["custom_field"] = SomeComplexObject()  # Type error!
```

### Before/After: Request Context

**Before** (dynamic attributes):
```python
# Dynamic attribute assignment (requires type: ignore)
context.domain_request = request  # type: ignore[attr-defined]
context.raw_body = body_bytes  # type: ignore[attr-defined]
context.backend = "openai"  # type: ignore[attr-defined]

# Readers must use getattr with defaults
backend = getattr(context, "backend", None)
```

**After** (explicit typed fields):
```python
# Explicit typed fields
context.domain_request = request  # Type-safe
context.raw_body = body_bytes  # Type-safe
context.backend = "openai"  # Type-safe

# Readers use direct attribute access
backend = context.backend  # Type-safe, IDE autocomplete works
```

## PR Checklist

When modifying cross-layer boundaries, verify:

- [ ] **No new `Any`** in `src/core/interfaces/` function signatures for cross-layer seams
- [ ] **No new `dict[str, Any]`** for contract-shaped payloads; use `JsonValue` or a named contract
- [ ] **No new `type: ignore`** in boundary modules (`src/core/interfaces/`, `src/core/domain/`, `src/core/transport/`) without documented rationale
- [ ] **Canonical contracts used** at all cross-layer boundaries (transport ↔ core ↔ connector)
- [ ] **Extensions constrained** to `JsonValue` type (not `Any`)
- [ ] **Single extension container** per contract (not multiple extension fields)

### Local Validation

Run the boundary type checker before submitting PRs:

```bash
./.venv/Scripts/python.exe dev/scripts/check_boundary_types.py
```

This script checks for:
- `Any` in function signatures in boundary modules
- `dict[str, Any]` for contract-shaped data
- New `type: ignore` comments in boundary code

### If Violations Are Necessary

If you must introduce a violation (e.g., legacy compatibility):

1. **Document rationale** in code comments explaining why the violation is necessary
2. **Add follow-up task** to remove the violation in a future PR
3. **Use allowlist** in `check_boundary_types.py` if the violation is in a legitimate internal context

Example:
```python
# TODO: Remove Any after migrating legacy callers (tracked in #1234)
def legacy_compat_method(request: Any) -> ResponseEnvelope:  # type: ignore[no-untyped-def]
    ...
```

## Related Documentation

- [Architecture Guide](./architecture.md) - System architecture overview
- [Code Organization](./code-organization.md) - Module structure and organization
- [Adding Features](./adding-features.md) - Feature development workflow
- [Adding Backends](./adding-backends.md) - Backend connector development

## References

- **Specification**: `.kiro/specs/cross-layer-typed-data-contracts/`
- **Design Document**: `.kiro/specs/cross-layer-typed-data-contracts/design.md`
- **Requirements**: `.kiro/specs/cross-layer-typed-data-contracts/requirements.md`

