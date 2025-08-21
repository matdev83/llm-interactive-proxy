# TODO: Improve Return Type Handling in Connectors

## Problem Statement
The current codebase has inconsistent return types from different connectors, which creates complex type checking logic in the backend service. Some connectors return tuples, while others return proper ResponseEnvelope objects. This inconsistency requires complex handling in the backend service.

## Goals
1. Ensure all connectors return consistent types (ResponseEnvelope | StreamingResponseEnvelope)
2. Simplify the complex return type handling in backend_service.py
3. Remove special case handling in connector implementations
4. Maintain backward compatibility

## Task List

### 1. Analyze Current Connector Return Types
- [x] Review all connector implementations to identify current return type patterns
- [x] Document inconsistencies in return types

### 2. Update OpenAI Connector
- [x] Modify `_handle_non_streaming_response` to return `ResponseEnvelope` instead of tuple
- [x] Update `chat_completions` method to handle the new return type properly
- [x] Ensure all return paths return consistent types

### 3. Update ZAI Connector
- [x] Remove special handling for different return types since parent will now return consistent types
- [x] Simplify the `chat_completions` method to directly return the parent's result

### 4. Update OpenRouter Connector
- [x] Remove complex type checking and special handling
- [x] Simplify to directly return the parent's result

### 5. Update Qwen OAuth Connector
- [x] Remove complex error handling that creates custom ResponseEnvelope
- [x] Ensure consistent return types with proper error propagation

### 6. Update Anthropic Connector
- [x] Modify `_handle_non_streaming_response` to return `ResponseEnvelope` instead of tuple
- [x] Update `chat_completions` method to handle the new return type properly

### 7. Update Gemini Connector
- [x] Already returns consistent types, but verify all paths return proper ResponseEnvelope

### 8. Simplify Backend Service
- [x] Remove complex type checking logic in `call_completion` method
- [x] Simplify the result processing logic since all connectors will return consistent types

### 9. Update Tests
- [x] Update any tests that expect the old return types
- [x] Verify all tests pass with the new consistent return types

### 10. Documentation
- [x] Update any documentation that references the old return type patterns
- [x] Document the new consistent return type approach