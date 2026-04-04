---
phase: 02-compatibility-contract-stabilization
plan: "01"
subsystem: domain/config
tags: [capability-descriptor, backend-config, pydantic, typed-config, tdd]
dependency_graph:
  requires: []
  provides: [BackendCapabilityDescriptor, BackendConfig.capability_descriptor]
  affects: [src/core/config/models/backends.py, src/core/domain/backend_capability_descriptor.py]
tech_stack:
  added: []
  patterns: [Pydantic BaseModel, field_validator coercion, Literal type constraint]
key_files:
  created:
    - src/core/domain/backend_capability_descriptor.py
    - tests/unit/config/__init__.py
    - tests/unit/config/test_backend_capability_descriptor.py
  modified:
    - src/core/config/models/backends.py
decisions:
  - "Used Literal['openai','anthropic','gemini'] for ProtocolFamily to enforce valid values at parse time"
  - "field_validator with mode='before' coerces dict->BackendCapabilityDescriptor so YAML config works transparently"
  - "capability_descriptor defaults to None to preserve safe backward-compatible behavior for backends without a descriptor"
metrics:
  duration: "4 minutes"
  completed: "2026-04-04"
  tasks_completed: 2
  files_changed: 4
---

# Phase 02 Plan 01: BackendCapabilityDescriptor Contract Summary

Typed `BackendCapabilityDescriptor` Pydantic model created and wired into `BackendConfig.capability_descriptor` with dict-coercion validator, enabling operators to declare backend capabilities through YAML config instead of implicit attribute inference.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create BackendCapabilityDescriptor model | 87021eb9 | src/core/domain/backend_capability_descriptor.py, tests/unit/config/test_backend_capability_descriptor.py |
| 2 | Wire capability_descriptor into BackendConfig | 6a7d665d | src/core/config/models/backends.py |

## Decisions Made

- `ProtocolFamily = Literal["openai", "anthropic", "gemini"]` — enforces valid wire protocol families at Pydantic parse time; unknown values raise `ValidationError`
- `field_validator("capability_descriptor", mode="before")` — coerces plain dicts from YAML config into `BackendCapabilityDescriptor` transparently; model instances pass through unchanged
- `capability_descriptor: BackendCapabilityDescriptor | None = None` — defaults to `None` so backends without a descriptor behave identically to current behavior (safe default, COMP-04 requirement)

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED
