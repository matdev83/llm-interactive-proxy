# Suggested Fixes for Translation Service Bugs

This document provides detailed suggested fixes for the identified bugs in the cross-API translation service, organized by priority.

## Critical Priority (P0) Fixes

### Fix 1.1: Complete Image URL Processing in Gemini Translation

**Current Issue**: Only data URLs are processed, HTTP/HTTPS URLs are skipped.

**Suggested Fix**:
```python
# In src/core/domain/translation.py, around line 787-797

def _process_image_part(self, part: MessageContentPartImage) -> dict[str, Any]:
    """Process an image part for Gemini format, handling both data and HTTP URLs."""
    url_str = str(part.image_url.url)
    
    if url_str.startswith("data:"):
        # Handle data URL
        try:
            header, b64_data = url_str.split(",", 1)
            mime = header.split(";")[0][5:]
            return {
                "inline_data": {
                    "mime_type": mime,
                    "data": b64_data
                }
            }
        except (ValueError, IndexError):
            # Fallback for malformed data URLs
            return {
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": ""
                }
            }
    else:
        # Handle HTTP/HTTPS URLs
        return {
            "file_data": {
                "mime_type": "image/jpeg",  # Default, could be enhanced with detection
                "file_uri": url_str
            }
        }
```

**Implementation Steps**:
1. Create a helper method `_process_image_part` to handle both data and HTTP URLs
2. Replace the existing image processing code with calls to this method
3. Add tests for both data URLs and HTTP URLs
4. Consider adding MIME type detection from URL extension or HTTP headers

### Fix 2.1: Consistent Stream Chunk Format Handling

**Current Issue**: Gemini stream chunks are returned without proper conversion to domain format.

**Suggested Fix**:
```python
# In src/core/services/translation_service.py, around line 196-223

def to_domain_stream_chunk(self, chunk: Any, source_format: str) -> Any:
    """
    Translates a streaming chunk from a specific API format to the internal domain stream chunk.
    """
    if source_format == "gemini":
        # Convert Gemini chunk to canonical format
        return self._convert_gemini_stream_to_domain(chunk)
    elif source_format in {"openai", "openai-responses"}:
        return Translation.openai_to_domain_stream_chunk(chunk)
    # ... rest of the method

def _convert_gemini_stream_to_domain(self, chunk: Any) -> dict[str, Any]:
    """Convert Gemini stream chunk to domain format."""
    if not isinstance(chunk, dict):
        return {"error": "Invalid chunk format: expected a dictionary"}
    
    response_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"
    created = int(time.time())
    model = "gemini-pro"
    
    content = ""
    finish_reason = None
    
    if "candidates" in chunk:
        for candidate in chunk["candidates"]:
            if "content" in candidate and "parts" in candidate["content"]:
                for part in candidate["content"]["parts"]:
                    if "text" in part:
                        content += part["text"]
            if "finishReason" in candidate:
                finish_reason = candidate["finishReason"].lower()
                if finish_reason == "stop":
                    finish_reason = "stop"
                elif finish_reason == "max_tokens":
                    finish_reason = "length"
                elif finish_reason == "safety":
                    finish_reason = "content_filter"
                elif finish_reason == "tool_calls":
                    finish_reason = "tool_calls"
    
    return {
        "id": response_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
    }
```

**Implementation Steps**:
1. Create a dedicated method to convert Gemini stream chunks to domain format
2. Update the `to_domain_stream_chunk` method to use this conversion
3. Ensure consistent handling of finish reasons across all APIs
4. Add comprehensive tests for stream chunk conversion

### Fix 3.1: Consistent Tool Call Format Handling

**Current Issue**: Tool calls from Gemini may fail if arguments are not in valid JSON format.

**Suggested Fix**:
```python
# In src/core/domain/translation.py, around line 210-225

def _process_function_call(self, function_call: dict[str, Any]) -> ToolCall:
    """Process a function call from Gemini response with proper error handling."""
    name = function_call.get("name", "")
    args = function_call.get("args", "{}")
    
    # Ensure arguments are valid JSON
    if isinstance(args, str):
        try:
            # Already a JSON string
            json.loads(args)
        except json.JSONDecodeError:
            # Invalid JSON, try to fix common issues
            try:
                # Replace single quotes with double quotes
                fixed_args = args.replace("'", '"')
                json.loads(fixed_args)
                args = fixed_args
            except json.JSONDecodeError:
                # If still invalid, wrap in a JSON object
                args = json.dumps({"_raw": args})
    elif not isinstance(args, (str, dict)):
        # Convert to JSON string
        args = json.dumps(args)
    
    return ToolCall(
        id=f"call_{uuid.uuid4().hex[:12]}",
        type="function",
        function=FunctionCall(
            name=name,
            arguments=args,
        ),
    )
```

**Implementation Steps**:
1. Create a helper method to process function calls with proper error handling
2. Add validation and repair for malformed JSON arguments
3. Update the Gemini response translation to use this helper
4. Add tests for various malformed argument scenarios

## High Priority (P1) Fixes

### Fix 1.2: Missing MIME Type Detection

