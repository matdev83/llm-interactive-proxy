# Codex Connector Redesign for Delta-Style, Cache-Friendly, Quota-Efficient Operation

## Summary
Redesign the `openai-codex` connector around proxy-managed Codex continuation so the proxy can stop replaying full session snapshots on every turn, preserve agent-family compatibility, and remain quota-efficient under OpenCode/Kilo/Droid constraints.

Chosen defaults:
- Proxy owns Codex continuation for this backend when the client does not send `previous_response_id`.
- Redesign is done as one cohesive implementation wave, not a patch series.
- Continuation state is ephemeral only: in-memory TTL/LRU, rebuilt safely after restart.
- Client-supplied `previous_response_id` always wins over proxy-synthesized lineage.

## Key Changes

### 1. Add a Codex continuation coordinator as the new source of session truth
- Introduce an internal service such as `ICodexContinuationCoordinator` with an in-memory TTL/LRU store.
- Store lineage per isolation key composed from:
  - proxy session id
  - backend type
  - effective model
  - active account/auth identity
  - client family
  - prompt/bootstrap fingerprint
  - tool-schema fingerprint
- Stored state must include at least:
  - active `prompt_cache_key`
  - last successful upstream `response_id`
  - whether the Codex chain has been bootstrapped
  - last bootstrap fingerprints
  - last successful transport/account/model metadata
- Invalidate lineage on:
  - backend/account/model change
  - prompt/bootstrap hash change
  - tool schema hash change
  - client-family change
  - explicit client reset/new conversation
  - `previous_response_not_found`
  - incompatible continuity conditions detected by proxy session logic

### 2. Make payload construction continuation-aware instead of replay-oriented
- Extend `CodexPayload` to carry `previous_response_id`.
- Preserve `previous_response_id` from Responses input passthrough; stop dropping it in the passthrough field whitelist.
- For continued Codex chains:
  - send only delta input for the new turn
  - do not resend the full accumulated conversation
  - do not resend environment context, static system instructions, or agent bridge bootstrap unless the chain is new/reset
- For new/reset chains:
  - send the full bootstrap once
  - establish `prompt_cache_key`
  - then switch future turns to delta mode
- Keep one controlled fallback path:
  - if continuation fails with `previous_response_not_found` or equivalent continuity failure, clear lineage and resend one safe replay/bootstrap request to recover

### 3. Split “bootstrap” guidance from “per-turn” payload so compatibility does not burn quota
- Treat Codex default prompt, environment context, and agent-family bridge guidance as chain bootstrap state, not recurring turn content.
- Keep the OpenCode bridge semantics, but inject them only when starting/resetting a Codex chain.
- Stop appending the full Codex default instructions on every passthrough turn.
- Replace the current “always force instructions” rule with:
  - full instructions/bootstrap on chain start/reset
  - no repeated static instructions on continued turns
  - minimal fallback only if upstream rejects an empty bootstrap on first turn
- Keep `prompt_cache_key` stable for the life of a valid chain; never regenerate it mid-chain except on invalidation/reset.

### 4. Preserve agent-specific tool compatibility without re-breaking caching
- Refactor `OpenCodeClientFamilyAdapter` so it no longer strips item `id`s or nested item `id`s on normal paths.
- Preserve raw `function_call`, `function_call_output`, `metadata`, and `item_reference` fields whenever they are valid for Codex continuity.
- Keep current OpenCode tool alias behavior:
  - `bash` / `shell` / `local_shell_call`
  - `apply_patch` restrictions
  - incompatible-tool retry steering
- Make incompatible-tool steering transient:
  - added only for the retrying request
  - not accumulated into long-lived chain bootstrap
- Preserve Kilo/Droid translation behavior as-is, but make their compatibility additions participate in the same bootstrap/delta separation:
  - stable compatibility instructions go into bootstrap fingerprinting
  - per-turn translated tool results remain delta items
- Define one explicit rule for orphaned tool outputs:
  - only coerce/orphan-rewrite when replay fallback is required and the delta slice cannot reference an upstream-known tool call
  - otherwise keep native Responses items unchanged

### 5. Make executor and transport own lineage updates and observability
- After each successful terminal response, capture the upstream response id and commit it to the continuation coordinator.
- Do not advance lineage on incomplete/failed streams.
- Clear lineage when auth rotation or account switching changes the backend identity used for the chain.
- Pass full connector request context into websocket transport so outbound `response.create` frames are actually captured.
- Keep HTTP and WebSocket behavior aligned:
  - both transports must accept/send `previous_response_id`
  - both must update lineage from terminal response ids
  - both must use the same invalidation logic
- Add structured diagnostics on every request:
  - chain mode: `bootstrap`, `continued_delta`, `fallback_replay`
  - whether `previous_response_id` was client-supplied or proxy-synthesized
  - prompt/bootstrap hash
  - tool-schema hash
  - input item count and serialized input size
  - instructions byte count
  - tools byte count
  - invalidation reason when applicable

### 6. Keep public behavior compatible while tightening internal boundaries
Important interface/type changes:
- `CodexPayload.previous_response_id: str | None`
- New internal continuation service interface and state type
- Payload builder becomes continuation-aware but remains transport-agnostic
- Compatibility adapters stop owning ad-hoc caching decisions; they provide:
  - bootstrap fragments
  - delta item adaptation
  - transient retry steering
- External client contract remains backward-compatible:
  - no required client changes
  - Responses passthrough continues to work
  - client-provided `previous_response_id` remains honored

## Test Plan
- Payload passthrough preserves:
  - `previous_response_id`
  - item `id`
  - nested item `id`
  - `metadata`
  - `item_reference`
  - native `function_call_output`
- OpenCode adapter preserves IDs and no longer undoes the generic caching fix.
- Second and later turns in a valid chain:
  - reuse prior `response_id`
  - omit repeated Codex system prompt
  - omit repeated environment context
  - omit repeated OpenCode bridge bootstrap
  - send only delta turn items
- Chain reset occurs on:
  - tool schema change
  - model change
  - account/auth rotation
  - client-family change
  - bootstrap fingerprint change
- `previous_response_not_found` triggers exactly one fallback replay, then re-establishes lineage.
- Incompatible OpenCode tool retry steering remains preserved and is not permanently accumulated into lineage.
- WebSocket outbound capture includes `response.create` frames with `previous_response_id` when used.
- End-to-end regression coverage for:
  - native Responses passthrough
  - OpenCode compatibility
  - Kilo compatibility
  - Droid compatibility
  - non-stream and stream Codex flows
- Add quota-efficiency assertions:
  - turn 2+ payload instruction bytes drop sharply versus turn 1
  - turn 2+ input item count reflects delta-only behavior
  - stable chain keeps `prompt_cache_key` constant

## Assumptions
- Proxy-managed continuation is enabled only for `openai-codex`, not generalized to other backends in this change.
- Continuation state is ephemeral and in-memory only; restart loses lineage and recovery happens through fallback replay.
- Existing proxy session id remains the user-facing continuity anchor; Codex lineage is derived from it, not exposed as a new external session API.
- Compatibility for OpenCode is a hard requirement and must not regress even if Codex-native tools are unavailable.
- The redesign may change on-wire Codex request shape for continued turns, but must not require changes from existing clients.
