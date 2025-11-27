# Key Hygiene

Automatic API key redaction in logs, wire captures, and error messages to prevent accidental exposure.

## Overview

The proxy includes comprehensive API key redaction to prevent sensitive credentials from appearing in logs, wire captures, error messages, or any other output. This "key hygiene" feature automatically detects and masks API keys before they can be written to disk or displayed, protecting your credentials even if logging is verbose or debugging is enabled.

Key redaction is always enabled and operates transparently across all proxy components.

## Key Features

- Automatic detection and redaction of API keys in all output
- Pattern-based matching for common API key formats
- Redaction in logs, wire captures, error messages, and debug output
- Preserves key prefixes for debugging (e.g., `sk-proj-****`)
- No performance impact on request processing
- Works with all supported LLM providers

## How It Works

The proxy uses a global logging filter that scans all log messages, wire capture entries, and error outputs for patterns that match known API key formats. When a potential API key is detected, it's automatically replaced with a redacted version that preserves enough information for debugging while hiding the sensitive portion.

**Redaction Examples**:

```
Original: sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx234yz
Redacted: sk-proj-****

Original: OPENAI_API_KEY=sk-1234567890abcdef
Redacted: OPENAI_API_KEY=sk-****

Original: Authorization: Bearer sk-proj-abc123def456
Redacted: Authorization: Bearer sk-proj-****
```

## Supported API Key Formats

The redaction system recognizes API keys from all major LLM providers:

### OpenAI

- Format: `sk-proj-*`, `sk-*`
- Example: `sk-proj-abc123def456...`
- Redacted: `sk-proj-****`

### Anthropic

- Format: `sk-ant-*`
- Example: `sk-ant-api03-abc123...`
- Redacted: `sk-ant-****`

### Google Gemini

- Format: `AIza*`
- Example: `AIzaSyAbc123Def456...`
- Redacted: `AIza****`

### OpenRouter

- Format: `sk-or-*`
- Example: `sk-or-v1-abc123...`
- Redacted: `sk-or-****`

### ZAI

- Format: Various ZAI key patterns
- Example: `zai_abc123def456...`
- Redacted: `zai_****`

### Proxy Authentication

- Format: Any value in `Authorization: Bearer` headers
- Example: `Authorization: Bearer my-secret-key`
- Redacted: `Authorization: Bearer ****`

### Environment Variables

The following environment variable names are automatically detected and their values redacted:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`
- `OPENROUTER_API_KEY`
- `ZENMUX_API_KEY`
- `ZAI_API_KEY`
- `MINIMAX_API_KEY`
- `LLM_INTERACTIVE_PROXY_API_KEY`
- `AUTH_TOKEN`
- `GOOGLE_CLOUD_PROJECT`

## Configuration

Key redaction is always enabled and requires no configuration. However, you can control what gets logged to reduce the risk of exposure:

### Logging Levels

```bash
# Reduce logging verbosity to minimize output
python -m src.core.cli --log-level WARNING

# Enable debug logging (keys will still be redacted)
python -m src.core.cli --log-level DEBUG
```

### Wire Capture

Wire captures automatically redact API keys:

```bash
# Enable wire capture (keys are redacted automatically)
python -m src.core.cli --capture-file logs/wire_capture.log
```

The `key_name` field in wire captures shows which environment variable was used (e.g., `OPENAI_API_KEY_1`) but never the actual key value.

## Usage Examples

### Viewing Logs Safely

Logs can be shared or reviewed without exposing API keys:

```bash
# View logs - API keys are automatically redacted
tail -f logs/proxy.log

# Search logs for errors - keys remain protected
grep ERROR logs/proxy.log

# Share logs with support - no manual redaction needed
cat logs/proxy.log | mail support@example.com
```

### Debugging with Wire Capture

Wire captures preserve debugging information while protecting keys:

```bash
# Enable wire capture
python -m src.core.cli --capture-file logs/wire_capture.log

# Review captured traffic - keys are redacted
cat logs/wire_capture.log | jq .

# Example output:
# {
#   "metadata": {
#     "key_name": "OPENAI_API_KEY_1",  // Shows which key was used
#     "backend": "openai"
#   },
#   "payload": {
#     "model": "gpt-4",
#     "messages": [...]
#   }
# }
```

### Error Messages

Error messages automatically redact keys:

```bash
# If an API key is invalid, the error message is safe to share
# Original error: "Invalid API key: sk-proj-abc123def456..."
# Logged error: "Invalid API key: sk-proj-****"
```

## Use Cases

### Sharing Logs for Support

Safely share logs with support teams or colleagues:

```bash
# Logs are safe to share - keys are automatically redacted
tar -czf logs.tar.gz logs/
# Send logs.tar.gz to support
```

### Public Issue Reporting

Include logs in public issue reports without manual redaction:

```bash
# Copy relevant log section to GitHub issue
# Keys are already redacted, no manual editing needed
grep -A 10 "ERROR" logs/proxy.log
```

### Debugging in Shared Environments

Debug issues in shared development environments without exposing keys:

```bash
# Enable verbose logging for debugging
python -m src.core.cli --log-level DEBUG

