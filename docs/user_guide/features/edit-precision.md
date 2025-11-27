# Edit Precision Tuning

Automated model parameter tuning that improves accuracy when file edits fail.

## Overview

The Edit Precision Tuning feature automatically detects when a model struggles with tasks like precise file edits and adjusts its parameters to improve accuracy on subsequent attempts. When the proxy detects that a file edit operation has failed (typically through error patterns or tool call failures), it automatically reduces the model's temperature and adjusts other parameters to make the model more deterministic and focused on the next attempt.

This feature is particularly valuable when working with models that may be too creative or non-deterministic for precise code editing tasks. By automatically tuning parameters after failures, the proxy helps models recover from mistakes without manual intervention.

## Key Features

- **Automatic Detection**: Monitors tool calls and responses for edit failure patterns
- **Dynamic Parameter Adjustment**: Reduces temperature and adjusts top_p values after failures
- **Model-Specific Tuning**: Supports per-model-family temperature overrides for optimal results
- **Agent Filtering**: Exclude specific agents from automatic tuning using regex patterns
- **Configurable Thresholds**: Customize temperature and top_p values to match your needs
- **Transparent Operation**: Works in the background without disrupting the conversation flow

## Configuration

Edit precision tuning can be configured through CLI flags, environment variables, or YAML configuration files. Configuration precedence: CLI > Environment Variables > YAML.

### CLI Flags

```bash
# Enable or disable edit-precision tuning
--enable-edit-precision
--disable-edit-precision

# Set target temperature for edit failures (default: 0.1)
--edit-precision-temperature FLOAT

# Set minimum top_p value for edit failures (default: 0.3)
--edit-precision-min-top-p FLOAT

# Enable top_p override for edit failures
--edit-precision-override-top-p

# Exclude specific agents from edit-precision tuning
--edit-precision-exclude-agents REGEX
```

### Environment Variables

```bash
# Enable or disable the feature (default: true)
export EDIT_PRECISION_ENABLED=true

# Set target temperature (default: 0.1)
export EDIT_PRECISION_TEMPERATURE=0.1

# Set minimum top_p value (default: 0.3)
export EDIT_PRECISION_MIN_TOP_P=0.3

# Enable top_p override (default: false)
export EDIT_PRECISION_OVERRIDE_TOP_P=true

# Exclude agents matching regex pattern
export EDIT_PRECISION_EXCLUDE_AGENTS_REGEX="test.*"
```

### YAML Configuration

```yaml
# config.yaml
edit_precision:
  enabled: true
  temperature: 0.1
  min_top_p: 0.3
  override_top_p: false
  exclude_agents_regex: null
```

### Model-Specific Temperature Overrides

Different model families perform best with different temperature values for precise edits. Configure per-model overrides in `config/edit_precision_model_temperatures.yaml`:

```yaml
# config/edit_precision_model_temperatures.yaml
default_temperature: 0.1

model_patterns:
  - keyword: "gpt"        # Matches any model with "gpt" in name (case-insensitive)
    temperature: 0.2
  - keyword: "gemini"
    temperature: 0.2
  - keyword: "deepseek"
    temperature: 0.0      # Fully deterministic for DeepSeek models
  - keyword: "glm"
    temperature: 0.6
  - keyword: "grok"
    temperature: 0.1
  - keyword: "sonnet"
    temperature: 0.2
  - keyword: "opus"
    temperature: 0.2
```

When edit-precision mode activates:

1. Model name is checked against patterns (case-insensitive substring match)
2. First matching pattern's temperature is used
3. If no match, `default_temperature` is used
4. These values override the CLI/env/config `edit_precision.temperature` setting

This allows fine-tuned control - for example, DeepSeek models work best with temperature=0.0 for precise edits, while GPT models prefer 0.2.

## Usage Examples

### Basic Usage

```bash
# Enable edit-precision tuning with default settings
python -m src.core.cli --enable-edit-precision

# Disable edit-precision tuning entirely
python -m src.core.cli --disable-edit-precision
```

### Custom Temperature Settings

```bash
# Use a very low temperature for maximum determinism
python -m src.core.cli --edit-precision-temperature 0.05

# Use a moderate temperature for balance between creativity and precision
python -m src.core.cli --edit-precision-temperature 0.15
```

### Advanced Configuration

