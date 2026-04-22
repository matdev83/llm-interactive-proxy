# Implementation Plan

- [x] 1. Verify upstream WebSocket response.create framing and fix if needed
  - Capture the exact `response.create` frame shape for the proxy's actual upstream surface: `wss://api.openai.com/v1/responses` with `OpenAI-Beta: responses-websocket-mode=...`
  - Do not infer the answer from HTTP `/responses` request bodies, Realtime WebSocket types, or OpenCode's HTTP streaming implementation; compare the verified upstream contract with the current `openai_websocket_client.py` implementation and change the proxy only if the shapes differ
  - Add a unit or integration test pinning the exact upstream frame shape expected by the live API
  - _Requirements: 1.2_

- [x] 2. Add Responses domain model and error hierarchy
- [x] 2.1 Implement the Responses domain request model with typed input items
  - Create `ResponsesDomainRequest` as a frozen Pydantic v2 model holding `input: list[ResponsesInputItem]`, `instructions`, `previous_response_id`, `tools`, `stream`, `model`, and all standard Responses parameters
  - Create `ResponsesInputItem` and `ResponsesContentPart` models preserving type, role, content, call_id, name, arguments, and output fields
  - Create `ResponsesOutputItem` model for session store persistence
  - Ensure input items are never flattened to messages — the list structure is the contract
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 4.1, 4.2, 4.3, 4.5_

- [x] 2.2 (P) Implement the Responses protocol error hierarchy
  - Create `ResponsesProtocolError` extending `LLMProxyError` with `message`, `code`, `param`, and `status_code`
  - Create `ResponsesValidationError` for client request validation failures
  - Create `ResponsesPreviousResponseNotFoundError` for unresolvable `previous_response_id`
  - Create `ResponsesProviderLimitationError` for features that cannot be preserved for a given backend
  - Register error-to-HTTP mapping in the transport exception adapter so all new error types produce Responses API-compatible error shapes
  - _Requirements: 1.4, 1.5, 1.6, 3.4, 6.3, 7.1, 7.2, 7.3_

- [x] 3. Implement request normalizer
  - Create `ResponsesRequestNormalizer` that accepts a raw dict (HTTP body or WS event payload) and returns a validated `ResponsesDomainRequest`
  - Validate that `model` is present; raise `ResponsesValidationError` with a client-visible code when missing
  - Normalize string `input` shorthand to a single-item message list without flattening to chat messages
  - Preserve all optional fields with their semantic meaning intact
  - Detect mutually incompatible field combinations and raise `ResponsesValidationError` (not a backend error)
  - Write unit tests covering valid inputs, missing model, string shorthand, array items, and invalid field combinations
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

- [x] 4. Implement session store for conversation linkage
  - Define `IResponsesSessionStore` protocol with `store(response_id, output_items, ttl_seconds)` and `resolve(previous_response_id)` async methods
  - Implement `InMemoryResponsesSessionStore` backed by a TTL-aware dict with an `asyncio.Lock` for safe concurrent access
  - Default TTL of 3600 seconds, configurable at construction time
  - `resolve` returns `None` when the id is not found or has expired; caller raises `ResponsesPreviousResponseNotFoundError`
  - Reject requests that provide both `previous_response_id` and `conversation`, and ensure `instructions` replaces prior instructions when chaining by `previous_response_id`
  - Register `IResponsesSessionStore` in the DI container via `ProcessorStage` so it is available to the controller
  - Write unit tests for store/resolve round-trip, TTL expiry, and missing-id behavior
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

- [x] 5. Implement event normalizer and wire renderer
- [x] 5.1 Implement the semantic event normalizer
  - Create `ResponsesSemanticEventType` enum and `ResponsesSemanticEvent` model covering all lifecycle event types: created, in_progress, output_item_added/done, content_part_added/done, text_delta/done, tool_call_args_delta/done, completed, failed, incomplete, plus passthrough events for unknown or built-in tool event families
  - Create `ResponsesEventNormalizer` that accepts an `AsyncGenerator` of provider chunks and emits `ResponsesSemanticEvent` objects
  - Handle OpenAI native path (already Responses events), Anthropic SSE chunks, and Gemini SSE chunks
  - Emit official positional fields (`output_index`, `content_index`, `item_id`) and a monotonically increasing `sequence_number` for every normalized event
  - Guarantee a terminal event (`response.completed` or `response.failed`) is always emitted even when the upstream errors mid-stream
  - Write unit tests for each provider's chunk-to-event mapping, passthrough behavior, official field naming, `sequence_number` progression, and the terminal-event guarantee
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9_

