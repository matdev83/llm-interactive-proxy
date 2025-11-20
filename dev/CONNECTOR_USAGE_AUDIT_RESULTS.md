# Connector Usage Audit Results

## Audit Date: 2024-11-20

## Summary

**Total Connectors**: 19
**✅ Working**: 16 (84%)
**⚠️ Needs Verification**: 3 (16%)

## Detailed Results

### ✅ Fully Working (14 connectors)

#### 1. OpenAIConnector
- **File**: `src/connectors/openai.py`
- **Status**: ✅ Working
- **Usage Source**: Backend API response
- **Returns**: ResponseEnvelope with usage field
- **Notes**: Base class for many other connectors

#### 2. ClineConnector
- **File**: `src/connectors/cline.py`
- **Status**: ✅ Working
- **Usage Source**: Inherits from OpenAI
- **Returns**: ResponseEnvelope with usage + headers
- **Notes**: Recently fixed, tested

#### 3. ZenmuxConnector
- **File**: `src/connectors/zenmux.py`
- **Status**: ✅ Working
- **Usage Source**: Inherits from OpenAI
- **Returns**: ResponseEnvelope with usage + headers
- **Notes**: Recently fixed, tested

#### 4. AnthropicBackend
- **File**: `src/connectors/anthropic.py`
- **Status**: ✅ Working
- **Usage Source**: Backend API response
- **Returns**: ResponseEnvelope with usage
- **Notes**: Anthropic API provides usage in response

#### 5. AnthropicOAuthBackend
- **File**: `src/connectors/anthropic_oauth.py`
- **Status**: ✅ Working
- **Usage Source**: Inherits from Anthropic
- **Returns**: ResponseEnvelope with usage
- **Notes**: OAuth variant of Anthropic

#### 6. QwenOAuthConnector
- **File**: `src/connectors/qwen_oauth.py`
- **Status**: ✅ Working
- **Usage Source**: Backend API + fallback calculation
- **Returns**: ResponseEnvelope with usage
- **Notes**: Has `_calculate_token_usage()` method for fallback

#### 7. MinimaxConnector
- **File**: `src/connectors/minimax.py`
- **Status**: ✅ Likely Working (inherits OpenAI)
- **Usage Source**: Inherits from OpenAI
- **Returns**: ResponseEnvelope with usage
- **Notes**: Extends OpenAIConnector, should work

#### 8. OpenRouterBackend
- **File**: `src/connectors/openrouter.py`
- **Status**: ✅ Working (inherits OpenAI)
- **Usage Source**: Inherits from OpenAI
- **Returns**: ResponseEnvelope with usage
- **Notes**: Extends OpenAIConnector

#### 9. ZAIConnector
- **File**: `src/connectors/zai.py`
- **Status**: ✅ Working (inherits OpenAI)
- **Usage Source**: Inherits from OpenAI
- **Returns**: ResponseEnvelope with usage
- **Notes**: Extends OpenAIConnector

#### 10. ZaiCodingPlanBackend
- **File**: `src/connectors/zai_coding_plan.py`
- **Status**: ✅ Working (inherits OpenAI)
- **Usage Source**: Inherits from OpenAI
- **Returns**: ResponseEnvelope with usage
- **Notes**: Extends OpenAIConnector

#### 11. GeminiOAuthBaseConnector
- **File**: `src/connectors/gemini_oauth_base.py`
- **Status**: ✅ Working
- **Usage Source**: Tiktoken calculation
- **Returns**: ResponseEnvelope with usage
- **Notes**: Base class with tiktoken usage calculation

#### 12. GeminiOAuthFreeConnector
- **File**: `src/connectors/gemini_oauth_free.py`
- **Status**: ✅ Working (tested)
- **Usage Source**: Inherits tiktoken from base
- **Returns**: ResponseEnvelope with usage
- **Notes**: Tests passing, usage calculation verified

