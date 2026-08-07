# Property-Based Testing Infrastructure

This directory contains the infrastructure for property-based testing of the streaming pipeline refactor.

## Overview

Property-based testing uses the Hypothesis library to automatically generate test cases and verify that universal properties hold across all valid inputs. This approach is more thorough than example-based testing and can discover edge cases that manual testing might miss.

## Components

### 1. Test Data Generators (`property_test_generators.py`)

Provides Hypothesis strategies for generating test data:

#### Core Strategies

- `valid_content_strategy()` - Generates valid content (str, dict, or bytes)
- `text_content_strategy()` - Generates text content
- `dict_content_strategy()` - Generates dictionary content
- `bytes_content_strategy()` - Generates bytes content

#### Metadata Strategies

- `valid_metadata_strategy()` - Generates valid metadata conforming to schema
- `minimal_metadata_strategy()` - Generates minimal required metadata
- `tool_calls_strategy()` - Generates valid tool_calls lists

#### StreamingContent Strategies

- `streaming_content_strategy()` - Generates arbitrary StreamingContent
- `non_done_streaming_content_strategy()` - Generates non-terminal chunks
- `done_streaming_content_strategy()` - Generates terminal chunks
- `streaming_content_with_reasoning_strategy()` - Generates chunks with reasoning
- `streaming_content_with_tool_calls_strategy()` - Generates chunks with tool calls

#### Chunk Pattern Strategies

- `chunk_stream_strategy()` - Generates streams of chunks
- `chunk_stream_with_done_strategy()` - Generates streams ending with done marker
- `interleaved_chunk_stream_strategy()` - Generates interleaved multi-stream chunks

#### Backend-Specific Strategies

- `openai_chunk_strategy()` - Generates OpenAI-style chunks
- `anthropic_event_strategy()` - Generates Anthropic-style events
- `gemini_chunk_strategy()` - Generates Gemini-style chunks

### 2. Hypothesis Configuration (`hypothesis_config.py`)

Provides centralized configuration for Hypothesis:

#### Profiles

- **default** - Standard profile with 100 examples
- **fast** - Quick profile with 10 examples for development
- **ci** - Thorough profile with 200 examples for CI/CD
- **debug** - Debug profile with verbose output

#### Usage

```python
from tests.utils.hypothesis_config import property_test_settings

@given(chunk=streaming_content_strategy())
@property_test_settings()
def test_my_property(chunk):
    # Test implementation
    pass
```

To change profiles:

```python
from tests.utils.hypothesis_config import set_profile

set_profile("fast")  # Use fast profile for development
```

### 3. Helper Utilities (`property_test_helpers.py`)

Provides utility functions for property-based testing:

#### Async Utilities

- `async_list()` - Convert async iterator to list
- `async_iter()` - Convert list to async iterator
- `async_iter_with_delay()` - Convert list to async iterator with delays

#### Validation Utilities

- `validate_chunk_structure()` - Validate chunk structure
- `validate_metadata_schema()` - Validate metadata schema
- `count_done_markers()` - Count done markers in stream
- `has_reasoning_in_content()` - Check for reasoning leaks

#### Stream Processing Utilities

- `process_stream_to_list()` - Collect all chunks from stream
- `filter_stream()` - Filter stream based on predicate
- `map_stream()` - Map transformation over stream

#### Comparison Utilities

- `chunks_equal()` - Compare two chunks for equality
- `metadata_subset()` - Check if metadata is subset

#### Mock Processors

- `PassThroughProcessor` - Passes chunks unchanged
- `CountingProcessor` - Counts chunks processed
- `MetadataEnrichingProcessor` - Adds metadata to chunks

#### Assertion Helpers

- `assert_valid_chunk()` - Assert chunk is valid
- `assert_no_reasoning_leak()` - Assert no reasoning leak
- `assert_single_done_marker()` - Assert exactly one done marker
- `assert_done_marker_at_end()` - Assert done marker at end

#### Test Data Builders

- `ChunkBuilder` - Fluent API for building test chunks

## Writing Property Tests

### Basic Structure

```python
from hypothesis import given, settings
from tests.utils.property_test_generators import streaming_content_strategy
from tests.utils.hypothesis_config import property_test_settings

@given(chunk=streaming_content_strategy())
@property_test_settings()
def test_my_property(chunk):
    """
    Property X: Description
    Feature: streaming-pipeline-refactor, Property X: Description
    
    For any StreamingContent chunk, some property should hold.
    
    Validates: Requirements X.Y
    """
    # Test implementation
    assert some_property_holds(chunk)
```

### Async Property Tests

