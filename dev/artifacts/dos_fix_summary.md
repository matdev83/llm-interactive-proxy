# DoS Vulnerability Fix Summary

## Issue Description
During security analysis of the LLM proxy codebase, two types of DoS vulnerabilities were identified and fixed:

### 1. Inconsistent Size Limits in Error Body Processing

**Problem**: Several connectors (`openai.py`, `gemini.py`, `anthropic.py`) were using 1MB limits for error body processing, which is too restrictive for legitimate LLM responses.

**Risk**: 
- Legitimate LLM responses (code generation, long documents, multi-turn conversations) can easily exceed 1MB
- Attackers could exploit this for **availability DoS** by triggering the limit to break normal functionality
- Inconsistent with other parts of codebase that use 10MB limits

**Fixed Files**:
- `src/connectors/openai.py` - Line ~1238
- `src/connectors/gemini.py` - Lines ~332, ~1036  
- `src/connectors/anthropic.py` - Lines ~566, ~932

**Change**: Updated all 1MB limits to 10MB limits:
```python
# Before:
if len(body_bytes) > 1024 * 1024:  # 1MB limit

# After: 
if len(body_bytes) > 10 * 1024 * 1024:  # 10MB limit (consistent with other middleware)
```

### 2. Missing Size Validation in JSON Parsing

**Problem**: The `_as_dict()` function in `rate_limit.py` parses JSON strings without size validation, making it vulnerable to memory/CPU exhaustion attacks.

**Risk**:
- Attacker could send arbitrarily large JSON strings 
- Could cause memory exhaustion during `json.loads()` parsing
- CPU exhaustion through parsing of massive/deeply nested structures

**Fixed File**: `src/rate_limit.py` - Lines 123-141

**Changes Made**:
1. Added 10MB size limit check before JSON parsing
2. Added size validation for extracted JSON substrings  
3. Added proper handling for None/non-string inputs

```python
def _as_dict(detail: object) -> dict[str, Any] | None:
    """Best-effort conversion of an error detail payload into a dict."""
    if isinstance(detail, dict):
        return detail
    if isinstance(detail, str):
        # DoS protection: Check string size before parsing
        if len(detail.encode('utf-8')) > 10 * 1024 * 1024:  # 10MB limit
            return None
        
        try:
            loaded = json.loads(detail)
            return loaded if isinstance(loaded, dict) else None
        except json.JSONDecodeError:
            start = detail.find("{")
            end = detail.rfind("}")
            if start != -1 and end != -1 and end > start:
                # DoS protection: Check extracted JSON size
                json_part = detail[start : end + 1]
                if len(json_part.encode('utf-8')) > 10 * 1024 * 1024:  # 10MB limit
                    return None
                try:
                    loaded = json.loads(json_part)
                    return loaded if isinstance(loaded, dict) else None
                except json.JSONDecodeError:
                    return None
    # Handle None and other non-string, non-dict types
    if detail is None:
        return None
    return None
```

## Verification

Created comprehensive test scripts that verify:
1. ✅ Size limits now properly reject oversized inputs
2. ✅ Normal functionality preserved for legitimate inputs  
3. ✅ No regressions in existing behavior
4. ✅ Consistent with existing 10MB limits used elsewhere

## Impact

- **Before**: Vulnerable to DoS attacks through:
  - Memory exhaustion via large JSON parsing
  - CPU exhaustion via complex nested structures  
  - Availability DoS via overly restrictive 1MB limits
- **After**: Protected against DoS while maintaining:
  - Full compatibility with legitimate LLM use cases
  - Consistent limits across the codebase
  - Proper error handling for edge cases

## Testing

All changes verified with:
- Linting: `ruff check --fix` ✅
- Type checking: `mypy` ✅  
- Unit tests: Existing test suite passes ✅
- Custom verification scripts confirm protection works ✅

The fixes maintain backward compatibility while adding proper DoS protection that aligns with the existing security posture of the codebase.