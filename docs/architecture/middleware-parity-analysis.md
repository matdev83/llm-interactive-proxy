# Middleware Streaming/Non-Streaming Parity Analysis

This document analyzes all response middleware in the codebase to identify feature parity gaps between streaming and non-streaming code paths.

## Summary Table

| Middleware | Streaming | Non-Streaming | Parity Status | Notes |
|------------|-----------|---------------|---------------|-------|
| ResponseLoggingMiddleware | Yes | Yes | FULL | Pass-through logging |
| ContentFilterMiddleware | Yes | Yes | FULL | Prefix filtering |
| LoopDetectionMiddleware | Yes | Yes | FULL | Accumulates per session |
| ThinkTagsFixMiddleware | Yes | Yes | PARTIAL | Different logic paths |
| EditPrecisionResponseMiddleware | Yes | Yes | FULL | Same logic for both |
| ToolCallReactorMiddleware | Yes | Yes | PARTIAL | Different lifecycle handling |
| EmptyResponseMiddleware | No | Yes | GAP | Skips streaming entirely |
| StructuredOutputMiddleware | No | Yes | GAP | Skips streaming entirely |
| JsonRepairMiddleware | No | Yes | GAP | Skips streaming, uses processor |
| ToolCallRepairMiddleware | N/A | N/A | N/A | Disabled (pass-through) |

## Detailed Analysis

### FULL PARITY (No Changes Needed)

#### ResponseLoggingMiddleware
- **Location**: `src/core/services/response_middleware.py`
- **Feature**: Logs response details
- **Parity**: Both paths perform identical logging
- **Migration Priority**: Low (demonstration only)

#### ContentFilterMiddleware
- **Location**: `src/core/services/response_middleware.py`
- **Feature**: Filters specific prefix from content
- **Parity**: Both paths apply same filter logic
- **Migration Priority**: Low

#### LoopDetectionMiddleware
- **Location**: `src/core/services/response_middleware.py`
- **Feature**: Detects repetitive content patterns
- **Parity**: Both paths use same detection logic (accumulates content)
- **Migration Priority**: Medium

#### EditPrecisionResponseMiddleware
- **Location**: `src/core/services/edit_precision_response_middleware.py`
- **Feature**: Detects edit failures and flags for retry
- **Parity**: Same detection logic for both paths
- **Migration Priority**: Medium

### PARTIAL PARITY (Different Logic Paths)

#### ThinkTagsFixMiddleware
- **Location**: `src/core/services/think_tags_fix_middleware.py`
- **Feature**: Extracts reasoning from `<think>` tags
- **Streaming**: Uses `_process_streaming_chunk()` with buffering
- **Non-streaming**: Uses direct extraction
- **Gap**: Logic differs significantly but achieves same result
- **Migration Priority**: High (complex streaming state)

#### ToolCallReactorMiddleware
- **Location**: `src/core/services/tool_call_reactor_middleware.py`
- **Feature**: Reacts to tool calls in responses
- **Streaming**: Uses buffer state, different lifecycle
- **Non-streaming**: Clears stream state immediately
- **Gap**: Lines 100-102 clear state for non-streaming only
- **Migration Priority**: High

### PARITY GAPS (Missing Streaming Support)

#### EmptyResponseMiddleware
- **Location**: `src/core/services/empty_response_middleware.py`
- **Feature**: Detects empty responses, triggers retry
- **Streaming**: Returns immediately (lines 250-253)
- **Non-streaming**: Full detection and retry logic
- **Gap**: Streaming responses skip empty detection entirely
- **Required Fix**: Implement streaming accumulation for empty detection
- **Migration Priority**: HIGH

#### StructuredOutputMiddleware
- **Location**: `src/core/services/structured_output_middleware.py`
- **Feature**: JSON schema validation and repair
- **Streaming**: Skips entirely (lines 77-84)
- **Non-streaming**: Full validation
- **Gap**: No streaming schema validation
- **Required Fix**: Accumulate streaming content, validate on completion
- **Migration Priority**: HIGH

