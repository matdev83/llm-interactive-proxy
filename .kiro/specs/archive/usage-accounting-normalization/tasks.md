# Implementation Plan

- [x] 1. Establish canonical usage models and normalization context
- [x] 1.1 Define canonical usage record fields, extensions container, and completion/incomplete enums
  - Ensure canonical usage includes identifiers, token counts, cost, completion outcome, incomplete reason, and extensions container
  - Represent unavailable values explicitly as null and derive total tokens when both inputs are present
  - _Requirements: 1.2, 1.3, 1.4, 2.2, 3.4_

- [x] 1.2 Expand normalization context and response envelopes to carry protocol, identifiers, and canonical usage
  - Capture request_id sources, backend/model identifiers, and protocol in the normalization context inputs
  - Attach canonical usage to response and streaming envelopes for downstream consumers
  - _Requirements: 1.5, 1.6, 1.7, 1.8, 5.1_

- [x] 2. Build usage normalization service and DI wiring
- [x] 2.1 Define the normalization service contract for canonical record creation and protocol projection
  - Establish a single normalization boundary for canonical usage inputs/outputs
  - _Contracts: IUsageNormalizationService_
  - _Requirements: 1.1, 2.1, 5.1_

- [x] 2.2 Implement canonical record creation with field mapping, null handling, and extension preservation
  - Map provider/model/request/protocol identifiers using available context signals
  - Normalize token totals and costs while preserving provider extensions under the extensions container
  - Fail open on missing inputs with explicit nulls
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 1.12, 2.1, 2.2, 2.3, 2.4, 4.1, 4.3_

- [x] 2.3 Implement streaming outcome resolution and structured warning logging
  - Resolve completion outcome and incomplete reason from cancellation signals and error classifications
  - Emit structured warnings with request identifier, backend, model, protocol, and error classification when usage is malformed
  - _Requirements: 3.1, 3.2, 3.3, 3.5, 3.6, 3.7, 3.8, 3.9, 4.2_

- [x] 2.4 Implement protocol usage projection that preserves existing values
  - Merge canonical usage into protocol payloads without overwriting existing non-null usage with zeroes
  - _Requirements: 5.2, 5.4_

- [x] 2.5 Register the normalization service in DI with the appropriate lifetime
  - Ensure the normalization service is available to orchestrators and adapters
  - _Requirements: 1.1, 5.1_

- [x] 3. Integrate normalization into request and streaming flows
- [x] 3.1 Update backend completion orchestration to emit canonical usage in envelopes
  - Build canonical usage for non-streaming responses and attach to response envelopes
  - Emit canonical usage on streaming completion with the final outcome
  - _Requirements: 1.1, 3.1, 3.2, 3.3, 5.1_

- [x] 3.2 (P) Update streaming tracking and error handling to supply completion signals
  - Provide completion outcome and error classification signals for normalization
  - Ensure early termination paths produce incomplete outcomes
  - _Requirements: 3.1, 3.2, 3.3, 3.7, 3.8, 3.9_

- [x] 3.3 (P) Stamp protocol identifiers and cancellation reasons in controllers
  - Tag each protocol surface with the correct protocol identifier in the request context
  - Record cancellation reasons on client disconnect or explicit cancellation callbacks
  - _Requirements: 1.9, 1.10, 1.11, 1.12, 3.5, 3.6_

- [x] 4. Project canonical usage into client responses
- [x] 4.1 Update response adapters to populate protocol usage from canonical usage
  - Preserve existing response shapes and avoid overriding non-null usage fields
  - _Requirements: 5.2, 5.3, 5.4_

- [x] 4.2 Update usage header generation to derive values from canonical usage
  - Populate response headers from canonical usage when available
  - _Requirements: 5.5_

- [x] 5. Extend wire capture metadata with canonical usage
- [x] 5.1 Add canonical usage metadata fields for CBOR and buffered capture outputs
  - Persist canonical usage in capture metadata without altering client payloads
  - _Requirements: 5.6_

- [x] 5.2 Attach canonical usage metadata during capture orchestration
  - Ensure capture entries include canonical usage and provider extensions when present
  - _Requirements: 5.1, 5.6_

- [x] 6. Testing coverage for normalization
- [x] 6.1 Write unit tests for canonical usage normalization behavior
  - Cover identifier mapping, null semantics, extensions preservation, and incomplete reason mapping
  - Validate protocol mapping and structured warning logging for malformed usage
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 1.12, 2.1, 2.2, 2.3, 2.4, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 4.1, 4.2, 4.3_

- [x] 6.2 Write integration tests for end-to-end usage propagation
  - Validate canonical usage attachment in envelopes, response payloads, headers, and wire capture metadata
  - _Requirements: 3.1, 3.2, 3.3, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

- [x] 6.3 Add property tests for usage normalization invariants
  - Validate total token derivation and unit normalization invariants
  - _Requirements: 1.3, 2.4_
