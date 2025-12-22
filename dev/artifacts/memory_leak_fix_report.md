# Memory Leak Fix - ThoughtSignatureManager

## Problem
The ThoughtSignatureManager in `src/connectors/gemini_base/thought_signature_manager.py` had a memory leak in its secondary index `_by_tool_call`. When the same `tool_call_id` appeared across different sessions, the cleanup logic failed to properly remove stale entries from the secondary index.

## Root Cause
The buggy cleanup logic was:
```python
self._by_tool_call = {
    k: v
    for k, v in self._by_tool_call.items()
    if v != oldest_sig or any(k2.endswith(f":{k}") for k2 in self._cache)
}
```

This logic failed when:
1. Same `tool_call_id` is used across multiple sessions (e.g., `session1:tool_a` and `session2:tool_a`)
2. The oldest entry is removed, but the condition `v != oldest_sig` could be `False` while `any(k2.endswith(f":{k}"))` is `True`
3. This kept the stale signature reference in the secondary index even though it no longer existed in the primary cache

## Fix
Replaced the flawed conditional logic with a simple rebuild approach:
```python
# Rebuild secondary index from remaining cache
new_by_tool_call = {}
for cache_key, (sig, _) in self._cache.items():
    tc_id = cache_key.split(":", 1)[1] if ":" in cache_key else cache_key
    new_by_tool_call[tc_id] = sig
self._by_tool_call = new_by_tool_call
```

This ensures the secondary index always matches the primary cache contents.

## Files Modified
- `src/connectors/gemini_base/thought_signature_manager.py` (lines 200-210, 293-304, 315-326)

## Verification
Created reproduction scripts that confirmed:
1. **Before fix**: Secondary index accumulated stale entries, causing unbounded memory growth
2. **After fix**: Secondary index stays synchronized with primary cache, no memory leak

## Impact
- Fixes memory leak that could accumulate unbounded stale entries
- Maintains all existing functionality
- No performance impact (rebuild is O(N) same as original logic)
- All existing tests pass