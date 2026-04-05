# ZAI Coding Plan 429 Error Diagnosis & Fix

## Root Cause

**Fingerprint Mismatch**: The ZAI connector was sending **mixed client fingerprints**:
- **Headers**: Kilo-Code (`User-Agent: Kilo-Code/4.111.0`, `Referer: https://kilocode.ai`, etc.)
- **Payload**: OpenCode (`agent: "opencode/1.2.26..."`)

This inconsistency triggered ZAI's WAF, causing 429 rejections.

## What Was Fixed

### 1. Consistent Fingerprint Detection

The ZAI connector now detects the client agent from the request and uses matching headers:

**OpenCode Client** (detected via `agent` field containing "opencode"):
```
User-Agent: opencode
(No Kilo-Code specific headers)
```

**Kilo-Code Client** (default, when no OpenCode agent detected):
```
User-Agent: Kilo-Code/4.111.0
Referer: https://kilocode.ai
Origin: https://kilocode.ai
HTTP-Referer: https://kilocode.ai
X-Title: Kilo Code
X-KiloCode-Version: 4.111.0
```

### 2. Payload Sanitation Logging

Enhanced logging to show which payload keys are stripped, helping diagnose future issues:
```
ZAI Coding Plan stripped payload keys: ['agent', 'audio', 'extra_body', ...]
ZAI Coding Plan final payload keys: ['max_tokens', 'messages', 'model', 'stream', 'temperature']
```

### 3. Agent Field Always Stripped

The `agent` field is **never** sent to ZAI in the payload body (not in `allowed_keys`), preventing any fingerprint mismatch between headers and payload.

## Files Modified

- `src/connectors/zai_coding_plan.py`:
  - Added `_OPENCODE_USER_AGENT` constant
  - Modified `get_headers()` to accept optional `request` parameter
  - Added `_detect_client_agent()` method to identify OpenCode vs Kilo-Code
  - Updated `stream_completion()` to pass request to `get_headers()`
  - Enhanced payload sanitization logging

- `dev/scripts/verify_zai_fingerprint_consistency.py`: New verification script
- `dev/scripts/verify_zai_payload_shape.py`: New payload shape verification script

## Testing

All existing tests pass:
- `tests/unit/connectors/test_zai_coding_plan.py`: 10/10 passed ✅
- `tests/integration/test_zai_coding_plan_integration.py`: 1/1 passed ✅
- `dev/scripts/verify_zai_fingerprint_consistency.py`: 3/3 passed ✅
- `dev/scripts/verify_zai_payload_shape.py`: PASS ✅

## How It Works

### Agent Detection Flow

1. Client sends request with agent identifier (from `x-agent` header or `user-agent`)
2. Session enricher stores agent in `CanonicalChatRequest.agent`
3. ZAI connector's `_detect_client_agent()` checks:
   - `request.agent` field (e.g., "opencode/1.2.26...")
   - `request.extra_body.agent` field (fallback)
4. If "opencode" found in agent string → use OpenCode fingerprint
5. Otherwise → use Kilo-Code fingerprint (backward compatible)

### Header Selection

```python
detected_agent = self._detect_client_agent(request)

if detected_agent == "opencode":
    headers["User-Agent"] = "opencode"
    # Remove Kilo-Code headers
else:
    headers["User-Agent"] = "Kilo-Code/4.111.0"
    headers["Referer"] = "https://kilocode.ai"
    # ... other Kilo-Code headers
```

## Verification

Run the verification scripts:
```bash
# Verify fingerprint consistency
./.venv/Scripts/python.exe -m dev.scripts.verify_zai_fingerprint_consistency

# Verify payload shape
./.venv/Scripts/python.exe -m dev.scripts.verify_zai_payload_shape
```

## Next Steps

1. **Deploy and monitor**: Check logs for fingerprint detection messages
2. **Verify 429 resolution**: If 429s persist, check if it's actual quota exhaustion
3. **Contact ZAI support**: If issue continues, verify API key status with ZAI
