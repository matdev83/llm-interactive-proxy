# Response Adapters Package

This package contains the modular layer components for converting domain response objects to FastAPI/Starlette response objects. The architecture follows SOLID principles with clear separation of concerns, dependency injection, and independent testability.

## Architecture Overview

The adapters package is organized into focused layers, each handling a specific aspect of response transformation:

```
adapters/
├── protocols.py          # Protocol definitions for all layer contracts
├── sse/                  # SSE formatting and decoding
├── metadata/             # Metadata injection (reasoning, etc.)
├── usage/                # Usage normalization and header injection
├── sanitization/         # Content and header sanitization
├── capture/              # Wire capture coordination
├── streaming/             # Streaming content conversion and buffering
└── response/             # Response builders (JSON, Streaming, Other)
```

## Layer Components

### SSE Layer (`sse/`)
- **SSEFormatter**: Formats content as SSE bytes (`data: {json}\n\n`)
- **SSEDecoder**: Decodes SSE-formatted payloads from various providers

### Metadata Layer (`metadata/`)
- **ReasoningInjector**: Injects reasoning metadata into OpenAI-style payloads

### Usage Layer (`usage/`)
- **UsageNormalizer**: Normalizes usage dictionaries to standard format
- **UsageHeaderInjector**: Applies usage data as HTTP headers

### Sanitization Layer (`sanitization/`)
- **JSONSanitizer**: Ensures JSON-safe content (converts non-serializable objects)
- **HeaderSanitizer**: Filters HTTP headers to allowed prefixes

### Capture Layer (`capture/`)
- **WireCaptureCoordinator**: Coordinates wire capture operations for debugging

### Streaming Layer (`streaming/`)
- **ToolBlockBuffer**: Buffers multiline tool blocks across streaming chunks
- **StreamingContentConverter**: Converts raw stream chunks to StreamingContent

### Response Layer (`response/`)
- **JSONResponseBuilder**: Builds FastAPI JSONResponse
- **StreamingResponseBuilder**: Builds FastAPI StreamingResponse
- **OtherResponseBuilder**: Builds non-JSON responses

## Usage

The facade in `response_adapters.py` provides the public API:

```python
from src.core.transport.fastapi.response_adapters import domain_response_to_fastapi

# Convert domain response to FastAPI response
response = domain_response_to_fastapi(envelope, wire_capture=wire_capture, context=context)
```

## Dependency Injection

All layer components support dependency injection via constructor parameters, with fallback to default instances when DI is unavailable:

```python
# With DI
json_builder = JSONResponseBuilder(
    json_sanitizer=my_sanitizer,
    header_sanitizer=my_header_sanitizer,
    usage_header_injector=my_injector,
)

# Without DI (uses defaults)
json_builder = JSONResponseBuilder()
```

## Protocol Contracts

All layer components implement protocols defined in `protocols.py`. This enables:
- Type checking and IDE support
- Runtime protocol compliance verification
- Easy mocking in tests

## Testing

Each layer has dedicated unit tests in `tests/unit/transport/fastapi/adapters/`. Integration tests verify the full pipeline in `tests/integration/transport/fastapi/`.

## Migration Notes

The original monolithic `response_adapters.py` (1851 lines) has been refactored into this modular structure. The facade maintains 100% backward compatibility with existing callers.