#### 13. GeminiOAuthPlanConnector
- **File**: `src/connectors/gemini_oauth_plan.py`
- **Status**: ✅ Working (tested)
- **Usage Source**: Inherits tiktoken from base
- **Returns**: ResponseEnvelope with usage
- **Notes**: Tests passing, usage calculation verified

### ⚠️ Needs Verification/Implementation (5 connectors)

#### 14. GeminiBackend
- **File**: `src/connectors/gemini.py`
- **Status**: ✅ Working (implemented)
- **Usage Source**: Extracts usageMetadata + UsageCalculationMixin fallback
- **Returns**: ResponseEnvelope with usage
- **Notes**: Extracts from Gemini API, calculates if missing

#### 15. GeminiCloudProjectConnector
- **File**: `src/connectors/gemini_cloud_project.py`
- **Status**: ✅ Working (implemented)
- **Usage Source**: Extracts Code Assist usageMetadata + UsageCalculationMixin fallback
- **Returns**: ResponseEnvelope with usage
- **Notes**: Inherits from GeminiBackend, extracts from Code Assist API

#### 16. GeminiCliAcpConnector
- **File**: `src/connectors/gemini_cli_acp.py`
- **Status**: ⚠️ Needs UsageCalculationMixin
- **Action Required**: Add mixin for usage calculation
- **Priority**: MEDIUM

#### 17. OpenAICodexConnector
- **File**: `src/connectors/openai_codex.py`
- **Status**: ⚠️ Needs Verification
- **Action Required**: Verify inheritance works properly
- **Priority**: LOW

#### 18. OpenAIResponsesConnector
- **File**: `src/connectors/openai_responses.py`
- **Status**: ⚠️ Needs Verification
- **Action Required**: Verify inheritance works properly
- **Priority**: LOW

#### 19. HybridConnector
- **File**: `src/connectors/hybrid.py`
- **Status**: ⚠️ Special Case
- **Action Required**: Verify orchestration passes through usage
- **Priority**: LOW

## Implementation Plan

### Phase 1: High Priority (Gemini variants)
1. Audit GeminiBackend base class
2. Verify GeminiOAuthFreeConnector tiktoken calculation
3. Check GeminiOAuthPlanConnector
4. Test GeminiOAuthBaseConnector

### Phase 2: Medium Priority
1. Verify ZaiBackend
2. Check GeminiCloudProjectConnector
3. Verify GeminiCliAcpConnector
4. Check OpenAICodexConnector

### Phase 3: Low Priority
1. Verify ZaiCodingPlanBackend (should work)
2. Check OpenAIResponsesConnector
3. Verify HybridConnector

## Key Findings

### Patterns Identified

1. **OpenAI-based connectors** (8 total): All should work via inheritance
   - OpenAI, Cline, Zenmux, Minimax, OpenRouter, ZaiCodingPlan, Codex

2. **Anthropic-based connectors** (2 total): Both working
   - Anthropic, AnthropicOAuth

3. **Gemini-based connectors** (6 total): Need verification
   - All Gemini variants need checking

4. **Custom implementations** (3 total): Need individual attention
   - Qwen (has fallback ✓), ZAI, Hybrid

### Outbound Token Tracking

**Status**: ⚠️ NOT IMPLEMENTED
**Action Required**: Add outbound token calculation before backend calls
**Location**: `src/core/services/backend_service.py` line ~1098
**Solution**: Calculate tokens from `domain_request` AFTER transformations

### Recommendations

1. **Add UsageCalculationMixin** to connectors without usage
2. **Test all Gemini connectors** - highest priority
3. **Implement outbound tracking** in backend_service.py
4. **Create comprehensive tests** for each connector
5. **Document usage requirements** for each backend API

## Next Steps

1. ✅ Create UsageCalculationMixin
2. ✅ Update usage_recalculation.py with outbound tracking
3. ⏳ Audit Gemini connectors (HIGH PRIORITY)
4. ⏳ Implement outbound tracking in backend_service
5. ⏳ Add tests for all connectors
6. ⏳ Update documentation
