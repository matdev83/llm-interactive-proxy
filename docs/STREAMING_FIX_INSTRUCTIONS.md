# Streaming Response Fix Instructions

## Context
The Gemini OAuth refactoring is **COMPLETE** and working for non-streaming requests.
Both `gemini-oauth-plan` and `gemini-oauth-antigravity` backends work correctly.

**REMAINING ISSUE:** Streaming responses return empty content to clients.

## How to Reproduce

1. Start the proxy:
```bash
./.venv/Scripts/python.exe -m src.core.cli --disable-auth --port 8000
```

2. Run the demo script:
```bash
./.venv/Scripts/python.exe scripts/demo_gemini_oauth_refactor.py
```

Expected: Non-streaming tests pass, streaming tests fail with empty content.

## Root Cause Analysis

### Evidence from CBOR Capture
```
# Backend sends content to proxy:
[171] B->P | backend=gemini-oauth-plan
data: {"choices": [{"delta": {"role": "assistant", "content": "2 +..."}}]}

# Proxy sends to client - CONTENT IS STRIPPED:
[173] P->C | backend=proxy  
data: {"choices": [{"finish_reason": "stop", "delta": {"role": "assistant"}}]}
```

The proxy receives content from the backend but sends empty delta to client.

### Where to Look

The bug is in the **VTC Response Wrapper** or stream processing pipeline:
- `src/core/services/streaming/vtc_response_wrapper.py`
- Specifically `_inject_text()` method around line 281
- Or `_create_chunk_with_text()` method around line 532

### Related Test Failure
```
tests/unit/connectors/test_gemini_oauth_fix.py::test_stream_generator_yields_usage_merged_with_stop
```
This test fails with:
```
TypeError: Cannot directly serialize StopChunkWithUsage
```
at `vtc_response_wrapper.py:281` in `_inject_text()` - it calls `.items()` on a `StopChunkWithUsage` object.

## Files Modified in Refactoring (for reference)

### New Strategy Files
- `src/connectors/gemini_base/interfaces.py` - Strategy interfaces
- `src/connectors/gemini_base/credential_providers/` - FileCredentialProvider, AntigravitySQLiteCredentialProvider
- `src/connectors/gemini_base/endpoints.py` - StandardCodeAssistEndpoint, AntigravitySandboxEndpoint
- `src/connectors/gemini_base/request_builders.py` - StandardRequestBodyBuilder, AntigravityRequestBodyBuilder
- `src/connectors/gemini_base/project_discovery.py` - FreeTier/PaidTier/AntigravityProjectDiscovery
- `src/connectors/gemini_base/model_discovery.py` - ApiModelDiscovery, FallbackModelDiscovery
- `src/connectors/gemini_base/response_processors.py` - NoOp, XmlToolCallPostProcessor

### Modified Connectors
- `src/connectors/gemini_base/connector.py` - Uses injected strategies
- `src/connectors/gemini_oauth_plan.py` - Injects PaidTier strategies
- `src/connectors/gemini_oauth_free.py` - Injects FreeTier strategies
- `src/connectors/gemini_oauth_antigravity.py` - Now inherits from Base (not Free), injects Antigravity strategies

## Key Fix Needed

In `src/core/services/streaming/vtc_response_wrapper.py`:

1. The `_inject_text()` method at line ~281 iterates over `content.items()` but `content` might be a `StopChunkWithUsage` object (which overrides `.items()` to raise TypeError).

2. Need to handle `StopChunkWithUsage` specially - convert to plain dict before iterating:
```python
if isinstance(content, StopChunkWithUsage):
    content = dict(content)  # or content.to_plain_dict()
```

3. Check `src/core/ports/streaming_contracts.py` for `StopChunkWithUsage` class definition.

## Demo Script Location
`scripts/demo_gemini_oauth_refactor.py` - Tests both backends with streaming and non-streaming.

## Verification Commands
```bash
# Run specific failing test
./.venv/Scripts/python.exe -m pytest tests/unit/connectors/test_gemini_oauth_fix.py::test_stream_generator_yields_usage_merged_with_stop -v --tb=long

# Run demo
./.venv/Scripts/python.exe scripts/demo_gemini_oauth_refactor.py

# Inspect CBOR captures for debugging
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py var/wire_captures_cbor/LATEST.cbor --last 20 --verbose
```

