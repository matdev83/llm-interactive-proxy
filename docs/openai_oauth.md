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
client’s expectations while preserving the canonical tool call metadata the
proxy relies on.
