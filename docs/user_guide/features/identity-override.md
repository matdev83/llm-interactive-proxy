# Client Identity Override

Override how the proxy identifies itself to LLM providers through configurable HTTP headers.

## Overview

Some LLM providers check which application is making requests and may filter or limit access based on client identification. The Client Identity Override feature lets you control how the proxy identifies itself to LLM providers through configuration, allowing you to work with providers that filter by client type or test how providers respond to different client identities.

## Key Features

- **User-Agent Override**: Control client application name and version
- **HTTP-Referer Override**: Set application website URL
- **X-Title Override**: Control application display name
- **Multiple Modes**: Passthrough, override, or use proxy defaults
- **Per-Backend Configuration**: Different identities for different providers
- **Easy Testing**: Quickly test provider behavior with different identities

## Configuration

Identity override is configured through the `identity` section in your config file.

### Configuration Modes

- `passthrough` (default): Forward original client values
- `override`: Use your custom values
- `default`: Use proxy's built-in defaults

### Basic Configuration

```yaml
# config/my_config.yaml
identity:
  user_agent:
    mode: override
    override_value: "MyApp/1.0.0"
  referer:
    mode: override
    override_value: "https://myapp.example.com"
  x_title:
    mode: override
    override_value: "My Application"
```

### CLI Arguments

For quick one-off overrides, use command-line arguments:

```bash
# Override just the user-agent
python -m src.core.cli --identity-user-agent "MyApp/1.0.0"

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

**Available CLI Arguments:**

- `--identity-user-agent VALUE`: Override User-Agent header (client name/version)
- `--identity-url URL`: Override HTTP-Referer header (application URL)
- `--identity-title TITLE`: Override X-Title header (application display name)

> **Note**: CLI parameters take precedence over config file settings.

## Usage Examples

### Override User-Agent Only

```yaml
identity:
  user_agent:
    mode: override
    override_value: "MyApp/1.0.0"
  referer:
    mode: passthrough  # Keep original
  x_title:
    mode: passthrough  # Keep original
```

### Use Proxy Defaults

```yaml
identity:
  user_agent:
    mode: default  # Use proxy's default User-Agent
  referer:
    mode: default  # Use proxy's default Referer
  x_title:
    mode: default  # Use proxy's default X-Title
```

### Impersonate KiloCode Client

```yaml
# config/identity_kilocode.example.yaml
identity:
  user_agent:
    mode: override
    override_value: "KiloCode/1.0.0"
  referer:
    mode: override
    override_value: "https://kilocode.example.com"
  x_title:
    mode: override
    override_value: "KiloCode"
```

### Impersonate Factory Droid Client

```yaml
# config/identity_factory_droid.example.yaml
identity:
  user_agent:
    mode: override
    override_value: "FactoryDroid/2.0.0"
  referer:
    mode: override
    override_value: "https://factorydroid.example.com"
  x_title:
    mode: override
    override_value: "Factory Droid"
```

## Use Cases

### Provider Compatibility

Work with providers that filter by client type (e.g., OpenRouter):

```bash
python -m src.core.cli \
  --default-backend openrouter \
  --identity-user-agent "ApprovedClient/1.0.0"
```

### Debugging Provider Behavior

Test how providers respond to different client identities:

```yaml
# Test with identity A
identity:
  user_agent:
    mode: override
    override_value: "ClientA/1.0.0"

# Then test with identity B
identity:
  user_agent:
    mode: override
    override_value: "ClientB/2.0.0"
```

### Testing Without Switching Applications

Simulate different clients without switching applications:

```bash
# Test as KiloCode
python -m src.core.cli --config config/identity_kilocode.example.yaml

# Test as Factory Droid
python -m src.core.cli --config config/identity_factory_droid.example.yaml
```

### Development and Testing

Use custom identities during development to distinguish test traffic:

```yaml
identity:
  user_agent:
    mode: override
    override_value: "MyApp-Dev/0.1.0"
  x_title:
    mode: override
    override_value: "MyApp Development"
```

## Example Configurations

The `config/` directory includes example files you can use as templates:

### KiloCode Identity

```bash
cp config/identity_kilocode.example.yaml config/my_kilocode_config.yaml
python -m src.core.cli --config config/my_kilocode_config.yaml
```

### Factory Droid Identity

```bash
cp config/identity_factory_droid.example.yaml config/my_droid_config.yaml
python -m src.core.cli --config config/my_droid_config.yaml
```

## Troubleshooting

**Changes not taking effect:**

1. Make sure you're using the `--config` flag or CLI arguments
2. Restart the proxy after making configuration changes
3. Check the proxy logs for any configuration errors

**Identity not being applied:**

- Verify the config file is being loaded (`--config` flag)
- Check that `mode` is set to `override` not `passthrough`
- Review proxy logs for identity configuration messages
- Ensure the `override_value` is specified

**How to see which headers are being sent:**

Enable wire capture to see exactly what headers are sent to backends:

```bash
# Start proxy with wire capture
python -m src.core.cli --config config/my_config.yaml --wire-capture-json

# Make a request, then check the capture file
# Look for entries with "direction":"proxy_to_backend" to see headers sent to backends
```

**Provider still rejecting requests:**

- Verify the identity values match what the provider expects
- Check provider documentation for required client identifiers
- Review provider logs for rejection reasons
- Try different identity combinations
- Some providers may use additional methods beyond headers to identify clients (API keys, IP addresses)

**Original client identity leaking through:**

- Set all identity fields to `override` mode
- Don't use `passthrough` mode if you want to hide original identity
- Check that no other headers are exposing client information

**Provider behavior unchanged:**

- Some providers may not check these headers
- Try different combinations of headers
- Check if provider uses other identification methods (API keys, IP addresses)
- Review provider documentation for client identification requirements

## Tips and Best Practices

- **Start Simple**: Begin with just overriding the User-Agent, as that's the most commonly checked header
- **Match Real Clients**: When testing, use actual client names from real applications (like "Kilo-Code/4.122.1") for more realistic testing
- **Keep Records**: Save different configuration files for different test scenarios (e.g., `config/test_as_kilocode.yaml`, `config/test_as_factory.yaml`)
- **Check Logs**: Always review wire capture logs to confirm your overrides are working as expected
- **CLI for Quick Tests**: Use CLI arguments for one-off tests, config files for persistent configurations

## Related Features

- [Model Name Rewrites](model-name-rewrites.md) - Transform model names for provider compatibility
- [Hybrid Backend](hybrid-backend.md) - Use different providers for different phases
- [Tool Access Control](tool-access-control.md) - Control tool access per provider
- [Wire Capture](../debugging/wire-capture.md) - Inspect headers and requests sent to backends
