# Streaming Regression Testing Infrastructure

This directory contains comprehensive tests to detect regressions in streaming functionality across the LLM proxy.

## Problem Statement

Streaming can silently break while still delivering correct final responses. The difference is not in the final outcome but in HOW responses are received - full at once vs. streamed in chunks. This reduces user experience as streaming makes models appear more responsive.

## Test Coverage

### 1. Backend Emulators (`emulators/`)

Mock backends that simulate realistic streaming behavior for different API flavors:

- **OpenAI Emulator**: Simulates OpenAI SSE streaming format
- **Anthropic Emulator**: Simulates Anthropic message streaming
- **Gemini Emulator**: Simulates Gemini streaming format

Each emulator:

- Sends responses in realistic chunks (not all at once)
- Includes delays between chunks to simulate network behavior
- Supports various content types (text, tool calls, reasoning)

### 2. Core Streaming Tests (`test_streaming_core.py`)

Tests basic streaming functionality:

- Chunks arrive incrementally (not buffered)
- Timing verification (chunks don't arrive all at once)
- Content integrity (final result matches expected)

### 3. Cross-Protocol Translation Tests (`test_streaming_translation.py`)

Tests streaming with protocol translation:

- OpenAI frontend -> Gemini backend
- OpenAI frontend -> Anthropic backend
- Anthropic frontend -> OpenAI backend
- Anthropic frontend -> Gemini backend
- Gemini frontend -> OpenAI backend
- Gemini frontend -> Anthropic backend

### 4. Advanced Features Tests (`test_streaming_features.py`)

Tests streaming with proxy features enabled:

- API key redaction in streaming responses
- Content rewriting middleware
- Tool call reactors
- Tool call/JSON repairs
- Think tags fix
- Dangerous command protection

### 5. Hybrid Backend Tests (`test_streaming_hybrid.py`)

Tests streaming in hybrid reasoning scenarios:

- Reasoning phase streaming
- Execution phase streaming
- Combined reasoning + execution streaming

## Running Tests

```bash
# Run all streaming regression tests
./.venv/Scripts/python.exe -m pytest tests/streaming_regression/

# Run specific test category
./.venv/Scripts/python.exe -m pytest tests/streaming_regression/test_streaming_core.py

# Run with verbose output to see timing details
./.venv/Scripts/python.exe -m pytest tests/streaming_regression/ -v -s
```

## Test Assertions

Each test verifies:

1. **Incremental Delivery**: Chunks arrive over time, not all at once
2. **Timing**: Delays between chunks are preserved
3. **Content Integrity**: Final assembled content matches expected output
4. **Format Correctness**: SSE/streaming format is maintained
5. **Feature Preservation**: Advanced features work correctly with streaming

## Adding New Tests

When adding new features that touch the streaming pipeline:

1. Add emulator support if needed (`emulators/`)
2. Add core streaming test (`test_streaming_core.py`)
3. Add cross-protocol tests if translation is involved (`test_streaming_translation.py`)
4. Add feature-specific tests (`test_streaming_features.py`)

## Common Failure Patterns

### Buffering Regression

**Symptom**: All chunks arrive at once
**Detection**: Timing assertions fail - all chunks have same timestamp
**Cause**: Async generator consumed before yielding, middleware buffering

### Format Corruption

**Symptom**: SSE format broken, clients can't parse
**Detection**: Content format assertions fail
**Cause**: Middleware modifying chunk boundaries, incorrect SSE reconstruction

### Feature Bypass

**Symptom**: Features work in non-streaming but not streaming
**Detection**: Feature-specific assertions fail in streaming mode
**Cause**: Feature only applied to final response, not streaming chunks