- [x] 5.2 Implement the wire renderer for SSE and WebSocket transports
  - Create `ResponsesWireRenderer` that accepts an `AsyncGenerator[ResponsesSemanticEvent]` and yields canonical SSE strings or WS dicts depending on transport mode
  - Enforce canonical event ordering with transport-correct terminal behavior: HTTP SSE ends with `response.completed`/`response.failed`/`response.incomplete` plus `[DONE]`; beta `/v1/responses` WebSocket handling must follow the verified contract for that specific transport surface and must not assume Realtime `response.done` unless that transport is explicitly Realtime
  - Ensure all rendered frames preserve official field names and `sequence_number`
  - After the terminal event, store completed output items in `IResponsesSessionStore`
  - Write unit tests pinning SSE frame ordering, WS frame ordering, official field names, `sequence_number` progression, passthrough events, and transport-correct terminal behavior
  - _Requirements: 1.2, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 2.5, 2.6, 7.4, 7.5_

- [x] 6. Implement backend projectors
- [x] 6.1 Implement the OpenAI native Responses projector
  - Create `OpenAIResponsesProjector` implementing `IResponsesBackendProjector`
  - Pass `input`, `instructions`, `previous_response_id`, `conversation`, `tools`, and all standard fields through natively without flattening — OpenAI supports the Responses API wire format directly
  - Preserve passthrough parameters such as `include`, `max_tool_calls`, `prompt`, `prompt_cache_key`, `prompt_cache_retention`, `service_tier`, `truncation`, `store`, and other supported fields unchanged
  - Return empty `capability_flags` list since all features are natively supported
  - Write unit tests verifying the payload shape and that no flattening occurs
  - _Requirements: 6.1, 6.4, 6.5, 6.6_

- [x] 6.2 (P) Implement the Anthropic Responses projector
  - Create `AnthropicResponsesProjector` implementing `IResponsesBackendProjector`
  - Project `ResponsesInputItem` list to Anthropic `messages` array and `system` string, preserving tool-call linkage via `tool_use`/`tool_result` content blocks
  - Inject prior output items from the session store into the message context for multi-turn continuity
  - Preserve and forward supported optional parameters unchanged where Anthropic can represent them; detect unsupported parameters or event families and raise `ResponsesProviderLimitationError` instead of silently dropping them
  - Write unit tests for item-to-messages projection, tool-call linkage preservation, prior-context injection, and unsupported-feature detection
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 4.1, 4.2, 4.3, 4.5_

- [x] 6.3 (P) Implement the Gemini Responses projector
  - Create `GeminiResponsesProjector` implementing `IResponsesBackendProjector`
  - Project `ResponsesInputItem` list to Gemini `contents` array, mapping function calls to `functionCall`/`functionResponse` parts
  - Preserve and forward supported optional parameters unchanged where Gemini can represent them; detect unsupported parameters or event families and raise `ResponsesProviderLimitationError` instead of silently dropping them
  - Write unit tests for item-to-contents projection, function-call part mapping, and unsupported-feature detection
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 4.1, 4.2, 4.3, 4.5_

- [x] 7. Wire all components into the controller
  - Update `ResponsesController` to inject `IResponsesSessionStore` and the appropriate `IResponsesBackendProjector` via DI instead of using the per-connection `response_cache` dict
  - Replace the existing `responses_to_domain_request` call with `ResponsesRequestNormalizer.normalize`
  - Add `previous_response_id` resolution: call `session_store.resolve`, raise `ResponsesPreviousResponseNotFoundError` on miss, inject prior items into the domain request
  - Route the domain request through the selected backend projector to obtain the provider payload
  - Pipe the provider stream through `ResponsesEventNormalizer` then `ResponsesWireRenderer` for both HTTP SSE and WebSocket transports
  - Ensure `request_id` is preserved in all error responses for correlation
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 7.1, 7.2, 7.3, 7.4, 7.5_

- [x] 8. Integration tests and contract fixture cleanup
  - Local contract, unit, integration, and spec-state validation are green; keep this spec active until live end-to-end proxy verification is completed through the client-facing `/v1/responses` surface.
- [x] 8.1 Write integration tests for the full HTTP and WebSocket flows
  - HTTP streaming: assert full SSE lifecycle from POST request through the verified terminal sequence and `[DONE]` sentinel only if the official endpoint uses it
  - WebSocket: assert verified `response.create` frame shape sent upstream, then canonical lifecycle events through the transport-correct terminal event
  - Multi-turn: assert `previous_response_id` is resolved from the session store across two sequential requests
  - Provider limitation: assert Anthropic path with an unsupported feature returns a `provider_limitation` error response
  - Error correlation: assert `request_id` is present in all error shapes
  - Unknown event families: assert built-in tool or passthrough event frames are preserved without field loss or reordering
  - _Requirements: 1.1, 1.2, 1.6, 2.1, 2.6, 3.1, 3.2, 3.3, 3.4, 5.1, 5.3, 5.4, 5.7, 5.8, 5.9, 6.3, 7.1, 7.2, 7.3_

