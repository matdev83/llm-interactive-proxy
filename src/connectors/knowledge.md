# OpenAI Codex Connector Knowledge

## Purpose

The `openai-codex` backend enables users to leverage ChatGPT Plus subscription allowances via OAuth authentication from the codex-cli command-line tool. This is distinct from the standard OpenAI API - it uses personal OAuth tokens and routes through the Codex Responses API endpoint.

## Critical Implementation Details

### Race Condition Prevention

**CRITICAL**: Token loading and refresh must be protected by `_token_refresh_lock`
- ✅ `_refresh_access_token()` loads credentials inside the lock
- ✅ `chat_completions()` relies on initialization, does NOT call `_load_auth()` unprotected
- ❌ Never call `_load_auth()` outside the lock during request processing - creates race windows

### Atomic File Writes

When persisting refreshed tokens:
1. Create temp file in same directory: `tempfile.mkstemp(dir=parent)`
2. Write JSON + flush + `os.fsync()` to ensure disk persistence
3. Atomic replace: `os.replace(temp_path, auth_path)` (cross-platform)
4. Clean up temp file on any error

This prevents file corruption when multiple processes access auth.json concurrently.

### Thread-Safe File Watching

Use `threading.Event` instead of manual boolean flags:
- `_reload_scheduling_event.is_set()` - check if reload in progress (thread-safe)
- `_reload_scheduling_event.set()` - mark reload started
- `_reload_scheduling_event.clear()` - mark reload completed

This prevents duplicate reload tasks from file watcher events.

## Dual Translation Paths

The connector has **two separate tool call handling modes**:

### 1. Legacy XML Mode (`tool_text_format: codex_xml`)
- For Cline/Kilo/Roocode agents
- Parses textual tool invocations like `<execute_command>`
- Matches text results back to invocations
- Maintains `pending_tool_call_records` for matching

### 2. Canonical Mode (default)
- For standard OpenAI clients (Continue.dev, Cursor, etc.)
- Uses structured `tool_calls` arrays from messages
- More robust, no text parsing
- Does NOT parse textual tool invocations

**Important**: These paths are mutually exclusive. Clients get one or the other based on capabilities.

## Passthrough Detection

`_is_native_responses_payload()` detects if a request is already in Codex/Responses format:

**Strict validation rules**:
1. If has `messages` array without Responses-specific fields → NOT passthrough
2. If has `input` array, must validate structure (type/role/content)
3. Check for Responses-specific fields: `prompt_cache_key`, `include`, `store`

**Do NOT** rely solely on presence of `input` or `instructions` - too broad.

## Tool Schema Modes

### codex_default
- Uses built-in: shell, apply_patch, view_image
- Best for general Codex CLI compatibility

### merge_custom
- Merges request tools with defaults
- **Collision handling**: If name matches but parameters differ → keep default, log warning
- Use when extending Codex toolset

### custom_only
- Replaces defaults entirely
- Risky - Codex may expect standard tools
- Only for advanced use cases

## Prompt Management

### Empty Prompt Handling

`_resolve_system_prompt()` now returns `str` (never None):
- Empty prompts return `""` instead of `None`
- Prevents downstream None handling issues
- Empty string means "use model default"

### Prompt Modes

- **codex_default**: Codex prompt + custom additions
- **merge_custom**: Same as codex_default
- **custom_only**: Only custom, optionally falls back to default if empty

## Configuration Validation

Tool schemas are validated with `_validate_tool_schema()`:
- Requires `name` field (string)
- Validates `description` is string if present
- Validates `parameters` is object with `type: object`
- Invalid schemas logged and skipped

## Common Pitfalls

### DO NOT:
- Call `_load_auth()` during request processing outside the refresh lock
- Modify auth.json without atomic writes
- Rely on `_reload_scheduling_in_progress` flag (replaced with Event)
- Assume passthrough based solely on `input` field presence

### DO:
- Let initialization handle initial credential loading
- Use `_token_refresh_lock` for any credential operations
- Monitor logs for tool schema collision warnings
- Use `codex_default` schema mode unless you have specific needs

## Limitations

### Known Gaps
1. **Streaming token refresh**: Configurable retry budget (default 2) with automatic token refresh on handshake or chunk authentication failures; further enhancements like resumable offsets remain future work.
2. **Proactive token refresh**: Waits for 401, doesn't predict expiration
3. **Renderer integration**: Only complete for `codex_xml` mode
4. **Canonical mode text parsing**: Doesn't parse textual tool invocations

### Testing Gaps
- No concurrent token refresh tests
- No streaming mid-expiry tests
- No cross-frontend integration tests
- No renderer mode coverage beyond XML

## Future Work

### High Priority
1. Implement streaming token refresh with retry wrapper
2. Complete renderer integration for all modes OR remove unused renderers

### Medium Priority
3. Add proactive token refresh (parse JWT exp field)
4. Add comprehensive integration tests
5. Simplify configuration system (~400 lines is too complex)

### Low Priority
6. Protocol negotiation instead of heuristic detection
7. Session-scoped tool call state (not global)
8. Verify against actual codex-cli source when available

## Related Files

- `_openai_codex_capabilities.py` - Capability resolution
- `_openai_codex_request_translator.py` - Request translation
- `docs/openai_codex.md` - Configuration guide
- `src/core/domain/translation.py` - Response translation utilities
- `src/core/services/tool_text_renderer.py` - Tool text rendering system
