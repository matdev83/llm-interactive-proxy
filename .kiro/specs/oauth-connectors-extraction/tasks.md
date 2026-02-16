# Implementation Plan

- [x] 1. Establish packaging boundary for extracted OAuth connectors
- [x] 1.1 Define and prepare the standalone OAuth connector distribution for pip installation
  - Define package structure, metadata, and release strategy for extracted connectors.
  - Ensure extracted connector ownership is clearly separated from core distribution lifecycle.
  - _Requirements: 1.1, 9.1_

- [x] 1.2 Add optional core installation extra for OAuth connector package
  - Provide optional installation path through core package extras.
  - Ensure full optional-install guidance is clear and consistent for operators.
  - _Requirements: 1.2, 1.3_

- [x] 1.3 Separate optional connector dependencies from mandatory core dependencies
  - Move OAuth-only dependency requirements behind optional install mode.
  - Keep core dependency footprint valid for non-OAuth operation.
  - _Requirements: 1.4_

- [x] 2. Implement fail-open plugin discovery for optional external backends
- [x] 2.1 Extend startup discovery to include external backend entry-point scan
  - Discover plugin backends through `llm_proxy_backends` entry-point group.
  - Preserve deterministic startup order before backend selection/validation.
  - _Requirements: 2.1, 2.2, 2.6_

- [x] 2.2 Implement no-entrypoint and load-failure fail-open behavior
  - Treat missing entry points as valid optional absence.
  - Log actionable warnings for plugin load failures without aborting startup.
  - _Requirements: 2.3, 2.4, 5.1_

- [x] 2.3 Register discovered plugin backends through stable registry contract
  - Register successfully loaded plugin backends with deterministic naming.
  - Persist compatibility metadata needed for runtime safety decisions.
  - _Requirements: 2.5, 9.2, 9.4_

- [x] 3. Enforce core independence from concrete backend connectors
- [x] 3.1 Remove unconditional core imports of extracted connector modules
  - Harden startup and DI composition paths to avoid hard dependency on extracted modules.
  - Keep optional plugin loading isolated from core bootstrap health.
  - _Requirements: 3.1, 3.2, 3.5_

- [x] 3.2 Ensure plugin onboarding does not require core business-logic edits
  - Drive connector extensibility through supported plugin contracts only.
  - Validate that adding connector types does not require routing/session core rewrites.
  - _Requirements: 3.3, 9.1, 9.2_

- [x] 3.3 Protect non-extracted connector behavior from plugin changes
  - Validate that changes in extracted plugin connectors cannot break core connector operation.
  - Preserve fail-open guarantees for optional plugin instability.
  - _Requirements: 3.4, 5.6, 10.4_

- [x] 4. Enforce frontend adapter decoupling and shared routing usage
- [x] 4.1 Align frontend adapters to canonical domain/request contracts
  - Keep frontend protocol layers focused on translation and adapter concerns only.
  - Keep core policy layers independent from concrete adapter classes.
  - _Requirements: 4.1, 4.2_

- [x] 4.2 Verify all outbound inference surfaces use shared routing boundary
  - Ensure primary, replacement, verifier, and auxiliary flows resolve through the same routing contract.
  - Preserve existing no-bypass compliance behavior.
  - _Requirements: 4.4, 6.1, 6.2, 6.3, 6.4_

- [x] 4.3 Add anti-drift checks for frontend-to-core boundary integrity
  - Prevent protocol-specific business logic from leaking into core routing/session services.
  - Keep layering and dependency direction explicit and reviewable.
  - _Requirements: 4.3, 10.1, 10.2_

- [x] 5. Preserve B2BUA identity and constrained-family architecture contracts
- [x] 5.1 Verify B2BUA identity isolation remains intact for core and plugin connectors
  - Keep A-leg continuity internal and B-leg connector-facing.
  - Ensure connector boundary sanitizes sensitive identity fields.
  - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [x] 5.2 Verify auxiliary session isolation behavior under extraction changes
  - Ensure sidecar/auxiliary calls do not mutate primary continuity identity lifecycle.
  - Preserve deterministic derived session behavior.
  - _Requirements: 7.5_

- [x] 5.3 Preserve constrained single-instance policy for self-managed OAuth families
  - Keep shared policy enforcement for constrained families across validation and routing.
  - Preserve deterministic conflict diagnostics and operator guidance.
  - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 6. Implement clear runtime behavior when optional OAuth package is absent
- [x] 6.1 Add actionable diagnostics for unregistered extracted backends
  - Emit install guidance when configuration references extracted backends that are unavailable.
  - Keep warnings precise and operator-actionable.
  - _Requirements: 5.2, 1.3_

- [x] 6.2 Enforce startup failure only when no viable backend path remains
  - Fail startup with actionable error when required backend target is unavailable and no alternative exists.
  - Keep startup healthy when at least one configured backend remains operational.
  - _Requirements: 5.3, 5.5_

- [x] 6.3 Return deterministic handled errors for request-time missing extracted backends
  - Avoid unhandled exceptions when clients target unavailable extracted backends.
  - Keep behavior consistent across supported protocol adapters.
  - _Requirements: 5.4_

- [x] 6.4 Validate continuity of API-key connector functionality without oauth package
  - Confirm non-OAuth connector paths remain fully functional in core-only install mode.
  - _Requirements: 5.1, 5.6_

- [x] 7. Define and enforce stable plugin API compatibility contract
- [x] 7.1 Publish supported plugin contract surface and registration hooks
  - Document stable interfaces and supported integration points for plugin authors.
  - _Requirements: 9.1, 9.2_

- [x] 7.2 Implement compatibility gating and optional hook execution behavior
  - Execute plugin hooks conditionally without making core startup dependent on them.
  - Skip incompatible plugins with warnings and continue startup.
  - _Requirements: 9.3, 9.4_

- [x] 7.3 Apply SOLID/DRY/layering checks to extraction-related implementation
  - Review and enforce single-responsibility boundaries across routing/session/discovery concerns.
  - Avoid duplicate policy logic across adapters, core services, and connector layers.
  - _Requirements: 10.1, 10.2, 10.3, 10.4_

- [x] 8. Build verification matrix and regression safeguards
- [x] 8.1 Add core-only mode tests for startup and discovery fail-open behavior
  - Validate startup in absence of oauth package and missing plugin entry points.
  - _Requirements: 11.1, 11.2, 5.1_

- [x] 8.2 Add core-only mode tests for API-key connector operational continuity
  - Validate non-extracted backend functionality remains stable without optional package.
  - _Requirements: 11.3, 5.6_

- [x] 8.3 Add tests for deterministic warnings/errors around missing extracted backends
  - Validate startup-time and request-time diagnostics/error behavior for unavailable extracted backends.
  - _Requirements: 11.4, 5.2, 5.3, 5.4, 5.5_

- [x] 8.4 Add tests for routing-unification and B2BUA boundary non-regression
  - Keep shared routing no-bypass guard active.
  - Verify A-leg/B-leg and identity sanitization behavior remains intact.
  - _Requirements: 6.5, 6.6, 7.1, 7.2, 7.3, 7.4, 7.5_

- [x] 8.5 Add and run external plugin package test suite
  - Maintain separate verification for extracted connector package behavior.
  - _Requirements: 11.5_
