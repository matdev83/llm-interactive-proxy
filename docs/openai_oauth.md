# OpenAI OAuth Backend Configuration

The `openai-oauth` connector now exposes a configuration surface that lets you
control capability defaults, prompt management, renderer selection, and tool
schema injection without touching the source code. All options live under the
`backends.openai_oauth.extra.codex` section of your application config and can
be overridden with dedicated environment variables.

## Capability Defaults

The connector derives a `CodexClientCapabilities` profile for every request.
You can override the defaults globally:

```yaml
backends:
  openai_oauth:
    extra:
      codex:
        default_capabilities:
          tool_text_format: codex_xml
          fallback_tool_text_format: summary
          prompt_mode: merge_custom
          tool_schema_mode: merge_custom
          include_environment_context: false
```

Environment override: set `OPENAI_OAUTH_DEFAULT_CAPABILITIES` to a JSON mapping
with the same keys (e.g. `{"prompt_mode":"custom_only"}`).

Agent-specific capability defaults can be registered via
`agent_capabilities` (mapping of agent name → capability overrides) or the
`OPENAI_OAUTH_AGENT_CAPABILITIES` environment variable.

## Tool Text Renderer Registry

Renderer selection is capability-driven. The registry ships with these built-ins:

| Key        | Behaviour                                                                      |
|------------|---------------------------------------------------------------------------------|
| `none`     | No textual overlay (default)                                                    |
| `xml`      | Legacy Codex CLI `<execute_command>`, `<apply_diff>`, `<view_image>` envelopes |
| `markdown` | Markdown code fences / image links                                              |
| `summary`  | Concise `[tool:name] {json}` fall back                                          |

Configuration example:

```yaml
backends:
  openai_oauth:
    extra:
      codex:
        renderer:
          default: markdown        # default for tool_text_format when unset
          fallback: summary        # used if the active renderer returns None
          aliases:
            codex_xml: xml         # extra alias beyond the built-in one
            cli: xml
          modules:
            custom: "myapp.renderers.CustomRenderer"
```

Setting `renderer.default` automatically updates the default capability unless
you explicitly set `tool_text_format` elsewhere. Renderer configuration can also
be supplied via environment variables:

- `OPENAI_OAUTH_RENDERER_DEFAULT`
- `OPENAI_OAUTH_RENDERER_FALLBACK`
- `OPENAI_OAUTH_RENDERER_ALIASES` (JSON mapping)
- `OPENAI_OAUTH_RENDERER_MODULES` (JSON mapping, values must be `module.Class`)

## Prompt Management

You can prepend or append additional guardrails to the Codex system prompt or
replace it entirely.

```yaml
backends:
  openai_oauth:
    extra:
      codex:
        prompt:
          template: |
            You are Codex running in secure mode.
          prepend:
            - "<policy>All network calls must be approved.</policy>"
          append:
            - "<logging>Summarise executed commands.</logging>"
          deduplicate: true
          fallback_to_default: true
```

- `template` overrides the bundled `gpt_5_codex_prompt.md`.
- `prepend` / `append` accept string or list values.
- `deduplicate` (default: `true`) prevents repeated sections.
- `fallback_to_default` (default: `true`) controls whether `custom_only` requests
  fall back to the Codex prompt when no custom instructions are supplied.

Environment overrides:

| Variable                               | Description                                  |
|----------------------------------------|----------------------------------------------|
| `OPENAI_OAUTH_PROMPT_TEMPLATE`         | Replacement prompt text                      |
| `OPENAI_OAUTH_PROMPT_PREPEND`          | JSON string or comma-separated list          |
| `OPENAI_OAUTH_PROMPT_APPEND`           | JSON string or comma-separated list          |
| `OPENAI_OAUTH_PROMPT_DEDUPLICATE`      | `true` / `false`                             |
| `OPENAI_OAUTH_PROMPT_FALLBACK_DEFAULT` | `true` / `false`                             |

## Tool Schema Providers

The connector offers three schema modes: `codex_default`, `merge_custom`, and
`custom_only`. You can redefine the baseline schema or supply reusable custom
tool definitions.

