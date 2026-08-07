## 2025-05-17 - TTLCache Iteration Overhead
**Learning:** In `RateLimitRegistry`, calling `list(self._until.items())` on a large `TTLCache` to iterate and clean up expired elements creates an unnecessary O(N) memory copy of all items and takes significantly longer than iterating the items generator directly.
**Action:** When tracking min/max or deleting stale elements from a dictionary, avoid casting `dict.items()` to a list. Instead, iterate over `.items()` directly, track keys to delete in a small list, and maintain a running min/max scalar value to eliminate intermediate list allocations.
