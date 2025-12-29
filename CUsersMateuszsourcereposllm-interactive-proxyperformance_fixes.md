# Performance Optimization Plan

## Selected Targets (3 total)

### 1. gemini_cloud_project.py:1593
- **Issue**: Char-by-char string concatenation (`line_buffer += char`) in byte-by-byte streaming loop
- **Impact**: O(n²) behavior for line building; called for every byte in stream
- **Fix**: Use list accumulator + join
- **File**: src/connectors/gemini_cloud_project.py

### 2. gemini_cli_acp.py:720
- **Issue**: String concatenation (`full_response += content`) in async streaming chunk loop
- **Impact**: O(n²) for response assembly; called per chunk
- **Fix**: Use list accumulator + join
- **File**: src/connectors/gemini_cli_acp.py

### 3. gemini_base/streaming_executor.py:568,575
- **Issue**: String concatenation (`generated_text += text_piece`, `error_json_buffer += text_piece`) in streaming hot path
- **Impact**: O(n²) for text accumulation; called per streaming chunk
- **Fix**: Use list accumulator + join (need to handle two separate buffers)
- **File**: src/connectors/gemini_base/streaming_executor.py

## Implementation Order
1. gemini_cloud_project.py (simplest - single buffer)
2. gemini_cli_acp.py (single buffer, async context)
3. gemini_base/streaming_executor.py (two buffers, complex logic)

## Test Strategy
- Find related tests in tests/ for each connector
- Run baseline (pre-change)
- Apply fix
- Run post-change
- Verify behavior identical
