# Cross-API Translation Service Bugs

This document outlines the bugs and issues identified in the cross-API translation service/layer of the LLM Interactive Proxy project.

## 1. Multimodal Content Handling Issues

### Bug 1.1: Incomplete Image URL Processing in Gemini Translation
**Location**: `src/core/domain/translation.py`, lines 787-797

**Issue**: The Gemini translation only processes data URLs (starting with "data:") and skips HTTP/HTTPS URLs. This is explicitly mentioned in the code comment but is not properly handled.

```python
# Handle only data URLs; skip http/https to match current test expectations
url_str = str(part.image_url.url)
if url_str.startswith("data:"):
    parts.append({
        "inline_data": {  # type: ignore
            "mime_type": "image/jpeg",  # Assume JPEG by default
            "data": url_str.split(",", 1)[-1],
        }
    })
```

**Impact**: Images hosted on the web cannot be processed when translating to Gemini format, breaking multimodal functionality for non-data URLs.

### Bug 1.2: Missing MIME Type Detection
**Location**: `src/core/domain/translation.py`, line 793

**Issue**: The code assumes JPEG format for all images without detecting the actual MIME type from the data URL.

```python
"mime_type": "image/jpeg",  # Assume JPEG by default
```

**Impact**: Non-JPEG images may be incorrectly processed, leading to failures or incorrect rendering.

### Bug 1.3: Inconsistent Multimodal Handling Across APIs
**Location**: Multiple translation methods

**Issue**: Each API (OpenAI, Anthropic, Gemini) handles multimodal content differently, with inconsistent support for image types and formats.

**Impact**: Users experience different behavior when using the same multimodal content with different backends.

## 2. Streaming Response Translation Issues

### Bug 2.1: Inconsistent Stream Chunk Format Handling
**Location**: `src/core/services/translation_service.py`, lines 196-223

**Issue**: The `to_domain_stream_chunk` method has inconsistent handling of different API formats. For Gemini, it returns the raw chunk without proper conversion.

```python
if source_format == "gemini":
    # For Gemini, the raw chunk is already in a format that can be directly yielded
    # or minimally processed to match the expected stream format.
    # We will convert it to a canonical stream chunk format if needed later
    return chunk
```

**Impact**: Gemini streaming responses may not be properly normalized to the domain format, causing inconsistencies in stream processing.

### Bug 2.2: Missing Error Handling in Stream Conversion
**Location**: `src/core/domain/translation.py`, lines 571-631

**Issue**: The `openai_to_domain_stream_chunk` method has basic error handling but doesn't properly log or report all error cases.

```python
except json.JSONDecodeError as exc:
    return {
        "error": "Invalid chunk format: expected JSON after 'data:' prefix",
        "details": {"message": str(exc)},
    }
```

**Impact**: Malformed stream chunks may cause silent failures or inconsistent error reporting.

## 3. Tool/Function Call Translation Issues

### Bug 3.1: Inconsistent Tool Call Format Handling
**Location**: `src/core/domain/translation.py`, lines 210-225

**Issue**: The Gemini response translation doesn't properly handle all tool call formats, particularly when function arguments are not valid JSON.

```python
function_call = part["functionCall"]
tool_calls.append(
    ToolCall(
        id=f"call_{uuid.uuid4().hex[:12]}",
        type="function",
        function=FunctionCall(
            name=function_call.get("name", ""),
            arguments=function_call.get("args", "{}"),
        ),
    )
)
```

**Impact**: Tool calls from Gemini may fail if arguments are not in the expected format.

### Bug 3.2: Missing Tool Choice Translation
**Location**: `src/core/services/translation_service.py`, lines 117-144

**Issue**: The `to_domain_request` method doesn't properly handle the `tool_choice` parameter for all API formats.

**Impact**: Tool selection behavior may be inconsistent across different backends.

## 4. Error Handling Issues

### Bug 4.1: Broad Exception Handling
**Location**: `src/core/domain/translation.py`, lines 105-109

**Issue**: The code uses broad exception handling without specific error types.

