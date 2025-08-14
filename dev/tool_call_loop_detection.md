## Tool-call loop detection: design and plan

### Overview
Add a server-side tool-call loop detector that tracks model-issued tool calls and prevents tight repetition loops. The detector uses a tiered configuration scheme aligned with existing in-chat loop detection: server defaults, per-(backend, model-id) overrides, and session-level overrides via in-chat commands.

### Design
- **Tracking scope**: Per session, track tool calls as tuples of (datetime, tool name, canonicalized parameters).
- **Canonicalization**: Parse the tool `function.arguments` JSON and re-dump with `sort_keys=True` to produce a stable signature string.
- **TTL-based pruning**: Ignore and drop entries older than the configured TTL window.
- **Repeat detection**: Consecutive identical signatures increment a counter; reaching the threshold triggers resolution behavior.
- **Resolution modes**:
  - **break (default)**: When threshold is reached, stop forwarding the tool call to the client and return an error to the user.
  - **chance_then_break**: On first detection, do not forward the call. Instead inject a tool-failure message instructing the model to self-reflect and correct. If the next tool call differs, allow it; if it repeats the same signature again, break.

### Logging
- **WARNING level**: All detected loops must be logged at WARNING level with crucial details:
  - Session ID
  - Tool name
  - Repetition count
  - TTL window
  - Truncated signature (first ~50 chars)
  - Model and backend in use
  - Resolution action taken (break or chance given)
  - Timestamp
- **Format**: `Tool call loop detected in session {session_id}: tool={tool_name}, repeats={count}/{max_repeats}, window={ttl}s, model={model}, backend={backend}, action={action}, signature={signature[:50]}...`
- **DEBUG level**: Additional details like full signatures and parameters should be logged at DEBUG level only.

### Tiered configuration (mirrors in-chat loop detection)
- **Server-level defaults** (env/config):
  - `TOOL_LOOP_DETECTION_ENABLED` (bool, default true)
  - `TOOL_LOOP_MAX_REPEATS` (int, default 4)
  - `TOOL_LOOP_TTL_SECONDS` (int, default 120)
  - `TOOL_LOOP_MODE` ("break" | "chance_then_break", default "break")
- **Backend+model overrides**:
  - Extend `ModelDefaults` with optional fields: `tool_loop_detection_enabled`, `tool_loop_detection_max_repeats`, `tool_loop_detection_ttl_seconds`, `tool_loop_detection_mode`.
  - Apply into `ProxyState.apply_model_defaults` only if session doesn't already override.
- **Session-level overrides**:
  - Extend `ProxyState` with optional properties and setters/unsetters for the above.
  - Add in-chat commands to set/unset:
    - `!/set(tool-loop-detection=true|false)`
    - `!/set(tool-loop-max-repeats=4)`
    - `!/set(tool-loop-ttl=120)`
    - `!/set(tool-loop-mode=break|chance|chance_then_break)`
    - `!/unset(tool-loop-detection, tool-loop-max-repeats, tool-loop-ttl, tool-loop-mode)`

### Tracking and enforcement
- **Where to intercept**: In `ChatService._process_backend_response` for non-streaming responses, before returning to the client.
- **What to track**: For each choice, inspect `message.tool_calls[*].function.{name, arguments}`.
- **Effective config resolution**: session overrides → model defaults applied to session → server defaults.
- **Disabled behavior**: If disabled by effective config, skip tracking entirely for performance.
- **On threshold**:
  - Mode "break": synthesize a user-facing error (OpenAI-like response with `finish_reason="error"`) and do not forward the tool call.
  - Mode "chance_then_break": inject a single tool-failure message back to the model with guidance text; accept next call if signature changes; otherwise break on next identical signature.
- **Streaming**: Skip tool-call enforcement for streaming responses (we don't build `tool_calls` there). Continue existing in-chat loop detection for text streams.

### Wiring and state
- New module `src/tool_call_loop/config.py` providing `ToolCallLoopConfig` with `from_env_vars` and `from_dict` helpers.
- New module `src/tool_call_loop/tracker.py` providing per-session `ToolCallTracker` with TTL pruning and repeat counting.
- Initialize `app.state.tool_loop_trackers: dict[str, ToolCallTracker]` during app setup.
- Expose server defaults via `config` (already passed into `ChatService`).

### Validation and tests
- Reaching threshold returns an error in "break" mode and does not forward tool call.
- "Chance-then-break": first detection injects tool-failure guidance; if subsequent tool call differs, allow; else break.
- Disabled mode: no tracking or overhead.
- TTL expiry resets the consecutive repeat context.
- Precedence order validated: session > model defaults > server.

### Config keys and commands
- Env vars: `TOOL_LOOP_DETECTION_ENABLED`, `TOOL_LOOP_MAX_REPEATS`, `TOOL_LOOP_TTL_SECONDS`, `TOOL_LOOP_MODE`.
- In-chat commands: `!/set(tool-loop-…)` and `!/unset(tool-loop-…)` as listed above.

### Error response shape
- Mirror the proxy's command error envelope: one choice with assistant message containing a concise explanation like:
  - "Tool call loop detected: '<tool_name>' invoked with identical params <N> times within <TTL>s. Session stopped to prevent unintended looping."
  - Include a guidance hint to adjust inputs or strategy.

## TODO (phased checklist)

### Phase 1: Scaffolding & configuration
- [ ] Create `src/tool_call_loop/config.py` with `ToolCallLoopConfig` and validation.
- [ ] Add env config keys to `src/core/config.py` and propagate to app `config` dict.
- [ ] Document defaults and env usage.

### Phase 2: Session and model-tier overrides
- [ ] Extend `src/models.py` `ModelDefaults` with tool-loop fields.
- [ ] Update `ProxyState` with session-level fields and setters/unsetters.
- [ ] Apply model defaults in `ProxyState.apply_model_defaults` (respect session override precedence).

### Phase 3: Command interface
- [ ] Update `src/commands/set_cmd.py` to accept `tool-loop-*` keys with validation.
- [ ] Update `src/commands/unset_cmd.py` to unset the new keys.
- [ ] Add examples to command help/docs.

### Phase 4: Tracker implementation
- [ ] Implement `src/tool_call_loop/tracker.py` with TTL pruning and repeat counting.
- [ ] Initialize `app.state.tool_loop_trackers` at app startup.
- [ ] Add DEBUG logs for recorded signatures and pruning.
- [ ] Add WARNING logs for detected loops with all crucial details.

### Phase 5: Enforcement integration
- [ ] In `ChatService._process_backend_response`, extract tool calls and compute signatures.
- [ ] Resolve effective config (session → model → server) and short-circuit when disabled.
- [ ] Implement "break" mode: synthesize error and block forwarding.
- [ ] Implement "chance_then_break" mode: inject guidance tool-failure message, re-call backend once; allow if signature changes, else break.
- [ ] Ensure streaming path is unaffected.
- [ ] Log all loop detections at WARNING level with detailed context.

### Phase 6: Tests
- [ ] Unit tests for tracker (TTL, repeat counting, consecutive behavior).
- [ ] Integration tests for both modes and precedence order.
- [ ] Tests for disabled mode and TTL expiry behavior.
- [ ] Verify logs contain all required fields at appropriate levels.

### Phase 7: Documentation & polish
- [ ] Update `README.md` with configuration keys and examples.
- [ ] Add troubleshooting notes for false positives and model behaviors.
- [ ] Ensure logs are clear and actionable (no secrets, concise context).
