# Architectural Improvement: Consistent Return Types

## Overview

This document describes the architectural improvements made to ensure consistent return types across all connectors in the LLM Interactive Proxy system.

## Problem Statement

The original codebase had inconsistent return types from different connectors:
- Some connectors returned tuples of (dict, dict)
- Others returned proper ResponseEnvelope objects
- This inconsistency required complex type checking logic in the backend service

## Solution

We modified the Anthropic connector to return consistent types:

### Before
```python
async def _handle_non_streaming_response(
    self,
    url: str,
    payload: dict,
    headers: dict,
    model: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    # ... implementation
    return converted, dict(response.headers)
```

### After
```python
async def _handle_non_streaming_response(
    self,
    url: str,
    payload: dict,
    headers: dict,
    model: str,
) -> ResponseEnvelope:
    # ... implementation
    return ResponseEnvelope(
        content=converted, headers=dict(response.headers), status_code=response.status_code
    )
```

## Benefits

1. **Consistency**: All connectors now return the same types (`ResponseEnvelope | StreamingResponseEnvelope`)
2. **Simplified Code**: Removed complex type checking logic in the backend service
3. **Better Maintainability**: Easier to understand and maintain with consistent return types
4. **Type Safety**: Improved type safety with explicit return types
5. **Reduced Cognitive Load**: Developers no longer need to handle multiple return type patterns

## Impact

- All tests pass
- No breaking changes to the public API
- Improved code quality and maintainability
- Reduced complexity in the backend service

## Future Considerations

This improvement sets a precedent for consistent return types across the entire system. Future connector implementations should follow this pattern to maintain consistency.