```yaml
backends:
  openai_oauth:
    extra:
      codex:
        tool_schema:
          base_tools:
            - type: function
              name: echo
              description: Echo text
              parameters:
                type: object
                properties:
                  text:
                    type: string
                required: [text]
          custom_tools:
            - type: function
              name: workspace_info
              description: Returns workspace metadata
              parameters:
                type: object
                properties: {}
```

- `base_tools` replaces the built-in `shell`, `apply_patch`, `view_image`
  schema. Use this when `tool_schema_mode` is `codex_default` or
  `merge_custom`.
- `custom_tools` are automatically available when a request selects
  `custom_only` or when merging.

Environment overrides:

| Variable                           | Description                |
|------------------------------------|----------------------------|
| `OPENAI_OAUTH_TOOL_SCHEMA_BASE`    | JSON array of base tools   |
| `OPENAI_OAUTH_TOOL_SCHEMA_CUSTOM`  | JSON array of custom tools |

Each tool entry must include a `name` field; invalid definitions are skipped
with a warning.

## Tool Schema Mode Selection

### When to Use Each Mode

**codex_default** (recommended for most cases)
- Uses the built-in Codex tool schema: `shell`, `apply_patch`, `view_image`
- Best for general-purpose coding assistance
- Ensures compatibility with Codex CLI expectations

**merge_custom** (for extending defaults)
- Merges your custom tools with the defaults
- Use when you need additional tools beyond the standard set
- Tool names must be unique - collisions log warnings and keep the default
- Example: adding workspace_info tool while keeping shell/apply_patch

**custom_only** (advanced use only)
- Completely replaces default tools with your custom set
- Use when you need full control over the tool interface
- Risk: Codex may expect standard tools and behave unexpectedly
- Ensure your custom tools cover expected Codex functionality

### Tool Schema Collision Handling

In `merge_custom` mode, if a custom tool has the same name as a default tool but different parameters:
- A warning is logged with the parameter differences
- The default tool definition is kept
- The custom definition is ignored

This prevents silent breakage when tools have incompatible signatures.

## Agent Override Precedence

Agent-specific capability overrides (configured via `agent_capabilities`) only apply when:
1. The capability value in the request matches the resolver's default
2. No explicit override was provided in `extra_body` or request attributes

Example:
```yaml
codex:
  agent_capabilities:
    cline:
      tool_text_format: codex_xml  # Only applies if request doesn't set tool_text_format
```

If a request explicitly sets `tool_text_format: none`, the agent override will NOT be applied.

## Streaming Behavior and Token Refresh

### Token Refresh During Streaming

**Current Limitation**: Token refresh on 401 errors only works for non-streaming requests.

For streaming requests:
- If the token expires mid-stream, the stream will fail with a 401 error
- No automatic retry/refresh is performed
- Workaround: Ensure tokens are fresh before starting long-running streams
- Future enhancement: Streaming wrapper with retry capability

### Token Lifecycle

The connector uses **reactive** token refresh:
- Waits for 401 Unauthorized response
- Refreshes the access token using the refresh token
- Retries the request once with the new token

Proactive refresh (before expiration) is not currently implemented but recommended for production:
- Parse JWT `exp` field or track OAuth `expires_in`
- Refresh tokens 5 minutes before expiry
- Reduces user-visible authentication errors

## Multi-Process Safety

### Shared auth.json Considerations

If running multiple proxy instances with a shared `auth.json` file:

**Safe Operations**:
- Reading credentials (uses file watching for automatic reload)
- Concurrent requests (each process manages its own connection pool)

**Coordination Required**:
- Token refresh writes are atomic (temp file + rename)
- However, multiple processes refreshing simultaneously will race
- Last writer wins - usually fine, but may waste refresh API calls

**Best Practices**:
1. Use separate `auth.json` files per process when possible
2. If sharing is required, consider external coordination (e.g., file locks)
3. Monitor for excessive token refresh API calls
4. Ensure the auth.json directory is writable by all processes

### File Watching Reliability

