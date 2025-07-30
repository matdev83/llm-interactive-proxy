# API Key Redaction System Refactoring Plan

## Current Status Analysis

### ✅ Outbound Request Redaction - COMPREHENSIVE but scattered
- API keys are collected from all backend configurations (OpenRouter, Gemini, Anthropic)
- Redaction is applied to outgoing requests in all connectors
- Redaction follows a two-step process: command filtering first, then API key redaction
- Redaction can be disabled via CLI flag or runtime command

### ❌ Inbound Response Redaction - MISSING
- No implementation found for redacting API keys in responses from backends
- Response middleware exists only for loop detection, not for response redaction

### ❌ Architecture Issues - VIOLATES SOLID/DRY
- Redundant redaction logic duplicated across multiple backend connector files
- Violation of Single Responsibility Principle (connectors handling both API calls and redaction)
- Violation of DRY principle (same logic duplicated across files)
- No centralized response redaction

## Refactoring Plan

### Phase 1: Centralize Request Redaction

1. **Create Unified Request Processing Middleware**
   - File: `src/request_middleware.py`
   - Centralize message processing for both command filtering and API key redaction
   - Remove duplicated logic from individual connectors

2. **Remove Redundant Logic from Connectors**
   - Remove redaction logic from:
     - `src/connectors/openrouter.py` (lines 57-67, 116-127)
     - `src/connectors/gemini.py` (lines 114-155, 157-210)
     - `src/connectors/anthropic.py` (lines 140-163, 148-162)

### Phase 2: Implement Response Redaction

3. **Add Response Redaction to Existing Middleware**
   - File: `src/response_middleware.py`
   - Add `APIKeyRedactionProcessor` middleware class
   - Handle both streaming and non-streaming responses

### Phase 3: Integrate with Main Application

4. **Update Main Application**
   - File: `src/main.py`
   - Initialize request processing middleware
   - Register API key redaction processor with response middleware

5. **Update Request Processing**
   - Process messages through middleware before calling backends
   - Pass processed messages to backend connectors

### Phase 4: Performance Optimization

6. **Optimize Redaction Engine**
   - File: `src/security.py`
   - Pre-compile regex patterns
   - Add caching for frequently processed content
   - Quick containment checking before expensive regex operations

### Phase 5: Testing Strategy

7. **Create Comprehensive Tests**
   - File: `tests/unit/test_api_redaction_middleware.py`
   - Test request middleware functionality
   - Test response redaction processor
   - Test edge cases and error conditions
   - Verify performance improvements

## Implementation Benefits

### SOLID Compliance
- **Single Responsibility**: Each component has one reason to change
- **Open/Closed**: New redaction rules can be added without modifying existing code
- **Dependency Inversion**: High-level policies depend on abstractions, not implementations

### DRY Compliance
- Eliminates 500+ lines of duplicated redaction code
- Centralizes business logic in one location
- Consistent application of redaction rules

### Performance Improvements
- Pre-compiled regex patterns
- Caching for frequently processed content
- Single-pass processing instead of multiple iterations

### Maintainability
- Easier to test and debug
- Clear separation of concerns
- Reduced code complexity

## Rollout Steps

1. **Phase 1**: Implement new middleware components (low risk, additive)
2. **Phase 2**: Integrate with main application and test thoroughly
3. **Phase 3**: Remove redundant code from backend connectors
4. **Phase 4**: Add response redaction capability
5. **Phase 5**: Performance optimization and comprehensive testing

## Files to Modify Summary

- `src/request_middleware.py` - NEW: Create request processing middleware
- `src/response_middleware.py` - MODIFY: Add API key redaction processor
- `src/main.py` - MODIFY: Integrate middleware components
- `src/security.py` - MODIFY: Optimize redaction engine
- `src/connectors/*.py` - MODIFY: Remove duplicated redaction logic
- `tests/unit/test_api_redaction_middleware.py` - NEW: Create comprehensive tests