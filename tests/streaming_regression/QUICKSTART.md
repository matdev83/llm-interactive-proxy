# Streaming Regression Tests - Quick Start

## What This Is

Tests that detect when streaming responses are accidentally buffered and delivered all at once instead of incrementally.

## Why It Matters

Streaming makes LLMs appear responsive. If streaming breaks, users see the same final result but it feels slower and less responsive.

## Quick Test

```bash
# Set environment to disable loop detection (temporary workaround)
$env:LOOP_DETECTION_ENABLED="false"

# Run one test
./.venv/Scripts/python.exe -m pytest tests/streaming_regression/test_streaming_core.py::test_openai_streaming_incremental_delivery -v
```

## Expected Result

**✅ Passing (after loop detection fix)**:

```
PASSED tests/streaming_regression/test_streaming_core.py::test_openai_streaming_incremental_delivery
```

**❌ Currently Failing**:

```
FAILED - AssertionError: Should receive multiple chunks
[Response cancelled: Loop detected...]
```

## Current Issue

Loop detector interferes with tests. **Fix needed**: See `LOOP_DETECTION_FIX.patch`

## Run All Tests

```bash
$env:LOOP_DETECTION_ENABLED="false"
./.venv/Scripts/python.exe -m pytest tests/streaming_regression/ -v
```

## Test Categories

```bash
# Core streaming (5 tests)
./.venv/Scripts/python.exe -m pytest tests/streaming_regression/test_streaming_core.py -v

# Cross-protocol (6 tests)
./.venv/Scripts/python.exe -m pytest tests/streaming_regression/test_streaming_translation.py -v

# Advanced features (5 tests)
./.venv/Scripts/python.exe -m pytest tests/streaming_regression/test_streaming_features.py -v

# Hybrid backend (5 tests)
./.venv/Scripts/python.exe -m pytest tests/streaming_regression/test_streaming_hybrid.py -v
```

## Understanding Test Output

### Passing Test

```
✓ Received 8 chunks
✓ Max delay: 0.023s (chunks arrived incrementally)
✓ Backend stats: all_at_once = False
✓ Content integrity: OK
```

### Failing Test (Buffering Detected)

```
✗ Received 1 chunk (expected >3)
✗ Max delay: 0.001s (all chunks arrived at once)
✗ Backend stats: all_at_once = True
→ BUFFERING REGRESSION DETECTED
```

## How It Works

1. **Emulator sends chunks with delays**: `await asyncio.sleep(0.02)`
2. **Test records arrival times**: `chunk_times.append(time.time())`
3. **Test asserts timing**: `assert max(delays) > 0.005`

## Adding New Tests

```python
from tests.streaming_regression.emulators.openai_emulator import OpenAIStreamingEmulator

@pytest.mark.asyncio
async def test_my_streaming_feature():
    # Create chunks
    chunks = OpenAIStreamingEmulator.create_text_chunks("test", chunk_size=10)
    backend = OpenAIStreamingEmulator(chunks=chunks, chunk_delay=0.02)
    
    # Inject backend
    app = _build_streaming_test_app()
    _inject_backend(app, backend)
    
    # Make request and verify timing
    # ... (see existing tests for pattern)
```

## Documentation

- `README.md` - Full user guide
- `IMPLEMENTATION_SUMMARY.md` - Technical details
- `QUICK_FIX_GUIDE.md` - How to fix loop detection issue
- `LOOP_DETECTION_FIX.patch` - Exact code changes needed

## Need Help?

1. Read `README.md` for detailed usage
2. Check `QUICK_FIX_GUIDE.md` for loop detection fix
3. See `IMPLEMENTATION_SUMMARY.md` for architecture details

## Status

- ✅ Infrastructure complete
- ✅ 24 tests written
- ✅ Documentation complete
- ⏳ Blocked on loop detection fix (30 min effort)
