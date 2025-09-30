# Gemini Code Assist API - Supported Parameters

## Overview

The `gemini-cli-oauth-personal` and `gemini-cloud-project` backends use the Gemini **Code Assist API** (`/v1internal:streamGenerateContent`), which supports a comprehensive set of generation parameters.

## ✅ Supported Parameters

Based on the gemini-cli reference implementation and our translation layer, the following parameters are fully supported:

### Basic Generation Parameters

| Parameter | Type | Description | OpenAI Equivalent |
|-----------|------|-------------|-------------------|
| `temperature` | float | Controls randomness (0.0-2.0) | `temperature` |
| `topP` | float | Nucleus sampling threshold | `top_p` |
| `topK` | int | Top-k sampling limit | N/A (Gemini-specific) |
| `maxOutputTokens` | int | Maximum tokens to generate | `max_tokens` |
| `stopSequences` | string[] | Stop generation at these strings | `stop` |

### Advanced Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `candidateCount` | int | Number of response variations |
| `presencePenalty` | float | Penalize tokens based on presence |
| `frequencyPenalty` | float | Penalize tokens based on frequency |
| `seed` | int | Random seed for deterministic output |
| `responseLogprobs` | bool | Return log probabilities |
| `logprobs` | int | Number of log probs per token |

### Reasoning/Thinking Parameters

| Parameter | Type | Description | OpenAI Equivalent |
|-----------|------|-------------|-------------------|
| `thinkingConfig` | object | Configure reasoning behavior | Similar to `reasoning_effort` |
| `thinkingConfig.thinkingBudget` | int | Max reasoning tokens: -1=dynamic, 0=none, >0=limit | N/A |
| `thinkingConfig.includeThoughts` | bool | Include reasoning in output (default: true) | N/A |

**Important**: Gemini uses `thinkingBudget` (integer) not `reasoning_effort` (string):
- `-1` = Dynamic/unlimited (let model decide) - **recommended for "high" effort**
- `0` = No thinking/reasoning
- `512` = Low thinking budget (~"low" effort)
- `2048` = Medium thinking budget (~"medium" effort)
- `8192+` = High thinking budget

Our proxy automatically maps OpenAI's `reasoning_effort` ("low", "medium", "high") to appropriate `thinkingBudget` values.

### Structured Output Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `responseMimeType` | string | Force response format (e.g., "application/json") |
| `responseJsonSchema` | object | JSON schema for structured output |
| `responseSchema` | object | Alternative schema format |

### Multimodal Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `responseModalities` | string[] | Output modalities (e.g., ["text", "audio"]) |
| `mediaResolution` | string | Image/video resolution preference |
| `speechConfig` | object | Audio output configuration |
| `audioTimestamp` | bool | Include timestamps in audio |

### Routing Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `routingConfig` | object | Model routing preferences |
| `modelSelectionConfig` | object | Model selection strategy |

## How to Use Parameters

### Via CLI Flag (All Requests)

You can set a global thinking budget for **all requests** using the `--thinking-budget` CLI flag:

```bash
./.venv/Scripts/python.exe -m src.core.cli \
  --host 127.0.0.1 --port 8000 \
  --disable-auth \
  --default-backend gemini-cli-oauth-personal \
  --static-route gemini-cli-oauth-personal:gemini-2.5-pro \
  --thinking-budget 32768
```

This sets `thinkingBudget: 32768` for all requests, overriding any `reasoning_effort` values.

**Special values:**
- `-1` = Dynamic/unlimited (recommended for maximum reasoning)
- `0` = Disable reasoning/thinking
- `>0` = Max reasoning tokens (e.g., 32768)

### Via OpenAI-Compatible API

When using the proxy with OpenAI-compatible format, parameters are automatically translated:

```python
import openai

client = openai.OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="dummy"
)

response = client.chat.completions.create(
    model="gemini-2.5-pro",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Explain quantum computing"}
    ],
    # Standard OpenAI parameters (automatically translated)
    temperature=0.8,
    top_p=0.9,
    max_tokens=2048,
    stop=["END"],
    
    # Gemini-specific via extra_body
    extra_body={
        "topK": 40,  # Gemini-specific
        "thinkingConfig": {
            "thinkingBudget": -1,  # -1 = dynamic/unlimited
            "includeThoughts": True  # Include reasoning in output
        }
    }
)
```

