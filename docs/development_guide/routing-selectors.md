# Technical Reference: Routing Selectors

This document provides detailed technical specifications for the proxy's routing selector syntax.

## Selector Formats

### Basic Selectors

- `backend:model` - Selects an explicit backend family (e.g., `openai:gpt-4o`)
- `backend-instance:model` - Targets a concrete backend instance (e.g., `openai.1:gpt-4o`)
- `model` - Model-only selector (uses default backend)
- `vendor/model` - Vendor-prefixed model selector
- `vendor/model:variant` - Model variant selector (remains model-only)

### URI-style Parameters

Selectors can include URI-style parameters that are parsed and propagated through routing metadata:

```
model?temperature=0.5&max_tokens=1000
openai:gpt-4o?temperature=0.7
```

### Composite Selectors

#### Failover Routing (Ordered)

Uses `|` to specify fallback backends when pre-output failures occur:

```
selectorA|selectorB|selectorC
```

Examples:
- `openai:gpt-4o|anthropic:claude-3-5-sonnet|openrouter:openai/gpt-4o`
- `gemini:gemini-1.5-pro|openai:gpt-4o`

The proxy advances left-to-right through the chain when failures occur, sharing one bounded attempt budget with existing retry/failover safety controls.

#### Weighted Routing

Uses `^` with optional `[weight=N]` prefixes for weighted distribution:

```
[weight=3]openai:gpt-4^[weight=1]anthropic:claude-3-5-sonnet
```

This distributes traffic 75% to OpenAI and 25% to Anthropic.

### Selector Rules

1. **No mixing operators** - Composite selectors must not mix `|` and `^` in the same selector string. These are rejected during validation.

2. **Quoting and escaping** - When providing selectors via CLI or environment variables, quote/escape the full selector string:
   - Windows: `|` is a PowerShell pipeline operator, `^` is a cmd.exe escape character
   - Bash: Use quotes to prevent shell interpretation

3. **Strict format for explicit routing** - `--static-route`, replacement targets, and explicit routing require strict `backend:model` format.

## Examples

### CLI Usage

```bash
# Basic backend selection
python -m src.core.cli --default-backend openai:gpt-4o

# With parameters
python -m src.core.cli --default-backend "openai:gpt-4o?temperature=0.5"

# Failover chain
python -m src.core.cli --default-backend "openai:gpt-4o|anthropic:claude-3-5-sonnet"

# Weighted routing
python -m src.core.cli --default-backend "[weight=3]openai:gpt-4^[weight=1]anthropic:claude-3-5-sonnet"
```

### Environment Variables

```bash
# Default backend with failover
export LLM_BACKEND="openai:gpt-4o|anthropic:claude-3-5-sonnet"

# Static route with parameters
export STATIC_ROUTE="openai:gpt-4o?temperature=0.1"
```

### Configuration File

```yaml
backends:
  default_backend: "openai:gpt-4o"
  
# Failover route for specific model
failover_routes:
  "gpt-4o":
    policy: "round-robin"
    elements: ["openai:gpt-4o", "anthropic:claude-3-5-sonnet"]
```

## Legacy Compatibility

Random model replacement has been deprecated and now routes through a compatibility bridge:
- Emits deprecation metadata
- Removal timeline: N+1 (removed in release after deprecation)
- Rejects unsafe mappings with explicit migration errors

Migrate to composite selectors for similar functionality.

## See Also

- [Backends Overview](../user_guide/backends/overview.md) - Provider setup and configuration
- [Routing Configuration](../user_guide/configuration.md) - Full configuration reference
- [CLI Parameters](../user_guide/cli-parameters.md) - Command-line options
