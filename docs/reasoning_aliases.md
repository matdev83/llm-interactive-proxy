# Reasoning Aliases Documentation

## Overview

Reasoning aliases allow you to define and switch between predefined sets of model reasoning settings using simple interactive commands. This feature provides greater control over model behavior during a session without needing to restart the proxy or modify the main configuration.

## Configuration

### Setting up reasoning_aliases.yaml

1. Copy the example configuration file:
   ```bash
   cp config/reasoning_aliases.yaml.example config/reasoning_aliases.yaml
   ```

2. Edit `config/reasoning_aliases.yaml` to define your reasoning modes:

```yaml
reasoning_alias_settings:
  - model: "gemini-2.5-pro"
    modes:
      high:
        max_reasoning_tokens: 32000
        reasoning_effort: "high"
        user_prompt_prefix: "Think even harder about the following problem. "
        user_prompt_suffix: ""
        temperature: 1.0
        top_p: 1.0
      medium:
        max_reasoning_tokens: 16000
        reasoning_effort: "medium"
        user_prompt_prefix: "Think hard about the following problem. "
        user_prompt_suffix: ""
        temperature: 0.7
        top_p: 0.9
      low:
        max_reasoning_tokens: 4000
        reasoning_effort: "low"
        user_prompt_prefix: "Think about the following problem. "
        user_prompt_suffix: ""
        temperature: 0.3
        top_p: 0.5
      none:
        max_reasoning_tokens: 100
        reasoning_effort: ""
        user_prompt_prefix: ""
        user_prompt_suffix: ""
        temperature: 0.0
        top_p: 0.1
  - model: "claude-sonnet-4*"
    modes:
      high:
        max_reasoning_tokens: 20000
        reasoning_effort: "high"
        user_prompt_prefix: "Think even harder about the following problem. "
        user_prompt_suffix: ""
        temperature: 1.0
        top_p: 1.0
      medium:
        max_reasoning_tokens: 10000
        reasoning_effort: "medium"
        user_prompt_prefix: "Think hard about the following problem. "
        user_prompt_suffix: ""
        temperature: 0.7
        top_p: 0.9
      low:
        max_reasoning_tokens: 2000
        reasoning_effort: "low"
        user_prompt_prefix: "Think about the following problem. "
        user_prompt_suffix: ""
        temperature: 0.3
        top_p: 0.5
      none:
        max_reasoning_tokens: 0
        reasoning_effort: ""
        user_prompt_prefix: ""
        user_prompt_suffix: ""
        temperature: 0.0
        top_p: 0.1
```

### Configuration Schema

The configuration supports the following fields for each reasoning mode:

- `max_reasoning_tokens`: Maximum reasoning tokens for this mode
- `reasoning_effort`: Reasoning effort level (string)
- `user_prompt_prefix`: Text to prepend to user prompts
- `user_prompt_suffix`: Text to append to user prompts
- `temperature`: Temperature setting for this mode (0.0 - 2.0)
- `top_p`: Top-p (nucleus sampling) setting for this mode (0.0 - 1.0)

## Interactive Commands

The following interactive commands are available:

- `!/max`: Activates the "high" reasoning mode
- `!/medium`: Activates the "medium" reasoning mode
- `!/low`: Activates the "low" reasoning mode
- `!/no-think`: Activates the "none" reasoning mode
- `!/mode <mode_name>`: Sets a specific reasoning mode

Aliases for `!/no-think`:
- `!/no-thinking`
- `!/no-reasoning`
- `!/disable-thinking`
- `!/disable-reasoning`

## Usage Examples

### Basic Usage

1. Start a conversation with any model
2. Use reasoning commands to adjust model behavior:

```
User: !/max
Proxy: Reasoning mode set to max.

User: Explain quantum computing
Proxy: [Response with high reasoning effort and detailed explanation]

User: !/low
Proxy: Reasoning mode set to low.

User: What's 2+2?
Proxy: [Brief response with low reasoning effort]
```

### Prompt Modification

The `user_prompt_prefix` and `user_prompt_suffix` settings automatically modify your prompts:

```yaml
modes:
  high:
    user_prompt_prefix: "Think carefully and provide a detailed explanation: "
    user_prompt_suffix: " Show your work step by step."
```

When this mode is active, a prompt like "Explain photosynthesis" becomes:
"Think carefully and provide a detailed explanation: Explain photosynthesis Show your work step by step."

## Model Support

Reasoning aliases work with any model that supports reasoning parameters. The configuration uses wildcard matching, so you can define settings for model patterns like `claude-sonnet-4*` to apply to multiple similar models.

## Error Handling

If you attempt to use a reasoning command for a model that has no settings defined in `reasoning_aliases.yaml`, the proxy will return a clear error message:
```
Command ignored. You have not configured reasoning settings for this model in config file reasoning_aliases.yaml
```

## Best Practices

1. **Start with conservative settings**: Begin with moderate reasoning settings and adjust based on your needs
2. **Use wildcards wisely**: Leverage wildcard patterns to apply settings to multiple similar models
3. **Test different modes**: Experiment with different reasoning modes to find the right balance for your use case
4. **Document your configurations**: Keep notes on which settings work best for different types of tasks
5. **Use prompt prefixes/suffixes**: Leverage prompt modification to guide model behavior without changing your natural interaction style

## Troubleshooting

### Configuration Issues

If reasoning commands aren't working:

1. Check that `config/reasoning_aliases.yaml` exists and is properly formatted
2. Verify that your model is listed in the configuration
3. Ensure the YAML syntax is correct (use a YAML validator if needed)

### Model Compatibility

Not all models support all reasoning parameters. Unsupported parameters are safely ignored. Check your model's documentation for supported parameters.

### Performance Considerations

Higher reasoning settings (like `!/max`) may result in:
- Longer response times
- Higher token usage
- Increased API costs
- More detailed but potentially verbose responses

Use lower settings (`!/low`, `!/no-think`) for quick, simple queries where detailed reasoning isn't needed.