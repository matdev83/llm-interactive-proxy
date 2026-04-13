# Migration retirement notes (request-processing unification)

## Retired from production startup

- **Feature parity registry initialization** no longer runs from `post_build_hooks`. The global parity registry and `initialize_feature_parity_registry` remain as an **optional** helper for tests, audits, and local diagnostics (see `post_build_actions.initialize_feature_parity_registry` docstring).
- **CI parity enforcement** no longer assumes registry population via `get_or_build_service_provider`. Quality tests seed the registry explicitly when they need `verify_parity()`, and assert typed `FeatureLifecycleContext` coverage where appropriate.

## Runtime shape (post-retirement)

- `BackendRequestManager` always uses the canonical post-backend pipeline (`PostBackendResponseCoordinator` + `EnvelopeCompatibilityAdapter`) for both requested modes.
- `enable_core_canonical_path` is retained for compatibility/validation semantics but no longer switches execution to a legacy split-handler branch.
- `CorePathDecision.retire_legacy_dual_path` remains a configuration snapshot in diagnostics when `emit_path_selection_metadata` is enabled.

## Compatibility shims retained

- `initialize_feature_parity_registry` and `src.core.interfaces.feature_parity` registry APIs unchanged for callers that opt in explicitly.
- **Current runtime**: `BackendRequestManager` always selects the canonical post-backend path; transport adaptation to streaming/non-streaming happens only at the boundary via `EnvelopeCompatibilityAdapter`.