# Share debug output with team
# Keys are redacted automatically
```

### Compliance and Auditing

Meet compliance requirements for credential protection:

```bash
# Logs can be archived for compliance
# No risk of exposing credentials in archived logs
cp logs/proxy.log /archive/$(date +%Y%m%d)-proxy.log
```

## Best Practices

### 1. Never Store Keys in Config Files

Even though keys are redacted in logs, never store them in configuration files:

```yaml
# BAD - Don't do this
backends:
  openai:
    api_key: "sk-proj-abc123..."  # Never hardcode keys

# GOOD - Use environment variables
backends:
  openai:
    api_key_env: "OPENAI_API_KEY"  # Reference env var
```

### 2. Use Environment Variables

Always set API keys via environment variables:

```bash
# Set keys in environment
export OPENAI_API_KEY="sk-proj-..."
export ANTHROPIC_API_KEY="sk-ant-..."

# Start proxy (keys are loaded from environment)
python -m src.core.cli
```

### 3. Rotate Keys Regularly

Regularly rotate API keys to minimize exposure risk:

```bash
# Generate new keys from provider dashboards
# Update environment variables
export OPENAI_API_KEY="sk-proj-new-key..."

# Restart proxy with new keys
python -m src.core.cli
```

### 4. Review Logs Before Sharing

While redaction is automatic, always review logs before sharing externally:

```bash
# Quick check for any missed patterns
grep -i "sk-" logs/proxy.log
grep -i "api.key" logs/proxy.log
```

### 5. Secure Log Storage

Store logs securely even though keys are redacted:

```bash
# Set appropriate permissions
chmod 600 logs/proxy.log

# Use encrypted storage for archived logs
tar -czf - logs/ | gpg -e -r admin@example.com > logs.tar.gz.gpg
```

### 6. Monitor for Key Exposure

Set up alerts for potential key exposure attempts:

```bash
# Monitor for suspicious patterns in logs
grep -i "authorization" logs/proxy.log | grep -v "****"
```

### 7. Use Separate Keys per Environment

Use different API keys for development, staging, and production:

```bash
# Development
export OPENAI_API_KEY="sk-proj-dev-..."

# Production
export OPENAI_API_KEY="sk-proj-prod-..."
```

## Troubleshooting

### Keys Appearing in Output

**Problem**: API keys appear unredacted in some output.

**Possible Causes**:

1. **Custom Logging**: If you've added custom logging code, it may bypass the redaction filter
2. **Third-Party Libraries**: Some libraries may log directly to stdout/stderr
3. **Error Handlers**: Custom error handlers may not use the redaction filter

**Solution**: Ensure all logging goes through the proxy's logging system:

```python
# Use the proxy's logger
from src.core.common.logging_utils import get_logger

logger = get_logger(__name__)
logger.info("Message with potential key: %s", api_key)  # Automatically redacted
```

### Debugging Key Issues

**Problem**: Need to verify which API key is being used without exposing the key.

**Solution**: Check the `key_name` field in logs and wire captures:

```bash
# View which key was used (without seeing the actual key)
grep "key_name" logs/wire_capture.log

# Example output:
# "key_name": "OPENAI_API_KEY_1"
```

### Verifying Redaction

**Problem**: Want to verify that redaction is working correctly.

**Solution**: Test with a dummy key:

```bash
# Set a test key
export OPENAI_API_KEY="sk-proj-test123"

# Enable debug logging
python -m src.core.cli --log-level DEBUG

# Check logs - should see "sk-proj-****" not "sk-proj-test123"
grep "sk-proj" logs/proxy.log
```

## Security Considerations

### Redaction is Not Encryption

Key redaction prevents accidental exposure in logs but is not a substitute for proper key management:

- Keys are still stored in memory during processing
- Keys are transmitted to LLM providers (as required)
- Redaction only affects logged/captured output

### Defense in Depth

Use multiple layers of security:

1. **Environment Variables**: Store keys in environment, not files
2. **Redaction**: Automatic redaction in logs (this feature)
3. **Access Control**: Restrict access to logs and wire captures
4. **Encryption**: Encrypt logs at rest and in transit
5. **Rotation**: Regularly rotate API keys
6. **Monitoring**: Monitor for unauthorized access attempts

### Limitations

Redaction cannot protect against:

- Memory dumps or core dumps
- Debugger inspection of running processes
- Network traffic interception (use HTTPS)
- Compromised systems with root access

## Related Features

- [Authentication](authentication.md) - Proxy API key authentication
- [Brute-Force Protection](brute-force-protection.md) - Protection against key guessing attacks
- [Wire Capture](../debugging/wire-capture.md) - Debugging with automatic key redaction
