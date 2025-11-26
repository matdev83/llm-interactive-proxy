# Client Identity Override Guide

## What Is This?

Some LLM providers (like OpenRouter) check which application is making requests and may filter or limit access based on the client name. This proxy lets you change how your application identifies itself to these providers, which can be useful for debugging and testing.

## Quick Start

### Using CLI Arguments

```bash
python -m src.core.cli --identity-user-agent "MyApp/1.0.0"
```

### Using Config File

Create or edit your configuration file (e.g., `config/my_config.yaml`):

```yaml
identity:
  user_agent:
    mode: override
    override_value: "MyApp/1.0.0"
```

Start the proxy:

```bash
python -m src.core.cli --config config/my_config.yaml
```

## Configuration Options

### What You Can Override

- **User-Agent**: The client application name and version (e.g., "Kilo-Code/4.122.1")
- **HTTP-Referer**: The website URL of your application (e.g., "<https://kilocode.com>")
- **X-Title**: The display name of your application (e.g., "Kilo Code")

### Modes

Each identity field supports three modes:

1. **passthrough** (default): Forwards the original client's values
2. **override**: Uses your custom values
3. **default**: Uses the proxy's built-in defaults

## CLI Parameters

For quick one-off overrides, use command-line arguments:

```bash
# Override just the user-agent
python -m src.core.cli --identity-user-agent "MyApp/2.0"

# Override all three headers
python -m src.core.cli \
  --identity-user-agent "Kilo-Code/4.122.1" \
  --identity-url "https://kilocode.com" \
  --identity-title "Kilo Code"

# Combine with other parameters
python -m src.core.cli \
  --default-backend openai \
  --identity-user-agent "TestClient/1.0"
```

### Available CLI Arguments

- `--identity-user-agent VALUE`: Override User-Agent header (client name/version)
- `--identity-url URL`: Override HTTP-Referer header (application URL)
- `--identity-title TITLE`: Override X-Title header (application display name)

> **Note**: CLI parameters take precedence over config file settings.

## Config File Examples

### Example 1: Impersonate KiloCode Client

```yaml
identity:
  user_agent:
    mode: override
    override_value: "Kilo-Code/4.122.1"
  url:
    mode: override
    override_value: "https://kilocode.com"
  title:
    mode: override
    override_value: "Kilo Code"
```

### Example 2: Impersonate Factory Droid

```yaml
identity:
  user_agent:
    mode: override
    override_value: "factory-cli/0.27.1"
  url:
    mode: override
    override_value: "https://factory.ai"
  title:
    mode: override
    override_value: "Factory Droid"
```

### Example 3: Custom Client Identity

```yaml
identity:
  user_agent:
    mode: override
    override_value: "MyCustomAgent/2.0"
  url:
    mode: override
    override_value: "https://example.com/myagent"
  title:
    mode: override
    override_value: "My Custom Agent"
```

### Example 4: Mix Override and Passthrough

```yaml
identity:
  user_agent:
    mode: override
    override_value: "TestClient/1.0"
  url:
    mode: passthrough  # Keep client's original URL
  title:
    mode: default      # Use proxy's default title
```

## Common Use Cases

### Debugging with Specific Providers

OpenRouter and similar providers may have different rate limits or features for different clients. Use identity override to test how your application behaves with different client identities:

```yaml
identity:
  user_agent:
    mode: override
    override_value: "curl/7.68.0"  # Test as if using curl
```

### Testing Backend Behavior

Test how different LLM backends respond to different client types without actually switching clients:

```yaml
# Test configuration 1
identity:
  user_agent:
    mode: override
    override_value: "OpenAI-SDK/1.0"

# Test configuration 2  
identity:
  user_agent:
    mode: override
    override_value: "Anthropic-SDK/0.5"
```

## Troubleshooting

### Changes Not Taking Effect

1. Make sure you're using the `--config` flag or CLI arguments
2. Restart the proxy after making configuration changes
3. Check the proxy logs for any configuration errors

### How to See Which Headers Are Being Sent

Enable wire capture to see exactly what headers are sent to backends:

```bash
# Check logs/wire_capture.log after making requests
python -m src.core.cli --config config/my_config.yaml
# Make a request
# Then check: logs/wire_capture.log
```

Look for entries with `"direction":"outbound_request"` to see headers sent to backends.

### Provider Still Blocking Requests

Some providers may use additional methods beyond headers to identify clients. If overriding headers doesn't solve your problem:

1. Check the provider's documentation for their client identification methods
2. Look at `logs/wire_capture.log` to see what the provider is receiving
3. Try different client identities to see what the provider accepts

## Tips

- **Start Simple**: Begin with just overriding the User-Agent, as that's the most commonly checked header
- **Match Real Clients**: When testing, use actual client names from real applications (like "Kilo-Code/4.122.1") for more realistic testing
- **Keep Records**: Save different configuration files for different test scenarios (e.g., `config/test_as_kilocode.yaml`, `config/test_as_factory.yaml`)
- **Check Logs**: Always review `logs/wire_capture.log` to confirm your overrides are working as expected

## Need More Help?

See the main `README.md` for general proxy configuration and setup instructions.