**Current Issue**: All images are assumed to be JPEG format.

**Suggested Fix**:
```python
def _detect_mime_type(self, url: str, data: str = "") -> str:
    """Detect MIME type from URL or data."""
    # Try to detect from data URL
    if url.startswith("data:"):
        try:
            header = url.split(";", 1)[0]
            if ":" in header:
                return header.split(":", 1)[1]
        except IndexError:
            pass
    
    # Try to detect from file extension
    if url.startswith("http"):
        extension = url.split(".")[-1].lower()
        mime_types = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "webp": "image/webp",
        }
        return mime_types.get(extension, "image/jpeg")
    
    # Default to JPEG
    return "image/jpeg"
```

**Implementation Steps**:
1. Create a MIME type detection helper method
2. Update image processing code to use this method
3. Add tests for various image formats

### Fix 4.1: Specific Exception Handling

**Current Issue**: Broad exception handling without specific error types.

**Suggested Fix**:
```python
# Replace broad exception handling with specific exceptions

try:
    domain_request = Translation.responses_to_domain_request(request)
    logger.debug(
        f"Successfully converted Responses API request to domain format - model={getattr(request, 'model', 'unknown')}"
    )
    return domain_request
except (ValueError, KeyError) as e:
    logger.error(
        f"Invalid format in Responses API request - model={getattr(request, 'model', 'unknown')}, error={e}"
    )
    raise ValueError(f"Invalid request format: {e}") from e
except json.JSONDecodeError as e:
    logger.error(
        f"JSON decode error in Responses API request - model={getattr(request, 'model', 'unknown')}, error={e}"
    )
    raise ValueError(f"Invalid JSON in request: {e}") from e
except Exception as e:
    logger.error(
        f"Unexpected error converting Responses API request - model={getattr(request, 'model', 'unknown')}, error={e}",
        exc_info=True
    )
    raise
```

**Implementation Steps**:
1. Identify all locations with broad exception handling
2. Replace with specific exception types
3. Add proper error logging with context
4. Create custom exception classes if needed

### Fix 5.2: Parameter Validation

**Current Issue**: Missing validation of required parameters.

**Suggested Fix**:
```python
def _validate_request_parameters(self, request: CanonicalChatRequest) -> None:
    """Validate required parameters in a domain request."""
    if not request.model:
        raise ValueError("Model is required")
    
    if not request.messages:
        raise ValueError("Messages are required")
    
    # Validate message structure
    for message in request.messages:
        if not message.role:
            raise ValueError("Message role is required")
        
        # Validate content based on role
        if message.role != "system" and not message.content:
            raise ValueError(f"Content is required for {message.role} messages")
    
    # Validate tool parameters if present
    if request.tools:
        for tool in request.tools:
            if isinstance(tool, dict):
                if "function" not in tool:
                    raise ValueError("Tool must have a function")
                if "name" not in tool.get("function", {}):
                    raise ValueError("Tool function must have a name")
```

**Implementation Steps**:
1. Create validation methods for different request types
2. Add validation calls at the beginning of translation methods
3. Add comprehensive tests for validation

### Fix 7.1: Enhanced JSON Schema Validation

**Current Issue**: Fallback validation when jsonschema library is not available.

**Suggested Fix**:
```python
def _enhanced_schema_validation(
    self, json_data: dict[str, Any], schema: dict[str, Any]
) -> tuple[bool, str | None]:
    """
    Enhanced JSON schema validation with better error reporting.
    """
    try:
        import jsonschema
        jsonschema.validate(json_data, schema)
        return True, None
    except ImportError:
        # Use enhanced basic validation
        return self._comprehensive_schema_validation(json_data, schema)
    except jsonschema.ValidationError as e:
        return False, f"Schema validation failed: {e.message}"
    except Exception as e:
        return False, f"Schema validation error: {e!s}"

def _comprehensive_schema_validation(
    self, json_data: dict[str, Any], schema: dict[str, Any]
) -> tuple[bool, str | None]:
    """
    More comprehensive basic validation without jsonschema library.
    """
    try:
        # Check type
        schema_type = schema.get("type")
        if schema_type == "object" and not isinstance(json_data, dict):
            return False, f"Expected object, got {type(json_data).__name__}"
        elif schema_type == "array" and not isinstance(json_data, list):
            return False, f"Expected array, got {type(json_data).__name__}"
        # ... other type checks
        
        # Check required properties for objects
        if schema_type == "object" and isinstance(json_data, dict):
            required = schema.get("required", [])
            for prop in required:
                if prop not in json_data:
                    return False, f"Missing required property: {prop}"
            
            # Check property types
            properties = schema.get("properties", {})
            for prop, value in json_data.items():
                if prop in properties:
                    prop_schema = properties[prop]
                    prop_type = prop_schema.get("type")
                    if prop_type == "string" and not isinstance(value, str):
                        return False, f"Property '{prop}' should be string, got {type(value).__name__}"
                    # ... other property type checks
        
        return True, None
    except Exception as e:
        return False, f"Validation error: {e!s}"
```

**Implementation Steps**:
1. Enhance the basic validation with more comprehensive checks
2. Add better error reporting
3. Add tests for various validation scenarios

