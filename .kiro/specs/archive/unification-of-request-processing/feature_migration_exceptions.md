# Canonical feature migration status and explicit exceptions

This document records Wave 4.2 migration progress and the bounded exceptions
that remain mode-sensitive during the transition.

## Migrated priority features

- `ResponseLoggingFeature`
  - Uses `FeatureLifecycleContext` via compatibility bridge.
  - Reads terminal state, finish reason, request id, backend, and model metadata.
- `ContentFilterFeature`
  - Uses `FeatureLifecycleContext` via compatibility bridge.
  - Keeps behavior identical while adding typed lifecycle-aware diagnostics.

## Explicit bounded exceptions (kept mode-sensitive for now)

- `EmptyResponseFeature`
  - Depends on stream terminal detection and retry budgets.
  - Remains in existing safeguard path until connector migration fully stabilizes.
- `ToolCallReactor` / swallowed-tool handling
  - Requires terminal and retry-state coordination with request-level control flow.
- Loop/cancellation guards in streaming handler
  - Intentionally remain in the streaming safeguard layer.

## Removal policy

- Duplicated feature logic is removed only when canonical behavior is equivalence-tested.
- Exception features stay isolated in current layers and are covered by regression tests.
