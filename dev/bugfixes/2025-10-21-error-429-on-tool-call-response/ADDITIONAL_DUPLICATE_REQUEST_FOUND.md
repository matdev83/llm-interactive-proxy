# CRITICAL: Additional Duplicate Request Pattern Found

## Summary

**URGENT**: The same duplicate request pattern that was causing 429 errors in `gemini_oauth_base.py` has been found in `src/connectors/gemini_cloud_project.py`.

## Duplicate Request Pattern in gemini_cloud_project.py

### First Request (Non-streaming):
- **Location**: Lines 1225-1233 in `_chat_completions_standard()`
- **Purpose**: Makes complete API call with `alt=sse` parameter
- **Issue**: Consumes full quota for the request

### Second Request (Streaming):
- **Location**: Lines 1389-1397 in `_chat_completions_streaming()`  
- **Purpose**: Makes identical API call with `stream=True`
- **Issue**: Consumes additional quota for the same request

## Impact

This means **ALL Gemini Cloud Project backend users** are experiencing:
- **2x quota consumption** per request
- **Rate limiting issues** after several exchanges
- **429 errors** mid-session when limits are hit
- **HTTP 502 errors** on client side

## Affected Backends

1. ✅ **gemini_oauth_base.py** - FIXED
2. ❌ **gemini_cloud_project.py** - NEEDS FIX
3. ✅ **gemini.py** - Uses different pattern (no duplicate requests)
4. ✅ **gemini_cli_acp.py** - Uses different pattern (no duplicate requests)
5. ✅ **gemini_oauth_free.py** - Inherits from gemini_oauth_base.py (fixed)
6. ✅ **gemini_oauth_plan.py** - Inherits from gemini_oauth_base.py (fixed)

## Required Action

The `gemini_cloud_project.py` connector needs the same fix applied:
1. Remove the duplicate non-streaming request in `_chat_completions_standard()`
2. Use only the streaming request for both streaming and non-streaming modes
3. Update token calculation logic

## Priority

**HIGH PRIORITY** - This affects enterprise users with GCP projects who are likely to hit quota limits faster due to higher usage patterns.