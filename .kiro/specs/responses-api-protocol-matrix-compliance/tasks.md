# Implementation Plan

- [ ] 1. Establish the new protocol-centric spec baseline
- [ ] 1.1 Create the new spec as the active source of truth and mark the current responses frontend compliance spec as superseded but not yet archived
  - Preserve historical context from the current spec while moving active scope to the protocol-centric matrix framing
  - Ensure approvals remain pending until the new requirements, design, and tasks are reviewed
  - _Requirements: 1, 2, 7_

- [ ] 2. Add red tests for profile-based routing before changing implementation
- [ ] 2.1 Add unit tests that prove Responses projector and stream selection must come from resolved protocol surface rather than backend name
  - Cover backends with different names that share one surface
  - Cover one backend name that can represent different surfaces through metadata
  - Add explicit regression cases for the current controller failure path
  - _Requirements: 1, 2, 6_

- [ ] 2.2 Add integration tests that prove controller behavior is profile-driven across HTTP and streaming paths
  - Verify the controller selects equivalent behavior for differently named backends with the same surface
  - Verify profile-driven stream normalization and limitation disclosure
  - _Requirements: 1, 3, 5, 6_

- [ ] 3. Introduce protocol-surface routing metadata
- [ ] 3.1 Extend backend capability and routing models to describe the outbound Responses protocol surface
  - Add a first-class profile model covering native Responses, legacy OpenAI, Anthropic, Gemini, Bedrock, and ACP
  - Decide whether the resolved surface lives on `BackendTarget` or a companion resolved-target object and update contracts consistently
  - _Requirements: 1, 2_

- [ ] 3.2 Populate protocol-surface metadata during target resolution
  - Source the surface from backend configuration, catalog metadata, or resolved backend descriptors rather than controller heuristics
  - Preserve existing backend identity and model resolution behavior
  - _Requirements: 1, 2, 6_

- [ ] 4. Replace backend-name projector selection with profile registries
- [ ] 4.1 Implement a Responses projector registry keyed by protocol surface
  - Resolve `IResponsesBackendProjector` by profile
  - Fail explicitly for unsupported or missing profile registrations
  - _Requirements: 1, 2, 6_

- [ ] 4.2 Implement a stream-profile registry keyed by protocol surface
  - Resolve the semantic event interpretation path from the same profile used for request projection
  - Remove duplicated backend-name conditionals from streaming orchestration
  - _Requirements: 1, 5_

- [ ] 4.3 Refactor `ResponsesController` to use resolved protocol surface metadata
  - Remove backend-name branching from `_prepare_responses_execution`
  - Preserve request normalization, session linkage, and error correlation behavior
  - _Requirements: 1, 3, 4, 5, 6_

- [ ] 5. Implement the full six-surface translation matrix
- [ ] 5.1 Complete and verify the native Responses surface path
  - Preserve native payload shape without lossy adaptation
  - _Requirements: 2, 3, 5_

- [ ] 5.2 Complete and verify the legacy OpenAI surface path
  - Preserve typed input semantics, tool linkage, and lifecycle equivalence through translation
  - _Requirements: 2, 3, 4, 5, 6_

- [ ] 5.3 Complete and verify the Anthropic surface path
  - Preserve tool and follow-up semantics or return explicit limitation errors
  - _Requirements: 2, 3, 4, 5, 6_

- [ ] 5.4 Complete and verify the Gemini surface path
  - Preserve tool and follow-up semantics or return explicit limitation errors
  - _Requirements: 2, 3, 4, 5, 6_

- [ ] 5.5 Complete and verify the Bedrock surface path
  - Implement Bedrock-specific translation and capability checks
  - Add explicit limitation behavior for unsupported feature combinations if needed
  - _Requirements: 2, 3, 4, 5, 6_

- [ ] 5.6 Complete and verify the ACP surface path
  - Implement ACP-specific translation, workspace-related validation, and lifecycle mapping
  - Preserve Responses follow-up semantics where contract-compatible
  - _Requirements: 2, 3, 4, 5, 6_

- [ ] 6. Expand regression and integration coverage
- [ ] 6.1 Add unit and integration coverage for the six-profile matrix
  - Cover request translation, stream normalization, multi-turn continuity, and explicit limitation disclosure per profile
  - _Requirements: 2, 3, 4, 5, 6_

- [ ] 6.2 Add fixture-backed canonical contract assertions for HTTP streaming and non-streaming Responses behavior
  - Pin response shape, event ordering, terminal signaling, and official field names
  - _Requirements: 3, 5, 6_

- [ ] 7. Add real proxy end-to-end verification using an official Responses-compatible client
- [ ] 7.1 Create an automated E2E harness that starts a real proxy instance and exercises `/v1/responses`
  - Avoid mocking the translation layer or bypassing controller routing
  - Validate client-visible semantics, not only internal payloads
  - _Requirements: 7_

- [ ] 7.2 Add one live-through-proxy verification scenario for each supported protocol surface
  - Native Responses
  - Legacy OpenAI
  - Anthropic
  - Gemini
  - Bedrock
  - ACP
  - _Requirements: 2, 5, 7_

- [ ] 7.3 Add an operator-run playbook for any live scenarios that cannot run in CI
  - Include exact commands, selectors, expected assertions, and artifact collection guidance
  - _Requirements: 7_

- [ ] 8. Reconcile spec state and completion criteria
- [ ] 8.1 Update completion gates so the feature cannot be declared complete until all six surfaces are implemented or explicitly narrowed by approved limitation statements
  - Keep the spec active until verification evidence exists for the full supported matrix
  - _Requirements: 2, 6, 7_