```python
import pytest
from hypothesis import given
from tests.utils.property_test_generators import chunk_stream_strategy
from tests.utils.property_test_helpers import async_iter, process_stream_to_list

@pytest.mark.asyncio
@given(chunks=chunk_stream_strategy())
@settings(max_examples=100, deadline=None)
async def test_async_property(chunks):
    """Test an async property."""
    stream = async_iter(chunks)
    processed = await process_stream_to_list(stream)
    
    # Verify property
    assert len(processed) == len(chunks)
```

### Using Test Helpers

```python
from tests.utils.property_test_helpers import (
    ChunkBuilder,
    assert_valid_chunk,
    assert_no_reasoning_leak,
)

def test_with_builder():
    """Test using the chunk builder."""
    chunk = (
        ChunkBuilder()
        .with_content("test")
        .with_provider("openai")
        .with_stream_id("test-123")
        .with_reasoning("thinking...")
        .build()
    )
    
    assert_valid_chunk(chunk)
    assert_no_reasoning_leak(chunk)
```

## Configuration

### Environment Variables

- `HYPOTHESIS_PROFILE` - Set the active profile (default, fast, ci, debug)

### pytest.ini Configuration

The Hypothesis settings are configured in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
# Hypothesis will use the default profile unless overridden
```

## Best Practices

### 1. Use Appropriate Strategies

Choose the most specific strategy for your test:

```python
# Good - specific strategy
@given(chunk=non_done_streaming_content_strategy())
def test_non_terminal_chunks(chunk):
    assert not chunk.is_done

# Less good - overly general strategy
@given(chunk=streaming_content_strategy())
def test_non_terminal_chunks(chunk):
    if chunk.is_done:
        return  # Skip done chunks
    # Test implementation
```

### 2. Tag Tests with Property Numbers

Always include the property number and description in the docstring:

```python
def test_property_X():
    """
    Property X: Description
    Feature: streaming-pipeline-refactor, Property X: Description
    
    For any input, property should hold.
    
    Validates: Requirements X.Y
    """
```

### 3. Use Assertion Helpers

Use the provided assertion helpers for common checks:

```python
# Good
assert_valid_chunk(chunk)
assert_no_reasoning_leak(chunk)

# Less good
assert isinstance(chunk.content, str | dict | bytes)
assert "reasoning_content" not in chunk.content
```

### 4. Handle Async Properly

Always use `pytest.mark.asyncio` and `deadline=None` for async tests:

```python
@pytest.mark.asyncio
@given(chunks=chunk_stream_strategy())
@settings(max_examples=100, deadline=None)
async def test_async_property(chunks):
    # Test implementation
    pass
```

### 5. Shrink Failing Examples

When a property test fails, Hypothesis will try to shrink the failing example to a minimal case. Let it complete this process to get the simplest failing case.

## Troubleshooting

### Tests Are Too Slow

Use the fast profile during development:

```python
from tests.utils.hypothesis_config import set_profile
set_profile("fast")
```

Or set the environment variable:

```bash
export HYPOTHESIS_PROFILE=fast
pytest tests/unit/test_my_properties.py
```

### Tests Are Flaky

Ensure you're using `deadline=None` for async tests and that your test doesn't depend on timing:

```python
@settings(max_examples=100, deadline=None)
async def test_my_async_property():
    # Use fake clocks instead of real time
    pass
```

### Need More Examples

Use the ci profile for more thorough testing:

```python
set_profile("ci")  # 200 examples
```

### Debugging Failures

Use the debug profile for verbose output:

```python
set_profile("debug")
```

Or use `@example()` to add specific failing cases:

```python
from hypothesis import given, example

@given(chunk=streaming_content_strategy())
@example(chunk=create_specific_failing_chunk())
def test_property(chunk):
    # Test implementation
    pass
```

## Running Property Tests

### Run All Property Tests

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_*_properties.py
```

### Run Specific Property Test

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_streaming_contracts_properties.py::test_property_chunk_validation
```

### Run with Fast Profile

```bash
HYPOTHESIS_PROFILE=fast ./.venv/Scripts/python.exe -m pytest tests/unit/test_*_properties.py
```

### Run with CI Profile

```bash
HYPOTHESIS_PROFILE=ci ./.venv/Scripts/python.exe -m pytest tests/unit/test_*_properties.py
```

## References

- [Hypothesis Documentation](https://hypothesis.readthedocs.io/)
- [Property-Based Testing Guide](https://hypothesis.works/articles/what-is-property-based-testing/)
- [Streaming Pipeline Design](../../.kiro/specs/streaming-pipeline-refactor/design.md)
- [Streaming Pipeline Requirements](../../.kiro/specs/streaming-pipeline-refactor/requirements.md)
