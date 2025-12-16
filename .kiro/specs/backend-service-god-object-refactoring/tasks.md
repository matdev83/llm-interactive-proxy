# Implementation Plan: BackendService God Object Refactoring

## Task Format

- Tasks focus on outcomes and behavior, not file paths or method names.
- Each task ends with a requirements mapping line listing numeric IDs from `requirements.md` (for example `1.2`).

## Phase 1: Baseline and Characterization

- [ ] 1. Establish a reliable baseline for current behavior
  - Run the existing automated tests that cover BackendService behavior (unit, integration, property, regression).
  - Capture current complexity metrics for BackendService using the project’s complexity tooling so improvements can be verified later.
  - _Requirements: 1.2, 4.1_

- [ ] 1.1 (P) Add/extend characterization tests for target resolution
  - Lock in current backend/model resolution behavior, including static routing overrides and URI parameter parsing.
  - _Requirements: 3.3, 4.2, 6.1, 6.2_

- [ ] 1.2 (P) Add/extend characterization tests for failover planning and execution
  - Lock in failover plan selection behavior (strategy vs coordinator), health filtering, and complex failover semantics.
  - _Requirements: 3.3, 4.2, 7.1, 7.2, 7.3_

- [ ] 1.3 (P) Add/extend characterization tests for streaming session identity
  - Lock in the current session-id fallback behavior used for streaming capture/buffering.
  - _Requirements: 3.3, 4.2, 8.1, 8.2, 8.3_

## Phase 2: Define New Boundaries (Interfaces + DI Seams)

- [ ] 2. Define small interfaces for the new collaborators
  - Introduce interfaces for completion orchestration, target resolution, failover planning, and streaming session-id resolution.
  - Ensure contracts are minimal and testable, and align with existing interface styles in the codebase.
  - _Requirements: 2.2, 6.1, 7.1, 8.1_

- [ ] 2.1 (P) Add DI wiring for new collaborators
  - Register new collaborators and their interfaces in the existing DI composition root.
  - If `BackendService` is also constructed via staged fallback wiring, update `src/core/app/stages/backend.py` so the fallback factory passes the same explicit dependency set (no missing collaborators).
  - _Requirements: 2.3, 2.4_

## Phase 3: Implement Extracted Collaborators

- [ ] 3. Implement the streaming session-id resolver and reuse it consistently
  - Centralize the session-id resolution algorithm and apply it anywhere streaming capture/buffering needs a stable identifier.
  - _Requirements: 8.1, 8.2, 8.3_

- [ ] 3.1 (P) Implement target resolution as a dedicated service
  - Extract backend/model resolution and request synchronization into a focused service, preserving ordering constraints and outputs.
  - _Requirements: 6.1, 6.2_

- [ ] 3.2 (P) Implement failover planning as a dedicated service
  - Extract plan selection and health filtering into a focused service, preserving all edge cases.
  - _Requirements: 7.1, 7.2_

- [ ] 3.3 Implement completion orchestration as a dedicated service
  - Move the completion flow out of BackendService into a dedicated orchestrator that coordinates resolution, backend invocation, retry/failover behavior, wire capture, and usage tracking.
  - Ensure the orchestrator does not create new high-complexity hotspots by decomposing the flow into smaller internal steps.
  - _Requirements: 1.1, 1.4, 3.2, 5.1, 7.3, 9.1, 10.1, 11.1, 11.2_

## Phase 4: Refactor BackendService into a Thin Facade

- [ ] 4. Remove runtime fallback instantiation from BackendService construction
  - Make dependency construction a DI concern, not a BackendService concern.
  - Update unit tests/fixtures that directly instantiate `BackendService` to provide required dependencies (or use a canonical test builder) so tests no longer rely on constructor fallbacks.
  - _Requirements: 2.1, 2.3, 3.5_

- [ ] 4.1 Update BackendService to delegate to new collaborators
  - Ensure public entrypoints delegate to the completion orchestrator.
  - Ensure helper methods referenced by tests remain as thin delegating wrappers with unchanged semantics.
  - _Requirements: 1.1, 3.1, 3.2, 3.3, 3.4_

## Phase 5: Verification and Quality Gates

- [ ] 5. Verify correctness via the full test suite
  - Run the full automated test suite and fix any regressions until green.
  - _Requirements: 4.1_

- [ ] 5.1 Verify complexity and size targets
  - Confirm BackendService size and complexity targets are met and no new “god object” replacements were introduced.
  - _Requirements: 1.2, 1.3, 1.4_

- [ ] 5.2 Verify non-functional constraints
  - Validate no streaming first-byte regressions and no measurable latency overhead in local smoke benchmarks.
  - _Requirements: 12.1, 12.2_

- [ ] 5.3 Verify security/observability invariants
  - Confirm error semantics, capture behavior, and usage tracking behavior remain unchanged.
  - _Requirements: 9.1, 11.1, 11.2, 12.3_
