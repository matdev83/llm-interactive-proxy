# Implementation Plan

## Phase 1: Establish Plugin Capability Contracts

- [ ] 1. Establish the shared plugin capability and protocol contracts
- [ ] 1.1 Define the published runtime contracts for OAuth-oriented backend behavior
  - Move the token-refresh contract into the stable core interface layer and publish the refresh, rotation, and account-selection capabilities through the plugin API.
  - Keep the contract surfaces focused on behaviors the core actually needs during execution.
  - Preserve compatibility for plugins adopting the new public contract surface.
  - _Requirements: 3.1, 3.2_

- [ ] 1.2 Define capability metadata for OAuth-oriented backends
  - Extend the backend capability model so backends can declare whether they are OAuth-based and whether they require personal authentication.
  - Ensure in-repo OAuth-oriented backends declare the same capability vocabulary as extracted plugins.
  - Keep the metadata focused on cross-cutting behavior rather than connector-specific quirks.
  - _Requirements: 2.1, 2.2, 2.3_

- [ ] 1.3 (P) Add discovery-time plugin metadata for CLI and capability integration
  - Extend plugin registration metadata so discovery can expose OAuth-related capability hints and plugin-owned CLI/configuration hooks.
  - Preserve idempotent plugin registration behavior and stable plugin API expectations.
  - Make the registration metadata sufficient for startup-time classification and integration decisions.
  - _Requirements: 2.4, 4.1, 4.2_

- [ ] 1.4 (P) Define the plugin-owned private configuration extension path
  - Implement one documented mechanism for plugins to own validation of their private configuration fragments without adding core-owned plugin-specific defaults.
  - Keep the extension path aligned with the existing configuration model and plugin boundary.
  - Ensure the contract is explicit enough for external plugin authors to adopt.
  - _Requirements: 4.3, 4.5_

## Phase 2: Remove Name-Based Core Coupling

- [ ] 2. Replace name-based discovery and scoping behavior with capability-driven behavior
- [ ] 2.1 Refactor OAuth-oriented connector classification to use declared capability signals
  - Update discovery-time classification so in-scope OAuth decisions use declared capability signals instead of extracted-plugin literals or spelling heuristics.
  - Preserve the ability to classify connectors before runtime connector instances exist.
  - Keep packaging diagnostics separate from behavioral branching.
  - _Requirements: 1.1, 1.3, 2.2, 2.4_

- [ ] 2.2 Refactor personal-auth resilience scoping to use capability metadata
  - Use declared backend capabilities to determine whether a backend participates in personal-auth resilience behavior.
  - Remove dependence on hardcoded backend-name lists for the in-scope scoping paths.
  - Preserve existing operator-facing override mechanisms where they remain part of the core feature set.
  - _Requirements: 1.1, 1.3, 2.3_

- [ ] 2.3 (P) Refactor streaming execution to use published protocols instead of private state access
  - Replace duck-typed credential, rotation, account-selection, and rate-limit behavior with calls through the published runtime contracts.
  - Remove dependence on private connector attributes and backend-name checks in the in-scope execution path.
  - Keep the retry and refresh flow behaviorally consistent while shifting to the new contracts.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

## Phase 3: Move Plugin-Specific CLI Ownership to Plugins

- [ ] 3. Integrate plugin-owned CLI and configuration behavior into startup
- [ ] 3.1 (P) Replace hardcoded extracted-plugin CLI wiring with plugin registration hooks
  - Let plugins contribute their own CLI arguments during startup instead of relying on hardcoded extracted-plugin flags in core.
  - Preserve the supported startup lifecycle so plugin hooks are available before argument parsing needs them.
  - Keep plugin argument registration deterministic and compatible with existing core CLI behavior.
  - _Requirements: 4.1, 4.4_

- [ ] 3.2 (P) Apply plugin-owned CLI values through the configuration pipeline
  - Let plugins translate parsed CLI values into configuration updates through a supported post-parse integration point.
  - Keep the existing core configuration precedence and applicator semantics intact.
  - Ensure plugin-owned settings remain inside the documented plugin boundary.
  - _Requirements: 4.2, 4.5_

## Phase 4: Restore Core Test Isolation

- [ ] 4. Rebuild the test boundary between core and extracted OAuth plugins
- [ ] 4.1 Remove extracted-plugin runtime behavior coverage from the core repository
  - Stop using the optional plugin package for connector runtime-behavior tests in core, except for packaging-contract scenarios.
  - Move extracted-plugin behavior assertions to the plugin repository.
  - Leave only core-owned contract and packaging coverage in this repository.
  - _Requirements: 5.1, 5.2, 5.4_

- [ ] 4.2 Update core tests to exercise generic plugin contracts and mocks
  - Replace plugin-specific behavior fixtures with generic mocks or dummy plugins for discovery, execution, and CLI/config integration tests.
  - Validate the new capability-driven and protocol-driven seams from the core side.
  - Preserve packaging-contract coverage that does not import optional plugin runtime code.
  - _Requirements: 5.1, 5.3_

## Phase 5: Verification and Follow-up Readiness

- [ ] 5. Verify the new plugin boundary is coherent and ready for follow-up cleanup
- [ ] 5.1 Validate end-to-end consistency across discovery, execution, CLI, and tests
  - Confirm the in-scope paths all use the same capability vocabulary and published runtime contracts.
  - Verify the core no longer depends on extracted-plugin names or runtime imports for the targeted behaviors.
  - Leave deferred heuristic cleanup explicitly outside this phase so future follow-up can proceed from a stable baseline.
  - _Requirements: 1.2, 2.2, 3.3, 4.4, 5.3_