- [x] 8.2 Pin contract fixtures and remove broken test file
  - Create reference fixtures pinning canonical SSE event ordering, `sequence_number` progression, official positional field names, WS frame shapes, and error response shapes for each error code
  - Write contract tests that assert the live renderer output matches the pinned fixtures
  - Remove or rename the existing `.broken` test file that was left from the previous implementation
  - _Requirements: 2.1, 2.2, 5.1, 5.2, 5.3, 5.6, 5.7, 5.8, 5.9, 7.1, 7.3_

- [ ] 9. Run live end-to-end proxy verification before declaring completion or archiving
  - _Spec metadata_: `spec.json` `phase` is `awaiting-operator-live-verification` while tasks **9** / **10.4** stay open; `ready_for_implementation` stays `false` until all tasks are done (Kiro linter). Automated pytest coverage does not satisfy this item.
  - Execute live HTTP `/v1/responses` verification against the proxy's client-facing frontend and confirm the pinned contract still holds when the request traverses the real translation layer
  - Execute live WebSocket verification against the proxy's client-facing `/v1/responses` surface and confirm terminal event behavior remains correct on the active transport path
  - Cover at least one native Responses backend path and at least one translated backend path so the client-facing contract is validated across backend flavors, not just mocked internals
  - Reconcile any fixture, implementation, or backend-adaptation drift discovered during live verification before marking the spec complete or archiving it
  - _Requirements: 1.2, 1.6, 5.2, 5.7, 6.1, 6.4, 7.1, 7.3_

- [x] 10. Close backend-flavor coverage gaps against the intended translation matrix
  - Confirm the implemented projector/routing matrix explicitly covers Responses API frontend to native Responses backend, legacy OpenAI-style backend, Anthropic, and Gemini
  - If any backend flavor still relies on lossy chat-only adaptation or bypasses the canonical Responses event pipeline, create targeted implementation and live-verification sub-tasks before declaring the spec complete
  - Add or extend integration coverage to prove the proxy can accept client-facing Responses API requests and translate them correctly for each supported backend flavor without requiring client protocol changes
  - _Requirements: 2.3, 5.5, 6.1, 6.2, 6.3, 6.4, 6.5, 6.8, 7.5_

- [x] 10.1 Audit native Responses backend path end-to-end
  - Verify the client-facing `/v1/responses` frontend reaches the native Responses backend path without lossy fallback to chat-only abstractions
  - Confirm request fields, streaming lifecycle events, and terminal response semantics stay on the canonical Responses pipeline for this path
  - Record any gaps as concrete implementation defects with matching test expectations before changing code
  - _Requirements: 2.3, 5.5, 6.1, 6.4, 7.5_

- [x] 10.2 Audit legacy OpenAI-style backend translation path end-to-end
  - Verify the client-facing `/v1/responses` frontend can translate to legacy OpenAI-style backend surfaces without requiring client protocol changes
  - Confirm typed input items, tool-call linkage, streaming event normalization, and final response equivalence are preserved or surfaced as explicit limitation errors
  - Identify any remaining lossy chat-only adaptation points and convert them into implementation tasks with regression tests
  - _Requirements: 2.3, 4.1, 4.2, 5.5, 6.2, 6.3, 6.8, 7.5_

- [x] 10.3 Audit Anthropic and Gemini translation paths against the frontend contract
  - Verify the client-facing `/v1/responses` frontend preserves the intended Responses semantics when routed to Anthropic and Gemini projectors
  - Confirm unsupported features become explicit `provider_limitation` outcomes rather than silent degradation
  - Add or update integration coverage where the current matrix does not prove the end-to-end translated behavior
  - _Requirements: 4.1, 4.2, 5.5, 6.1, 6.2, 6.3, 6.4, 6.5, 7.5_

- [ ] 10.4 Run backend-flavor live-through-proxy verification and reconcile outcomes
  - _Spec metadata_: completion of this task (with evidence) is the signal to move `spec.json` to a completed/archived phase; see `OPERATOR_LIVE_VERIFICATION_10.4.md`.
  - Execute live-through-proxy verification for at least one native Responses path and one translated backend-flavor path using the client-facing `/v1/responses` surface
  - Confirm the verified matrix matches the documented contract fixtures, or update implementation/tests/spec tasks if the live path proves otherwise
  - Only mark task 10 complete when the backend-flavor matrix is proven or explicitly narrowed with documented limitations
  - Preferred live matrix: (a) one native Responses backend path exposed through the proxy frontend, and (b) one translated backend-flavor path such as Anthropic, Gemini, or legacy OpenAI-style routing through the same frontend contract
  - Verification artifacts must come from real client-style calls through the proxy surface (HTTP and, where configured, WebSocket) rather than direct backend connector invocation
  - If credentials or runtime environment are unavailable, leave this task pending and document the exact command set, backend selectors, and expected assertions needed for a future operator-run verification
  - Operator-run playbook (pending live evidence in this repo): `.kiro/specs/responses-api-frontend-compliance/OPERATOR_LIVE_VERIFICATION_10.4.md`
  - _Requirements: 5.5, 6.1, 6.4, 6.5, 6.8, 7.5_