### Via Anthropic-Compatible API

```python
import anthropic

client = anthropic.Anthropic(
    base_url="http://localhost:8000",
    api_key="dummy"
)

response = client.messages.create(
    model="gemini-2.5-pro",
    messages=[
        {"role": "user", "content": "Explain quantum computing"}
    ],
    temperature=0.7,
    max_tokens=1024,
    top_p=0.95,
    top_k=40  # Gemini-specific
)
```

## Implementation Details

### Translation Flow

1. **Request arrives** in OpenAI or Anthropic format
2. **Translation service** converts to canonical domain format
3. **Domain → Gemini** conversion creates `generationConfig`
4. **System role filtering** (Code Assist requirement)
5. **Code Assist wrapping** with project ID and user_prompt_id
6. **API call** to `/v1internal:streamGenerateContent`

### Code Assist Request Structure

```json
{
  "model": "gemini-2.5-pro",
  "project": "project-id-here",
  "user_prompt_id": "proxy-request",
  "request": {
    "contents": [...],
    "systemInstruction": {"role": "user", "parts": [...]},
    "generationConfig": {
      "temperature": 0.8,
      "topP": 0.9,
      "topK": 40,
      "maxOutputTokens": 2048,
      "stopSequences": ["END"],
      "thinkingConfig": {
        "thinkingBudget": -1,
        "includeThoughts": true
      },
      "presencePenalty": 0.5,
      "frequencyPenalty": 0.5,
      "seed": 12345
    },
    "tools": [...],
    "toolConfig": {...},
    "safetySettings": [...]
  }
}
```

## Current Implementation Status

✅ **Fully Implemented** in `src/core/domain/translation.py`:
- `temperature` (line 487)
- `topP` (line 485)
- `topK` (line 483)
- `maxOutputTokens` (line 489)
- `stopSequences` (line 491)
- `thinkingConfig` with `thinkingBudget` and `includeThoughts` (line 493-507)
  - Automatically maps OpenAI's `reasoning_effort` to `thinkingBudget`
  - "low" → 512 tokens, "medium" → 2048 tokens, "high" → -1 (dynamic)

✅ **Passed Through** via `generationConfig`:
- All parameters in the generationConfig are passed through to the Code Assist API
- The API supports all parameters listed in the gemini-cli reference

## Differences from Standard Gemini API

The Code Assist API (`/v1internal:streamGenerateContent`) differs from the standard Gemini API (`/v1beta:streamGenerateContent`):

1. **System Role**: Must use `systemInstruction` with `role: 'user'` (not 'system')
2. **Request Wrapping**: Requires `project`, `user_prompt_id`, and nested `request` object
3. **Authentication**: Uses OAuth or ADC (not API keys)
4. **Endpoint**: Different URL path (`v1internal` vs `v1beta`)

## Testing Parameters

You can test parameter support with:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-2.5-pro",
    "messages": [
      {"role": "user", "content": "Count to 10"}
    ],
    "temperature": 0.8,
    "top_p": 0.9,
    "max_tokens": 100,
    "extra_body": {
      "topK": 40,
      "thinkingConfig": {
        "thinkingBudget": 2048,
        "includeThoughts": true
      }
    }
  }'
```

## References

- **gemini-cli source**: `dev/thrdparty/gemini-cli-new/packages/core/src/code_assist/converter.ts`
- **Translation service**: `src/core/domain/translation.py` (line 476)
- **OAuth Personal backend**: `src/connectors/gemini_oauth_personal.py` (line 1199)
- **Cloud Project backend**: `src/connectors/gemini_cloud_project.py` (line 1036)

## Summary

**Yes, you can set custom model parameters including temperature, reasoning tokens (via `thinkingConfig`), and many other advanced parameters when using the `gemini-cli-oauth-personal` and `gemini-cloud-project` backends. The parameters are automatically translated from OpenAI/Anthropic format and passed through to the Code Assist API.**
