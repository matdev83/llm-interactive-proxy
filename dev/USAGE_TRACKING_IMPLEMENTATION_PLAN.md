# Usage Tracking Implementation Plan

## Summary
Systematic implementation to ensure ALL backend connectors properly handle usage/billing information.

## Completed ✓

### Phase 1: Core Infrastructure
- [x] Created `usage_recalculation.py` utility for post-transformation recalculation
- [x] Updated `response_adapters.py` to automatically recalculate usage
- [x] Updated header filtering to allow provider-specific headers
- [x] Created `UsageCalculationMixin` for connectors
- [x] Comprehensive tests (33 tests passing)

### Phase 2: Initial Connectors
- [x] Cline connector - Headers forwarded, usage recalculated
- [x] ZenMux connector - Headers forwarded, usage recalculated
- [x] OpenAI connector - Already returns usage correctly
- [x] Anthropic connector - Already returns usage correctly

## In Progress 🔄

### Phase 3: Audit Remaining Connectors

#### High Priority (User-Facing)
1. **QwenOAuthConnector** - Has calculation, verify it works
2. **GeminiOAuthPlanConnector** - Verify usage handling
3. **GeminiOAuthFreeConnector** - Has tiktoken calculation, verify
4. **OpenRouterBackend** - Inherits OpenAI, should work
5. **MinimaxConnector** - Need to audit

#### Medium Priority
6. **ZaiBackend** - Need to audit
7. **ZaiCodingPlanBackend** - Inherits OpenAI, should work
8. **GeminiCloudProjectConnector** - Need to audit
9. **GeminiCliAcpConnector** - Need to audit
10. **OpenAICodexConnector** - Need to audit

#### Low Priority (Special Cases)
11. **HybridConnector** - Orchestrates other backends
12. **OpenAIResponsesConnector** - Need to audit

## Implementation Steps

### For Each Connector:

1. **Audit Current State**
   ```python
   # Check if connector returns usage in ResponseEnvelope
   # Check if usage is None, zero, or missing
   ```

2. **Add Usage Calculation**
   ```python
   # Option A: Use UsageCalculationMixin
   class MyConnector(LLMBackend, UsageCalculationMixin):
       async def chat_completions(self, ...):
           result = await super().chat_completions(...)
           return self.ensure_usage_in_response(result, messages, model)
   
   # Option B: Implement custom calculation
   def _calculate_token_usage(self, response, messages, model):
       # Custom logic for this backend
   ```

3. **Request Usage from Backend**
   ```python
   # Add headers or API parameters to request usage
   headers = {
       "X-Request-Usage": "true",  # Example
       # Backend-specific headers
   }
   ```

4. **Add Tests**
   ```python
   # Test usage is returned
   # Test usage is calculated when missing
   # Test usage is calculated when zero
   ```

## Backend-Specific Requirements

### OpenAI-Compatible APIs
- **Headers**: None required
- **Response**: Usage in `usage` field
- **Status**: ✓ Working

### Anthropic
- **Headers**: None required
- **Response**: Usage in `usage` field
- **Status**: ✓ Working

### Gemini
- **Headers**: May need API key with usage enabled
- **Response**: Usage in `usageMetadata`
- **Action**: Verify all Gemini connectors

### Qwen
- **Headers**: None required
- **Response**: May be missing
- **Status**: Has fallback calculation ✓

### Minimax
- **Headers**: Unknown
- **Response**: Unknown
- **Action**: Audit and implement

### ZAI
- **Headers**: Unknown
- **Response**: Unknown
- **Action**: Audit and implement

## Testing Strategy

### Unit Tests (Per Connector)
```python
@pytest.mark.asyncio
async def test_connector_returns_usage():
    """Test that connector returns usage in response."""
    
@pytest.mark.asyncio
async def test_connector_calculates_missing_usage():
    """Test that connector calculates usage when missing from backend."""
    
@pytest.mark.asyncio
async def test_connector_calculates_zero_usage():
    """Test that connector calculates usage when backend returns zeros."""
```

### Integration Tests
```python
@pytest.mark.asyncio
async def test_usage_recalculated_after_transformation():
    """Test that usage is recalculated after proxy transformations."""
```

## Success Metrics

- [ ] All 19 connectors return usage in ResponseEnvelope
- [ ] Usage is calculated if missing from backend (100% coverage)
- [ ] Usage is recalculated after transformations (100% coverage)
- [ ] All connectors have usage tests (100% coverage)
- [ ] Documentation updated for each connector

## Timeline

- **Week 1**: Audit all connectors, document current state
- **Week 2**: Implement usage calculation for high-priority connectors
- **Week 3**: Implement usage calculation for medium-priority connectors
- **Week 4**: Testing, documentation, and polish

## Notes

- Use `UsageCalculationMixin` for consistency
- Log when usage is calculated (for debugging)
- Preserve prompt_tokens when recalculating
- Use tiktoken for accurate token counting
- Handle both streaming and non-streaming responses
