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

### Tiered configuration (mirrors in-chat loop detection)
- **Server-level defaults** (env/config):
  - `TOOL_LOOP_DETECTION_ENABLED` (bool, default true)
  - `TOOL_LOOP_MAX_REPEATS` (int, default 4)
  - `TOOL_LOOP_TTL_SECONDS` (int, default 120)
  - `TOOL_LOOP_MODE` ("break" | "chance_then_break", default "break")
- **Backend+model overrides**:
  - Extend `ModelDefaults` with optional fields: `tool_loop_detection_enabled`, `tool_loop_detection_max_repeats`, `tool_loop_detection_ttl_seconds`, `tool_loop_detection_mode`.
  - Apply into `ProxyState.apply_model_defaults` only if session doesn’t already override.
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
- **Streaming**: Skip tool-call enforcement for streaming responses (we don’t build `tool_calls` there). Continue existing in-chat loop detection for text streams.

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
- Mirror the proxy’s command error envelope: one choice with assistant message containing a concise explanation like:
  - "Tool call loop detected: '<tool_name>' invoked with identical params <N> times within <TTL>s. Session stopped to prevent unintended looping."
  - Include a guidance hint to adjust inputs or strategy.

## TODO (phased checklist)

### Phase 1: Scaffolding & configuration
- [x] Create `src/tool_call_loop/config.py` with `ToolCallLoopConfig` and validation.
- [x] Add env config keys to `src/core/config.py` and propagate to app `config` dict.
- [x] Document defaults and env usage.

### Phase 2: Session and model-tier overrides
- [x] Extend `src/models.py` `ModelDefaults` with tool-loop fields.
- [x] Update `ProxyState` with session-level fields and setters/unsetters.
- [x] Apply model defaults in `ProxyState.apply_model_defaults` (respect session override precedence).

### Phase 3: Command interface
- [x] Update `src/commands/set_cmd.py` to accept `tool-loop-*` keys with validation.
- [x] Update `src/commands/unset_cmd.py` to unset the new keys.
- [x] Add examples to command help/docs.

### Phase 4: Tracker implementation
- [x] Implement `src/tool_call_loop/tracker.py` with TTL pruning and repeat counting.
- [x] Initialize `app.state.tool_loop_trackers` at app startup.
- [x] Add DEBUG logs for recorded signatures and pruning.

### Phase 5: Enforcement integration
- [x] In `ChatService._process_backend_response`, extract tool calls and compute signatures.
- [x] Resolve effective config (session → model → server) and short-circuit when disabled.
- [x] Implement "break" mode: synthesize error and block forwarding.
- [x] Implement "chance_then_break" mode: inject guidance tool-failure message, re-call backend once; allow if signature changes, else break.
- [x] Ensure streaming path is unaffected.

### Phase 6: Tests
- [x] Unit tests for tracker (TTL, repeat counting, consecutive behavior).
- [x] Integration tests for both modes and precedence order.
- [x] Tests for disabled mode and TTL expiry behavior.

### Phase 7: Documentation & polish
- [x] Update `README.md` with configuration keys and examples.
- [x] Add troubleshooting notes for false positives and model behaviors.
- [x] Ensure logs are clear and actionable (no secrets, concise context).