```bash
# Custom top_p value and enable override
python -m src.core.cli --edit-precision-min-top-p 0.2 --edit-precision-override-top-p

# Exclude specific agents from edit-precision (e.g., exclude "test" agents)
python -m src.core.cli --edit-precision-exclude-agents "test.*"

# Combine multiple edit-precision settings
python -m src.core.cli \
  --enable-edit-precision \
  --edit-precision-temperature 0.08 \
  --edit-precision-min-top-p 0.25 \
  --edit-precision-override-top-p
```

### Environment Variable Configuration

```bash
# Configure via environment variables
export EDIT_PRECISION_ENABLED=true
export EDIT_PRECISION_TEMPERATURE=0.05
export EDIT_PRECISION_MIN_TOP_P=0.2
export EDIT_PRECISION_OVERRIDE_TOP_P=true

# Start the proxy
python -m src.core.cli
```

## Use Cases

### Automated Code Refactoring

When an AI assistant is performing large-scale code refactoring, edit precision tuning helps ensure that subsequent file modifications are more accurate after initial failures:

```bash
python -m src.core.cli \
  --enable-edit-precision \
  --edit-precision-temperature 0.05
```

### Multi-File Code Generation

During complex multi-file code generation tasks, the feature helps maintain consistency and accuracy across multiple edit operations:

```bash
python -m src.core.cli \
  --enable-edit-precision \
  --edit-precision-temperature 0.1 \
  --edit-precision-override-top-p
```

### Model-Specific Optimization

Different models require different precision settings. Use model-specific overrides for optimal results:

```yaml
# For DeepSeek models - fully deterministic
model_patterns:
  - keyword: "deepseek"
    temperature: 0.0

# For GPT models - slightly higher for better results
  - keyword: "gpt"
    temperature: 0.2
```

### Testing and Development Workflows

Exclude test agents from automatic tuning to maintain consistent behavior during testing:

```bash
python -m src.core.cli \
  --enable-edit-precision \
  --edit-precision-exclude-agents "test.*|dev.*"
```

### Cost-Sensitive Applications

Lower temperature values reduce token usage by making responses more focused and deterministic:

```bash
python -m src.core.cli \
  --enable-edit-precision \
  --edit-precision-temperature 0.0 \
  --edit-precision-min-top-p 0.1
```

## How It Works

1. **Failure Detection**: The proxy monitors tool calls and responses for patterns indicating edit failures
2. **Parameter Adjustment**: When a failure is detected, the proxy automatically adjusts model parameters:
   - Reduces temperature to the configured value (default: 0.1)
   - Optionally adjusts top_p to the minimum value (if override enabled)
3. **Model-Specific Tuning**: Checks model name against configured patterns and applies model-specific temperature
4. **Retry**: The adjusted parameters are used for the next request, improving accuracy
5. **Reset**: Parameters return to normal after successful operations

## Troubleshooting

### Edit Precision Not Activating

**Problem**: Edit failures don't trigger parameter adjustments

**Solutions**:
- Verify the feature is enabled: `--enable-edit-precision` or `EDIT_PRECISION_ENABLED=true`
- Check that your agent is not excluded by the `exclude_agents_regex` pattern
- Review logs for edit failure detection messages
- Ensure the failure patterns match your use case (check `config/edit_precision_patterns.yaml`)

### Temperature Not Changing

**Problem**: Model temperature doesn't seem to change after failures

**Solutions**:
- Verify model-specific overrides in `config/edit_precision_model_temperatures.yaml`
- Check that the model name matches a configured pattern
- Ensure the backend supports temperature parameter (some backends ignore it)
- Review debug logs for parameter adjustment messages

### Too Aggressive Tuning

**Problem**: Model becomes too deterministic and loses useful creativity

**Solutions**:
- Increase the temperature value: `--edit-precision-temperature 0.2`
- Disable top_p override: remove `--edit-precision-override-top-p` flag
- Adjust model-specific temperatures in the configuration file
- Consider excluding certain agents that need more creativity

### Conflicts with Other Features

**Problem**: Edit precision conflicts with other parameter-tuning features

**Solutions**:
- Check configuration precedence: CLI > Environment > YAML
- Review logs for parameter override messages
- Ensure planning-phase overrides don't conflict with edit precision
- Consider disabling one feature if they interfere with each other

## Related Features

- [Planning Phase Overrides](planning-phase.md) - Override model parameters during the planning phase
- [Hybrid Backend](hybrid-backend.md) - Use different models for different phases
- [Dangerous Command Protection](dangerous-command-protection.md) - Prevent destructive operations
- [Tool Access Control](tool-access-control.md) - Control which tools models can access