The connector uses `watchdog` to detect auth.json changes:
- Works reliably on local filesystems
- May miss events on network mounts or during high I/O load
- Fallback: credentials are revalidated every 30 seconds
- Manual reload: Restart the proxy if file watching fails

## Renderer System Limitations

### Tool Text Rendering Modes

The tool text renderer system has **limited integration**:

**Fully Supported**:
- `tool_text_format: codex_xml` - Legacy textual tool call format for Cline/Kilo agents
- Parses textual tool invocations/results and converts to structured format

**Not Fully Integrated**:
- `tool_text_format: markdown` - Renderer exists but not used in canonical translation path
- `tool_text_format: summary` - Same limitation
- `tool_text_format: none` - Default, no text rendering (structured tool calls only)

**Recommendation**: Use `tool_text_format: none` (default) unless you specifically need Cline/Kilo compatibility.

### Custom Renderer Implementation

If you need a custom renderer:
1. Create a module with a `render_tool_call(tool_call)` function
2. Configure via `renderer.modules` in codex config
3. Note: Custom renderers only work in `codex_xml` translation mode

## Configuration Validation

The connector performs validation on:
- Tool schemas (requires `name` field, warns on invalid entries)
- Tool name collisions (logs warnings in merge_custom mode)
- Capability values (no schema enforcement, logs warnings)
- Renderer modules (logs warnings on load failures)

**Recommendation**: Use explicit configuration and monitor logs for validation warnings.

## Troubleshooting

### Common Issues

**401 Errors Despite Valid Token**
- Check for race condition: Multiple processes refreshing simultaneously
- Verify file watcher is working (check logs for reload messages)
- Ensure auth.json permissions are correct

**Streaming Failures Mid-Request**
- Token likely expired during stream
- Workaround: Use non-streaming requests for long operations
- Or refresh token before starting stream

**Tool Schema Not Applied**
- Verify tool_schema_mode is set correctly
- Check logs for collision warnings
- Ensure custom tools have valid `name` fields

**Agent Overrides Not Working**
- Verify agent name matches configuration (case-insensitive)
- Check if request explicitly overrides the capability
- Review logs for capability resolution details

## Environment Variables Summary

| Variable                                  | Purpose                                    |
|-------------------------------------------|--------------------------------------------|
| `OPENAI_OAUTH_DEFAULT_CAPABILITIES`       | JSON default capability overrides          |
| `OPENAI_OAUTH_AGENT_CAPABILITIES`         | JSON agent → capability map                |
| `OPENAI_OAUTH_RENDERER_DEFAULT`           | Default renderer key                       |
| `OPENAI_OAUTH_RENDERER_FALLBACK`          | Fallback renderer key                      |
| `OPENAI_OAUTH_RENDERER_ALIASES`           | JSON alias mapping                         |
| `OPENAI_OAUTH_RENDERER_MODULES`           | JSON name → `module.Class` mapping         |
| `OPENAI_OAUTH_PROMPT_TEMPLATE`            | Replacement system prompt                  |
| `OPENAI_OAUTH_PROMPT_PREPEND`             | JSON/List of prepend sections              |
| `OPENAI_OAUTH_PROMPT_APPEND`              | JSON/List of append sections               |
| `OPENAI_OAUTH_PROMPT_DEDUPLICATE`         | Toggle deduplication                       |
| `OPENAI_OAUTH_PROMPT_FALLBACK_DEFAULT`    | Toggle fallback when custom prompt empty   |
| `OPENAI_OAUTH_TOOL_SCHEMA_BASE`           | JSON base schema override                  |
| `OPENAI_OAUTH_TOOL_SCHEMA_CUSTOM`         | JSON reusable custom schema entries        |

## Observability

- Capability resolution logs emit the final merged profile (set log level to
  `DEBUG`).
- Renderer configuration failures log warnings but fall back to the safe `none`
  renderer.
- Prompt and tool schema helpers validate definitions and skip malformed entries
  with clear warnings.

With these knobs you can tailor the `openai-oauth` backend to match each
client's expectations while preserving the canonical tool call metadata the
proxy relies on.