```python
except Exception as e:
    logger.error(
        f"Failed to convert Responses API request to domain format - model={getattr(request, 'model', 'unknown')}, error={e}"
    )
    raise
```

**Impact**: Errors may not be properly categorized or handled, making debugging difficult.

### Bug 4.2: Missing Validation in Translation Methods
**Location**: Multiple translation methods

**Issue**: Many translation methods don't validate input parameters before processing, leading to potential runtime errors.

**Impact**: Invalid inputs may cause unexpected failures without clear error messages.

## 5. Inconsistent Parameter Mapping

### Bug 5.1: Inconsistent Stop Sequence Handling
**Location**: `src/core/domain/translation.py`, lines 730-734

**Issue**: Stop sequences are handled differently across APIs, with inconsistent normalization.

```python
stop_sequences = (
    request.stop if isinstance(request.stop, list) else [request.stop]
)
config["stopSequences"] = stop_sequences
```

**Impact**: Stop sequences may not work consistently across different backends.

### Bug 5.2: Missing Parameter Validation
**Location**: `src/core/services/translation_service.py`, lines 260-370

**Issue**: The `_prepare_payload` method doesn't validate that required parameters are present before processing.

**Impact**: Missing required parameters may cause silent failures or unexpected behavior.

## 6. Response Format Issues

### Bug 6.1: Inconsistent Usage Metadata Handling
**Location**: `src/core/domain/translation.py`, lines 252-260

**Issue**: Usage metadata is handled differently across APIs, with inconsistent field names and structures.

```python
usage = {
    "prompt_tokens": usage_metadata.get("promptTokenCount", 0),
    "completion_tokens": usage_metadata.get("candidatesTokenCount", 0),
    "total_tokens": usage_metadata.get("totalTokenCount", 0),
}
```

**Impact**: Usage tracking may be inconsistent or incorrect for different backends.

### Bug 6.2: Missing Response Validation
**Location**: Multiple response translation methods

**Issue**: Response translation methods don't validate that required fields are present in the response.

**Impact**: Malformed responses may cause downstream failures.

## 7. Structured Output Issues

### Bug 7.1: Incomplete JSON Schema Validation
**Location**: `src/core/domain/translation.py`, lines 22-47

**Issue**: The JSON schema validation falls back to basic validation when the jsonschema library is not available, which may miss important validation errors.

```python
except ImportError:
    # jsonschema not available, perform basic validation
    return Translation._basic_schema_validation(json_data, schema)
```

**Impact**: Structured output validation may be insufficient, leading to invalid responses.

### Bug 7.2: Missing Error Recovery for Structured Output
**Location**: `src/core/domain/translation.py`, lines 1652-1840

**Issue**: The structured output enhancement doesn't have robust error recovery for all failure cases.

**Impact**: Failed structured output may not be properly repaired, resulting in invalid responses.

## 8. Code Quality Issues

### Bug 8.1: Code Duplication
**Location**: Multiple translation methods

**Issue**: There is significant code duplication between different translation methods, particularly in parameter handling.

**Impact**: Maintenance burden and increased likelihood of inconsistencies.

### Bug 8.2: Missing Type Hints
**Location**: Multiple methods in translation classes

**Issue**: Several methods lack complete type hints, making the code harder to understand and maintain.

**Impact**: Reduced code clarity and potential for type-related bugs.

## 9. Test Coverage Issues

### Bug 9.1: Incomplete Test Coverage for Edge Cases
**Location**: Test files

**Issue**: The test suite doesn't cover all edge cases, particularly for error conditions and malformed inputs.

**Impact**: Bugs may not be caught until they occur in production.

### Bug 9.2: TODO Comments Indicating Unimplemented Features
**Location**: `tests/unit/core/domain/test_translation_cross_api.py`, lines 107-112

**Issue**: Test files contain TODO comments indicating that certain features (like multimodal content) are not properly implemented or tested.

```python
# TODO: Fix the implementation to handle multimodal content properly
# The following assertions would be valid once the implementation is fixed:
# assert len(parts) == 2
# assert "inline_data" in parts[1]
```

**Impact**: Known functionality gaps are not being addressed.