# Design Document

## Overview

This design document describes the implementation of backend filtering functionality for the `inspect_cbor_capture.py` script. The feature allows developers to filter CBOR wire capture entries by backend name, enabling focused debugging of multi-backend scenarios.

## Architecture

The backend filter feature integrates into the existing argument parsing and entry filtering pipeline:

```
User Input (--backend, --list-backends)
    |
    v
Argument Parser
    |
    v
Load Capture File
    |
    v
Extract Backend Metadata
    |
    v
Filter Entries by Backend
    |
    v
Display Results (Summary, Entries, Analysis)
```

## Components and Interfaces

### 1. Backend Discovery Component

**Purpose**: Extract and catalog all unique backends present in a capture file.

**Interface**:
```python
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict


class CaptureEntryMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    be: str | None = None


class CaptureEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ts: float
    dir: int
    seq: int
    data: bytes
    meta: CaptureEntryMeta | None = None


class BackendCount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: str
    count: int


def get_unique_backends(entries: Sequence[CaptureEntry]) -> list[BackendCount]:
    """
    Extract unique backends from capture entries.
    
    Args:
        entries: List of typed capture entries
        
    Returns:
        List of backend/count pairs (sorted by count descending)
    """
```

**Behavior**:
- Iterates through all entries and extracts the `meta.be` (backend) field
- Counts occurrences of each backend
- Returns sorted dictionary by count (descending)
- Handles entries without backend metadata gracefully

### 2. Backend Filter Component

**Purpose**: Filter capture entries by backend name.

**Interface**:
```python
def filter_entries_by_backend(
    entries: Sequence[CaptureEntry],
    backend_name: str | None
) -> list[CaptureEntry]:
    """
    Filter entries by backend name.
    
    Args:
        entries: List of typed capture entries
        backend_name: Backend name to filter by, or None for no filtering
        
    Returns:
        Filtered list of entries
    """
```

**Behavior**:
- If `backend_name` is None, returns all entries unchanged
- If `backend_name` is specified, returns only entries where `meta.be == backend_name`
- Entries without backend metadata are excluded when filtering

### 3. Argument Parser Enhancement

**Changes to existing argument parser**:
- Add `--backend` / `-b` argument for filtering by backend name
- Add `--list-backends` / `-l` argument for discovering available backends
- Update help text with examples

### 4. Main Function Flow

**Enhanced flow**:
1. Parse arguments (including new `--backend` and `--list-backends`)
2. Load capture file
3. If `--list-backends` is specified:
   - Extract unique backends
   - Display backend list with counts
   - Exit
4. If `--backend` is specified:
   - Validate backend exists in capture (warn if not found)
   - Filter entries by backend
5. Continue with existing logic (summary, entries display, analysis)

## Data Models

### Capture Entry Structure (existing)
See `CaptureEntry` / `CaptureEntryMeta` in the interface section above. The wire-capture reader may still yield untyped mappings; this feature normalizes to these models at the boundary and passes typed entries through the filter/discovery pipeline.

### Backend Catalog
```python
{
    "openai": 42,          # backend name -> entry count
    "anthropic": 38,
    "gemini": 25
}
```

## Correctness Properties

A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.

### Property 1: Backend Filter Completeness

*For any* capture file and any backend name that exists in the file, filtering by that backend SHALL return all and only entries where the metadata backend field matches that backend name.

**Validates: Requirements 1.1**

### Property 2: No Filter Equivalence

*For any* capture file, not specifying a backend filter SHALL return the same entries as the unfiltered entry list.

**Validates: Requirements 1.3**

### Property 3: Backend Discovery Accuracy

*For any* capture file, the `--list-backends` output SHALL contain exactly the set of unique backend names present in entries with backend metadata, with accurate counts.

**Validates: Requirements 2.1, 2.3**

### Property 4: Analysis Pair Filtering

*For any* capture file and any backend name, when analyzing request/response pairs with backend filter, all pairs returned SHALL have both request and response entries associated with the specified backend.

**Validates: Requirements 1.4**

### Property 5: Entries Limit with Backend Filter

*For any* capture file and any backend name, when displaying entries with a limit, the number of displayed entries SHALL not exceed the specified limit and all displayed entries SHALL match the backend filter.

**Validates: Requirements 1.5**

## Error Handling

### Invalid Backend Name
- **Scenario**: User specifies `--backend openai-invalid` but only "openai" exists
- **Handling**: Display warning message, show zero entries, continue execution
- **Message**: "Warning: Backend 'openai-invalid' not found in capture. Available backends: openai, anthropic"

### No Backend Metadata
- **Scenario**: Capture file has entries but none have backend metadata
- **Handling**: Display message when `--list-backends` is used
- **Message**: "No backend information available in this capture file"

### Empty Filter Result
- **Scenario**: Backend filter matches no entries
- **Handling**: Display summary showing 0 entries, continue normally
- **Message**: Implicit in summary output

## Testing Strategy

### Unit Testing

Unit tests verify specific examples and edge cases:

1. **Backend extraction**: Test `get_unique_backends()` with various entry structures
2. **Backend filtering**: Test `filter_entries_by_backend()` with valid/invalid backends
3. **Empty results**: Test filtering that returns no entries
4. **No metadata**: Test entries without backend metadata
5. **Argument parsing**: Test `--backend` and `--list-backends` argument parsing

### Property-Based Testing

Property-based tests verify universal properties across many inputs:

1. **Property 1 (Completeness)**: Generate random capture files with multiple backends, verify all matching entries are returned
2. **Property 2 (Exclusivity)**: Generate random capture files, verify no non-matching entries are returned
3. **Property 4 (No Filter Equivalence)**: Generate random capture files, verify unfiltered equals no-filter
4. **Property 5 (Discovery Accuracy)**: Generate random capture files, verify backend list matches actual backends
5. **Property 6 (Discovery Completeness)**: Generate random capture files, verify all backends in entries appear in list

### Integration Testing

Integration tests verify the complete workflow:

1. Test `--list-backends` flag displays correct backends
2. Test `--backend` with `--entries` shows filtered entries
3. Test `--backend` with `--analyze` analyzes only matching pairs
4. Test `--backend` with `--json` exports only filtered entries
5. Test `--backend` with `--direction` combines both filters correctly

## Implementation Notes

- Backend filtering is applied after direction filtering in the pipeline
- Backend metadata is optional; entries without it are excluded when filtering
- Backend names are case-sensitive (match exactly as stored in metadata)
- The `--list-backends` flag takes precedence and exits early
- Filtering logic is reusable across all output modes (summary, entries, analysis, JSON)

