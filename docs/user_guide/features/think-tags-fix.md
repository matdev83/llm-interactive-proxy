# Think Tags Fix

Automatically detect and correct improperly formatted reasoning tags in model responses to prevent reasoning content from being visible to users.

## Overview

Some models from less known vendors produce `<think>` tags inside plain message body instead of using standard reasoning/thinking token separation. This results in reasoning content being visible to users as part of the response. The Think Tags Fix feature detects and corrects such improperly marked reasoning streams, extracting the reasoning content and placing it in appropriate metadata fields while keeping the main response clean.

## Key Features

- **Universal Backend Support**: Works with all connectors (OpenAI, Anthropic, Gemini, custom backends)
- **Streaming Support**: Handles think tags split across multiple streaming chunks with session-based buffering
- **Reasoning Preservation**: Preserves reasoning content in appropriate fields instead of discarding it
- **Multiple Response Formats**: Supports OpenAI-style, dict responses, and ProcessedResponse formats
- **Standards Compliant**: Follows established LLM API patterns for reasoning separation
- **Opt-in Feature**: Disabled by default, no impact on existing functionality

## Configuration

The feature is disabled by default and must be explicitly enabled.

### CLI Flag

```bash
python -m src.core.cli --fix-think-tags
```

### Environment Variable

```bash
export FIX_THINK_TAGS_ENABLED=true
export FIX_THINK_TAGS_STREAMING_BUFFER_SIZE=4096  # Optional: buffer size for streaming
```

### Config File

```yaml
session:
  fix_think_tags_enabled: true
  fix_think_tags_streaming_buffer_size: 4096  # Optional: default 4KB
```

## Usage Examples

### Problem Example

Without the fix, reasoning content is visible to users:

```
Model output: "<think>Let me analyze this step by step...</think>Here's the answer: 42."
User sees: "<think>Let me analyze this step by step...</think>Here's the answer: 42."
```

### Solution Example

With the fix enabled, reasoning is extracted and separated:

```
Model output: "<think>Let me analyze this step by step...</think>Here's the answer: 42."
User sees: "Here's the answer: 42."
Developer access: "Let me analyze this step by step..." (in reasoning field/metadata)
```

### Streaming Example

The fix handles think tags that span multiple streaming chunks:

```
Chunk 1: "<think>Let me"
Chunk 2: " analyze this"
Chunk 3: " step by step...</think>Here's"
Chunk 4: " the answer: 42."

Result:
- User sees: "Here's the answer: 42."
- Reasoning: "Let me analyze this step by step..."
```

## Use Cases

### Working with Lesser-Known Model Providers

Some smaller or regional model providers don't properly implement reasoning token separation. Enable this fix to work with these models while maintaining a clean user experience:

```bash
python -m src.core.cli \
  --default-backend custom-provider \
  --fix-think-tags
```

### Debugging Model Reasoning

Enable the fix to capture and analyze reasoning content from models that expose it via think tags:

```python
# Handle reasoning appropriately
if response.metadata.get("reasoning"):
    log_reasoning_for_debugging(response.metadata["reasoning"])
    show_thinking_if_requested(response.metadata["reasoning"])
display_clean_response(response.content)
```

### Building User Interfaces

Web UIs can provide expandable reasoning sections when available:

```javascript
// Show clean response with optional reasoning
if (response.message.reasoning) {
  showExpandableReasoning(response.message.reasoning);
}
displayMainResponse(response.message.content);
```

### API Client Integration

API clients can access reasoning content for logging or display:

```python
# API client example
if response.metadata.get("reasoning"):
    log_reasoning_for_debugging(response.metadata["reasoning"])
    show_thinking_if_requested(response.metadata["reasoning"])
display_clean_response(response.content)
```

## Response Format Details

The fix adds reasoning content to different fields depending on the response format:

### OpenAI-Style Responses

Adds `reasoning` field to the message:

```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "Here's the answer: 42.",
      "reasoning": "Let me analyze this step by step..."
    }
  }]
}
```

### Dict Responses

Adds reasoning to metadata:

```python
{
  "content": "Here's the answer: 42.",
  "metadata": {
    "reasoning": "Let me analyze this step by step..."
  }
}
```

### ProcessedResponse

Adds reasoning to metadata:

```python
ProcessedResponse(
  content="Here's the answer: 42.",
  metadata={
    "reasoning": "Let me analyze this step by step..."
  }
)
```

## Streaming Buffer Configuration

The streaming buffer size controls how much data can be buffered while waiting for complete think tags:

```yaml
session:
  fix_think_tags_streaming_buffer_size: 4096  # 4KB default
```

**Considerations:**

- **Larger buffers**: Can handle longer reasoning content split across many chunks
- **Smaller buffers**: Use less memory but may fail on very long reasoning sections
- **Default (4KB)**: Suitable for most use cases

## Troubleshooting

**Reasoning content still visible to users:**

- Verify the feature is enabled (`--fix-think-tags` or config)
- Check that the model is using `<think>` tags (not other formats)
- Review logs for parsing errors
- Ensure the buffer size is large enough for the reasoning content

**Reasoning content truncated:**

- Increase the streaming buffer size in configuration
- Check logs for buffer overflow warnings
- Consider if the reasoning content is unusually long

**Performance impact:**

- The fix adds minimal overhead (<1ms per response)
- Streaming responses may have slight latency due to buffering
- Disable the feature if not needed to eliminate any overhead

**Reasoning not appearing in metadata:**

- Verify your client is checking the correct field (`reasoning` or `metadata.reasoning`)
- Check the response format (OpenAI-style vs dict vs ProcessedResponse)
- Enable debug logging to see reasoning extraction details

## Related Features

- [LLM Assessment System](llm-assessment.md) - Monitors conversation quality over time
- [Angel Verification System](angel-verification.md) - Verifies individual responses for quality
- [Hybrid Backend](hybrid-backend.md) - Uses reasoning from one model to improve another