#### JsonRepairMiddleware
- **Location**: `src/core/app/middleware/json_repair_middleware.py`
- **Feature**: Repairs malformed JSON
- **Streaming**: Returns immediately (lines 46-47)
- **Non-streaming**: Full repair logic
- **Gap**: Uses separate JsonRepairProcessor for streaming
- **Required Fix**: Unify with IResponseFeature pattern
- **Migration Priority**: MEDIUM (has separate processor)

## Migration Strategy

### Phase 1: Foundation (Complete)
- Created `IResponseFeature` interface with explicit `process_streaming()` / `process_non_streaming()` methods
- Created `FeatureParityRegistry` for tracking feature support across both paths
- Created `MiddlewareToFeatureAdapter` and `FeatureToMiddlewareAdapter` for bridging interfaces
- Added `FeatureCapability` constants: `BOTH`, `STREAMING`, `NON_STREAMING`

### Phase 2: Core Features (Complete)
Migrated middleware with straightforward logic to IResponseFeature:
- `ResponseLoggingMiddleware` -> `ResponseLoggingFeature` ✅
- `ContentFilterMiddleware` -> `ContentFilterFeature` ✅
- `LoopDetectionMiddleware` -> `LoopDetectionFeature` ✅

### Phase 3: Gap Fixes (Complete)
Added streaming support to middleware that previously lacked it:
- `EmptyResponseMiddleware` -> `EmptyResponseFeature` ✅
  - Added stream activity tracking per session
  - Detects empty streams at completion and sets `empty_stream_detected` metadata
- `StructuredOutputMiddleware` -> `StructuredOutputFeature` ✅
  - Added streaming content accumulation
  - Validates complete JSON at stream end
- `JsonRepairMiddleware` -> `JsonRepairFeature` ✅
  - Added streaming content accumulation  
  - Repairs complete JSON at stream end

### Phase 4: Complex Middleware (Deferred)
The following middleware have complex streaming state management and are deferred from full migration:
- `ThinkTagsFixMiddleware` - 700+ lines with sophisticated buffer management
- `ToolCallReactorMiddleware` - Complex lifecycle state handling
- `EditPrecisionResponseMiddleware` - Already has full parity

These can be wrapped using `MiddlewareToFeatureAdapter` for registry integration.

### Phase 5: Registration Infrastructure (Complete)
Created `src/core/services/feature_parity_registration.py` with:
- `register_all_features()` - Registers known features at startup
- `register_middleware_instance()` - Runtime middleware registration
- `register_feature_instance()` - Runtime feature registration
- `get_parity_report()` - Generates parity report
- `verify_parity()` - Verifies parity with optional strict mode

## Verification

After registration, verify parity using:
```python
from src.core.services.feature_parity_registration import (
    register_all_features,
    get_parity_report,
    verify_parity,
)

# Register all known features
register_all_features()

# Get parity report
print(get_parity_report())

# Verify parity (raises on error-level violations if strict=True)
violations = verify_parity(strict=False)
for v in violations:
    print(f"{v.severity}: {v.feature_name} - {v.description}")
```

## New Files Created

| File | Purpose |
|------|---------|
| `src/core/interfaces/feature_parity.py` | Registry, adapters, violation types |
| `src/core/services/feature_parity_registration.py` | Registration utilities |
| `tests/unit/core/test_feature_parity.py` | Unit tests for parity infrastructure |

## Updated Files

| File | Changes |
|------|---------|
| `src/core/interfaces/response_processor_interface.py` | Added `IResponseFeature`, `FeatureCapability` |
| `src/core/services/response_middleware.py` | Added Feature versions of middleware |
| `src/core/services/empty_response_middleware.py` | Added `EmptyResponseFeature` |
| `src/core/services/structured_output_middleware.py` | Added `StructuredOutputFeature` |
| `src/core/app/middleware/json_repair_middleware.py` | Added `JsonRepairFeature` |

