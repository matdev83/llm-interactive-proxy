# Model Name Rewrites

The Model Name Rewrites feature provides a powerful, rule-based system for dynamically transforming model names before they are processed by the proxy.

## Overview

This feature enables seamless model routing, backend abstraction, and fallback strategies without requiring changes to client applications. It uses regex-based pattern matching with configurable rules and precedence to transform model names on the fly.

## Key Benefits

- **Backend Abstraction**: Hide specific backend details from client applications
- **Seamless Migration**: Switch underlying models without updating client code
- **Cost Optimization**: Route expensive models to cheaper alternatives
- **Fallback Strategies**: Create catch-all rules for unrecognized models
- **Provider Consolidation**: Route all requests of a certain type through a preferred provider

## Configuration Sources

Model aliases can be configured through three sources with the following precedence order:

### 1. CLI Parameters (Highest Precedence)

```bash
# Single alias
--model-alias "^gpt-(.*)=openrouter:openai/gpt-\1"

# Multiple aliases
--model-alias "^gpt-(.*)=openrouter:openai/gpt-\1" \
--model-alias "^claude-(.*)=anthropic:claude-\1" \
--model-alias "^(.*)=gemini-oauth-plan:gemini-1.5-pro"
```

### 2. Environment Variables (Medium Precedence)

```bash
export MODEL_ALIASES='[
  {"pattern": "^gpt-(.*)", "replacement": "openrouter:openai/gpt-\\1"},
  {"pattern": "^claude-(.*)", "replacement": "anthropic:claude-\\1"},
  {"pattern": "^(.*)$", "replacement": "gemini-oauth-plan:gemini-1.5-pro"}
]'
```

### 3. Config File (Lowest Precedence)

```yaml
model_aliases:
  # Static replacement for specific model
  - pattern: "^claude-3-sonnet-20240229$"
    replacement: "gemini-oauth-plan:gemini-1.5-flash"
  
  # Dynamic replacement with capture groups
  - pattern: "^gpt-(.*)"
    replacement: "openrouter:openai/gpt-\\1"
  
  # Catch-all fallback for any other model
  - pattern: "^(.*)$"
    replacement: "gemini-oauth-plan:gemini-1.5-pro"
```

## Rule Processing

- **First Match Wins**: Rules are processed in order, and the first matching pattern is applied
- **Regex Support**: Patterns use Python regular expressions with full capture group support
- **Validation**: Invalid regex patterns are caught early with helpful error messages
- **Precedence**: CLI parameters override environment variables, which override config file settings

## Usage Examples

### Route All GPT Models to OpenRouter

```yaml
model_aliases:
  - pattern: "^gpt-(.*)"
    replacement: "openrouter:openai/gpt-\\1"
```

### Replace Expensive Models with Cheaper Alternatives

```yaml
model_aliases:
  - pattern: "^gpt-4o$"
    replacement: "gemini-oauth-plan:gemini-1.5-pro"
  - pattern: "^claude-3-opus.*"
    replacement: "anthropic:claude-3-sonnet-20240229"
```

### Create Environment-Specific Routing

```bash
# Development environment - use free models
export MODEL_ALIASES='[
  {"pattern": "^.*$", "replacement": "gemini-oauth-plan:gemini-1.5-flash"}
]'

# Production environment - use premium models
export MODEL_ALIASES='[
  {"pattern": "^gpt-(.*)", "replacement": "openai:gpt-\\1"},
  {"pattern": "^claude-(.*)", "replacement": "anthropic:claude-\\1"}
]'
```

### Override for Specific Applications

```bash
# Force a specific application to use your preferred model
./my-app | llm-proxy --model-alias ".*=my-backend:my-preferred-model"
```

## Integration with Other Features

Model aliases work seamlessly with other proxy features:

- **Static Route**: `--static-route` takes precedence over model aliases
- **Planning Phase**: Operates on the rewritten model names
- **Failover**: Failover routes use the final rewritten model names
- **In-Chat Commands**: `!/model(...)` commands respect alias rules

## Error Handling

The proxy provides robust error handling for model aliases:

- **Invalid Regex**: Patterns are validated at startup/parse time
- **Malformed JSON**: Environment variable errors are logged as warnings
- **Schema Validation**: Config file validation ensures proper structure
- **Graceful Fallback**: Invalid rules are skipped, processing continues

## Use Cases

### Backend Migration

Migrate from one provider to another without updating client code:

```yaml
model_aliases:
  - pattern: "^openai:(.*)"
    replacement: "openrouter:openai/\\1"
```

### Cost Control

Route expensive models to cheaper alternatives automatically:

```yaml
model_aliases:
  - pattern: "^gpt-4-turbo$"
    replacement: "gpt-4o-mini"
  - pattern: "^claude-3-opus$"
    replacement: "claude-3-sonnet"
```

### Testing and Development

Use different models in different environments:

```bash
# Development
export MODEL_ALIASES='[{"pattern": ".*", "replacement": "gemini-oauth-free:gemini-1.5-flash"}]'

# Production
export MODEL_ALIASES='[{"pattern": ".*", "replacement": "openai:gpt-4o"}]'
```

## Best Practices

1. **Test Patterns**: Validate regex patterns before deploying to production
2. **Order Matters**: Place more specific patterns before general catch-all patterns
3. **Document Rules**: Add comments explaining the purpose of each alias
4. **Monitor Usage**: Track which aliases are being used most frequently
5. **Version Control**: Store alias configurations in version control

## Related Features

- [URI Model Parameters](uri-model-parameters.md) - Specify model parameters in model strings
- [Hybrid Backend](hybrid-backend.md) - Combine reasoning and execution models
- [Planning Phase Overrides](planning-phase.md) - Use strong models for planning
