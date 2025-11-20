# Usage Tracking Audit - All Backend Connectors

## Objective
Ensure ALL backend connectors properly handle usage/billing information:
1. Request usage info from backends (via headers or API-specific methods)
2. Calculate usage on proxy level if missing from upstream
3. Return accurate usage to clients

## Backend Connectors Inventory

### OpenAI-Compatible Backends
1. **OpenAIConnector** (`openai.py`) - Base class
2. **ClineConnector** (`cline.py`) - Extends OpenAI
3. **ZenmuxConnector** (`zenmux.py`) - Extends OpenAI
4. **OpenRouterBackend** (`openrouter.py`) - Extends OpenAI
5. **ZaiCodingPlanBackend** (`zai_coding_plan.py`) - Extends OpenAI
6. **OpenAICodexConnector** (`openai_codex.py`) - Extends OpenAI

### Anthropic Backends
7. **AnthropicBackend** (`anthropic.py`)
8. **AnthropicOAuthBackend** (`anthropic_oauth.py`) - Extends Anthropic

### Gemini Backends
9. **GeminiBackend** (`gemini.py`) - Base class
10. **GeminiOAuthBaseConnector** (`gemini_oauth_base.py`) - Base for OAuth variants
11. **GeminiOAuthFreeConnector** (`gemini_oauth_free.py`)
12. **GeminiOAuthPlanConnector** (`gemini_oauth_plan.py`)
13. **GeminiCloudProjectConnector** (`gemini_cloud_project.py`)
14. **GeminiCliAcpConnector** (`gemini_cli_acp.py`)

### Other Backends
15. **QwenOAuthConnector** (`qwen_oauth.py`)
16. **MinimaxConnector** (`minimax.py`)
17. **ZaiBackend** (`zai.py`)
18. **HybridConnector** (`hybrid.py`) - Special case (orchestrates other backends)
19. **OpenAIResponsesConnector** (`openai_responses.py`)

## Audit Results

### ✅ Already Handling Usage Correctly

#### OpenAI-Compatible (via OpenAIConnector base)
- **OpenAIConnector**: Returns usage in ResponseEnvelope ✓
- **ClineConnector**: Inherits from OpenAI ✓
- **ZenmuxConnector**: Inherits from OpenAI ✓
- **OpenRouterBackend**: Inherits from OpenAI ✓
- **ZaiCodingPlanBackend**: Inherits from OpenAI ✓

#### Anthropic
- **AnthropicBackend**: Returns usage in ResponseEnvelope ✓
- **AnthropicOAuthBackend**: Inherits from Anthropic ✓

#### Qwen
- **QwenOAuthConnector**: Has `_calculate_token_usage()` method ✓
  - Calculates usage when missing or zero
  - Uses tiktoken for accurate counting

### ⚠️ Needs Verification

#### Gemini Backends
- **GeminiBackend**: Need to verify usage handling
- **GeminiOAuthBaseConnector**: Need to verify usage handling
- **GeminiOAuthFreeConnector**: Test shows tiktoken usage calculation ✓
- **GeminiOAuthPlanConnector**: Need to verify
- **GeminiCloudProjectConnector**: Need to verify
- **GeminiCliAcpConnector**: Need to verify

#### Other
- **MinimaxConnector**: Need to verify
- **ZaiBackend**: Need to verify
- **HybridConnector**: Special case - orchestrates other backends
- **OpenAICodexConnector**: Need to verify
- **OpenAIResponsesConnector**: Need to verify

## Implementation Strategy

### Phase 1: Add Usage Calculation to Base Classes ✓
- [x] Add automatic recalculation in `response_adapters.py`
- [x] Create `usage_recalculation.py` utility
- [x] Test with Cline and ZenMux

### Phase 2: Ensure All Connectors Return Usage
For each connector that doesn't return usage:
1. Check if backend API provides usage
2. If yes: Ensure we request it (headers, API params)
3. If no: Calculate using tiktoken on proxy level
4. Return usage in ResponseEnvelope

### Phase 3: Add Fallback Usage Calculation
Create a mixin or base class method that:
1. Checks if usage is present in response
2. If missing or zero, calculates using tiktoken
3. Returns ResponseEnvelope with usage

### Phase 4: Comprehensive Testing
- Test each connector for usage reporting
- Test with missing usage from backend
- Test with zero usage from backend
- Test with partial usage (some fields zero)

## Required Headers/API Settings

### OpenAI-Compatible APIs
- No special headers needed
- Usage is in response body by default

### Anthropic
- No special headers needed
- Usage is in response body (`usage` field)

### Gemini
- Usage in response as `usageMetadata`
- May need to enable in API settings

### Qwen
- Usage may be missing in some responses
- Already has fallback calculation ✓

## Next Steps

1. **Audit Gemini connectors** - Verify usage handling
2. **Audit Minimax connector** - Verify usage handling
3. **Audit ZAI connector** - Verify usage handling
4. **Create base mixin** - For automatic usage calculation
5. **Add comprehensive tests** - For all connectors
6. **Document requirements** - For each backend API

## Success Criteria

- [ ] All connectors return usage in ResponseEnvelope
- [ ] Usage is calculated if missing from backend
- [ ] Usage is recalculated after proxy transformations
- [ ] All connectors have tests for usage reporting
- [ ] Documentation updated for each connector
