# Resilience Scoping

Resilience scoping controls how the proxy shares (or isolates) cooldown and rate-limit
state across clients. This is especially important when the proxy is used both by
solo developers (personal OAuth tokens) and enterprise/shared deployments.

## Defaults (No Configuration Required)

By default, the proxy treats backends as:

- **Personal** when the backend type contains `oauth` or `codex`.
- **Shared** otherwise.

The built-in personal list includes:

- `antigravity-oauth`
- `gemini-oauth-free`
- `gemini-oauth-plan`
- `gemini-cli-cloud-project`
- `qwen-oauth`
- `openai-codex`

This means OAuth- and Codex-style backends are scoped per user/session without
any configuration changes.

## Configuration

Configure scoping rules in the main config under `resilience`. Use these
lists to explicitly mark backends as personal or shared.

## CLI Flags

Use CLI flags for one-off overrides (highest precedence):

- `--resilience-personal-backends BACKEND[,BACKEND...]`
- `--resilience-shared-backends BACKEND[,BACKEND...]`

You can pass a comma-separated list or repeat the flag.

## Environment Variables

Use environment variables to override config defaults:

- `RESILIENCE_PERSONAL_BACKEND_TYPES`
- `RESILIENCE_SHARED_BACKEND_TYPES`

Both accept comma-separated backend type lists.

## Override Mechanism

Use `resilience.personal_backend_types` and `resilience.shared_backend_types` to
override the defaults when needed.

```yaml
resilience:
  # Force personal scoping for selected backends (optional).
  personal_backend_types: ["openai-codex", "qwen-oauth"]
  # Force shared scoping for selected backends (optional).
  shared_backend_types: ["openai", "openrouter"]
```

### Precedence Rules

- If a backend appears in `shared_backend_types`, it is treated as shared.
- Otherwise, if a backend appears in `personal_backend_types`, it is personal.
- If neither list matches, defaults apply.

## When To Override

- **Enterprise/shared backend but name contains `oauth`**: add it to
  `shared_backend_types` to keep shared cooldown state.
- **Personal backend without `oauth`/`codex` in name**: add it to
  `personal_backend_types` to isolate state by session.

## Use Cases

- **Mixed deployments**: isolate personal OAuth backends while keeping shared
  enterprise backends on a single cooldown pool.
- **Custom backend names**: enforce scoping when backend naming doesn't match
  the default `oauth`/`codex` heuristic.

## Related Docs

- [Configuration Guide](../configuration.md)
- [CLI Parameters Reference](../cli-parameters.md)
- [Backend Overview](../backends/overview.md)