## Medium Priority (P2) Fixes

### Fix 6.1: Consistent Usage Metadata Handling

**Suggested Fix**:
```python
def _normalize_usage_metadata(self, usage: dict[str, Any], source_format: str) -> dict[str, Any]:
    """Normalize usage metadata from different API formats to a standard structure."""
    if source_format == "gemini":
        return {
            "prompt_tokens": usage.get("promptTokenCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0),
        }
    elif source_format == "anthropic":
        return {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        }
    elif source_format in {"openai", "openai-responses"}:
        return {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
    else:
        # Default normalization
        return {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
```

**Implementation Steps**:
1. Create a normalization method for usage metadata
2. Update all response translation methods to use this normalization
3. Add tests for different API formats

### Fix 5.1: Consistent Stop Sequence Handling

**Suggested Fix**:
```python
def _normalize_stop_sequences(self, stop: Any) -> list[str] | None:
    """Normalize stop sequences to a consistent format."""
    if stop is None:
        return None
    
    if isinstance(stop, str):
        return [stop]
    
    if isinstance(stop, list):
        # Ensure all elements are strings
        return [str(s) for s in stop]
    
    # Convert other types to string
    return [str(stop)]
```

**Implementation Steps**:
1. Create a helper method to normalize stop sequences
2. Update all translation methods to use this normalization
3. Add tests for various stop sequence formats

## Low Priority (P3) Fixes

### Fix 8.1: Reduce Code Duplication

**Suggested Fix**:
```python
# Create a base translation class with common functionality
class BaseTranslator:
    """Base class for API translators with common functionality."""
    
    def _extract_text_content(self, content: Any) -> str:
        """Extract text content from various content formats."""
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
            return " ".join(text_parts)
        return str(content)
    
    def _validate_and_convert_messages(self, messages: list[Any]) -> list[dict[str, Any]]:
        """Validate and convert messages to a standard format."""
        validated_messages = []
        for message in messages:
            if not hasattr(message, "role") or not message.role:
                continue
            
            validated_message = {
                "role": message.role,
                "content": self._extract_text_content(getattr(message, "content", "")),
            }
            
            # Add other fields if present
            for field in ["name", "tool_calls", "tool_call_id"]:
                if hasattr(message, field):
                    validated_message[field] = getattr(message, field)
            
            validated_messages.append(validated_message)
        
        return validated_messages
```

**Implementation Steps**:
1. Create a base translator class with common functionality
2. Refactor existing translators to inherit from this base class
3. Move common methods to the base class
4. Add tests for the base class functionality

### Fix 8.2: Add Missing Type Hints

**Suggested Fix**:
```python
# Add type hints to all methods
def to_domain_request(
    self, request: Any, source_format: str
) -> CanonicalChatRequest:
    """
    Translates an incoming request from a specific API format to the internal domain ChatRequest.
    
    Args:
        request: The request object in the source format.
        source_format: The source API format (e.g., "anthropic", "gemini").
    
    Returns:
        A ChatRequest object.
    
    Raises:
        ValueError: If the source format is not supported.
        TypeError: If the request object is not in the expected format.
    """
```

**Implementation Steps**:
1. Add type hints to all method signatures
2. Add type hints to internal variables
3. Add return type annotations
4. Run mypy to verify type correctness

## Test Coverage Improvements

### Fix 9.1: Comprehensive Test Coverage

**Suggested Fix**:
```python
# Add tests for edge cases and error conditions
class TestTranslationEdgeCases:
    def test_malformed_json_in_tool_calls(self):
        """Test handling of malformed JSON in tool calls."""
        
    def test_invalid_image_urls(self):
        """Test handling of invalid image URLs."""
        
    def test_missing_required_fields(self):
        """Test handling of missing required fields."""
        
    def test_streaming_error_conditions(self):
        """Test handling of streaming error conditions."""
```

**Implementation Steps**:
1. Identify untested code paths and edge cases
2. Create comprehensive test cases for these scenarios
3. Add property-based tests for validation
4. Set up test coverage reporting

## Implementation Strategy

1. **Phase 1 (Critical)**:
   - Implement fixes for bugs 1.1, 2.1, and 3.1
   - Add comprehensive tests for these fixes
   - Set up monitoring to detect issues

2. **Phase 2 (High)**:
   - Implement fixes for bugs 1.2, 4.1, 5.2, and 7.1
   - Refactor error handling throughout the codebase
   - Add validation methods

3. **Phase 3 (Medium)**:
   - Implement fixes for bugs 6.1, 5.1, 7.2, and 3.2
   - Create normalization methods for consistent behavior
   - Add integration tests

4. **Phase 4 (Low)**:
   - Implement fixes for bugs 8.1, 8.2, and others
   - Refactor code to reduce duplication
   - Add comprehensive type hints

5. **Phase 5 (Testing)**:
   - Improve test coverage to >90%
   - Add property-based tests
   - Set up continuous integration with coverage reporting

Each fix should be implemented with proper tests before deployment to ensure the fix works as expected and doesn't introduce regressions.