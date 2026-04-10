# Gap Analysis: composite-model-routing-failover-weighted-random

## Current Status

- Requirements, design, and tasks are approved in `spec.json`.
- Implementation status is complete and post-implementation polish has been applied.
- Composite selector parsing, failover, weighted routing, and cross-surface routing are implemented through the shared routing entry point.

## Post-Polish Alignment Update

The following implementation gaps identified during deep code review were closed:

1. **Explicit composite selectors no longer lose runtime failover in request processing**
   - `BackendProcessor` now mirrors `BackendService` failover gating:
     - explicit **non-composite** selectors disable runtime failover,
     - explicit **composite** selectors keep runtime failover enabled.

2. **Quality Verifier routing surface is deterministic**
   - Quality verifier calls now stamp `composite_routing_surface=quality_verifier`.
   - Surface resolution gives `call_purpose=quality_verifier*` precedence over stale surface hints.

3. **Project directory LLM routing now allows composite runtime failover**
   - Project-directory model calls now invoke backend execution with `allow_failover=True`.
   - Unit coverage verifies failover-enabled invocation and composite-selector passthrough.

4. **Replacement compatibility bridge now performs safe composite weighted translation**
   - Safe legacy replacement selectors are translated into deterministic weighted composite selectors.
   - Unsafe/ambiguous mappings still fail with explicit migration errors.
   - N+1 deprecation metadata remains published.

5. **Auxiliary routing ownership is consolidated**
   - Duplicate auxiliary routing mutation logic in `RequestProcessorService` was removed.
   - Canonical auxiliary routing adaptation remains in `BackendRequestPreparer`.

## Requirements Coverage Snapshot

| Requirement | Status | Notes |
|---|---|---|
| R1 Unified entry point | Implemented | Main/auxiliary/quality-verifier/replacement surfaces route through shared composite logic. |
| R2 Failover selectors | Implemented | Ordered failover and deterministic exhaustion behavior are present. |
| R3 Weighted selectors | Implemented | Weighted parsing/selection and default weights are covered. |
| R4 Parsing/validation | Implemented | Deterministic parsing with mixed-operator rejection and validation errors. |
| R5 Retry/failover safety | Implemented | Shared bounded attempt budget and meaningful-output guard enforced. |
| R6 Backward compatibility | Implemented | Existing selector semantics retained for non-composite paths. |
| R7 Replacement migration | Implemented | Deprecation metadata + compatibility bridge + explicit migration errors. |
| R8 Observability/diagnostics | Implemented | Structured composite diagnostics available across supported surfaces. |

## Validation Notes

- Targeted unit/integration/regression test suites covering the touched areas passed after the polish changes.
- Final full-suite and CLI end-to-end verification is executed in the verification phase after this document sync.
