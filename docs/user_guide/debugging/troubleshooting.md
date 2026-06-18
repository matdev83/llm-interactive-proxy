# Troubleshooting

This guide covers common issues and their solutions when using the LLM Interactive Proxy.

## Common Errors

### Authentication Errors

#### 401 Unauthorized

**Error**: `401 Unauthorized` response from proxy

**Cause**: Missing or invalid `Authorization` header when proxy authentication is enabled

**Solutions**:

1. **Check if authentication is enabled**:
   ```bash
   # Look for auth configuration in your config file
   grep -A 5 "auth:" config.yaml
   ```

2. **Provide valid API key**:
   ```bash
   curl -X POST http://localhost:8000/v1/chat/completions \
     -H "Authorization: Bearer YOUR_PROXY_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"model": "openai:gpt-4", "messages": [...]}'
   ```

3. **Disable authentication for testing**:
   ```yaml
   # config.yaml
   auth:
     enabled: false
   ```

#### 403 Forbidden

**Error**: `403 Forbidden` response from proxy

**Cause**: API key is recognized but lacks required permissions

**Solutions**:

1. **Verify API key permissions** in your configuration
2. **Check IP-based restrictions** if configured
3. **Review brute-force protection** - you may be temporarily blocked

### Request Errors

#### 400 Bad Request

**Error**: `400 Bad Request` response

**Cause**: Malformed request payload

**Solutions**:

1. **Verify request format** matches the API you're using:
   - OpenAI: `/v1/chat/completions` expects OpenAI format
   - Anthropic: `/anthropic/v1/messages` expects Anthropic format
   - Gemini: `/v1beta/models` expects Gemini format

2. **Check required fields**:
   ```json
   {
     "model": "openai:gpt-4",  // Required
     "messages": [              // Required
       {"role": "user", "content": "Hello"}
     ]
   }
   ```

3. **Validate JSON syntax**:
   ```bash
   # Use jq to validate JSON
   echo '{"model": "test"}' | jq .
   ```

#### 422 Unprocessable Entity

**Error**: `422 Unprocessable Entity` response

**Cause**: Request validation failed

**Solutions**:

1. **Check error details** in the response body:
   ```json
   {
     "error": {
       "message": "Validation error",
       "details": {
         "field": "temperature",
         "issue": "must be between 0 and 2"
       }
     }
   }
   ```

2. **Verify parameter values**:
   - `temperature`: 0.0 to 2.0
   - `top_p`: 0.0 to 1.0
   - `max_tokens`: positive integer

3. **Check model name format**:
   ```
   Valid: openai:gpt-4
   Valid: anthropic:claude-3-opus
   Invalid: gpt-4 (missing backend prefix)
   ```

#### 400 Context Length Exceeded

**Error**: `400 Bad Request` with `context_length_exceeded` error code

**Cause**: Request exceeds model's context window limits

**Solutions**:

1. **Check error details** for token counts:
   ```json
   {
     "error": {
       "type": "invalid_request_error",
       "code": "context_length_exceeded",
       "param": "input",
       "message": "Your input exceeds the context window of this model. Please adjust your input and try again.",
       "details": {
         "measured": 150000,
         "limit": 128000,
         "model": "openai:gpt-4"
       }
     }
   }
   ```

2. **Reduce input size**:
   - Shorten messages
   - Remove unnecessary context
   - Split into multiple requests

3. **Use a model with larger context window**:
   ```
   openai:gpt-4-turbo-128k
   anthropic:claude-3-opus (200k context)
   ```

4. **Enable [context window enforcement](../features/context-window-enforcement.md)**:
   ```yaml
   session:
     context_window_enforcement_enabled: true
   ```

### Backend Errors

#### 503 Service Unavailable

**Error**: `503 Service Unavailable` response

**Cause**: Upstream LLM provider is unreachable

**Solutions**:

1. **Check backend connectivity**:
   ```bash
   # Test OpenAI
   curl https://api.openai.com/v1/models \
     -H "Authorization: Bearer $OPENAI_API_KEY"
   
   # Test Anthropic
   curl https://api.anthropic.com/v1/messages \
     -H "x-api-key: $ANTHROPIC_API_KEY"
   ```

2. **Verify API keys are set**:
   ```bash
   echo $OPENAI_API_KEY
   echo $ANTHROPIC_API_KEY
   ```

3. **Try another backend**:
   ```bash
   # Switch from OpenAI to Anthropic
   curl -X POST http://localhost:8000/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{"model": "anthropic:claude-3-opus", "messages": [...]}'
   ```

4. **Enable failover** (if configured):
   ```yaml
   backends:
     openai:
       failover_to: anthropic
   ```

#### Model Not Found

**Error**: `404 Not Found` or "Model not found" error

**Cause**: Model name doesn't exist for the selected backend

**Solutions**:

1. **Verify model name** for your backend:
   ```bash
   # OpenAI models
   openai:gpt-4
   openai:gpt-4-turbo
   openai:gpt-3.5-turbo
   
   # Anthropic models
   anthropic:claude-3-opus-20240229
   anthropic:claude-3-sonnet-20240229
   anthropic:claude-3-haiku-20240307
   ```

2. **Check backend documentation** for available models

3. **Use [model name rewrites](../features/model-name-rewrites.md)** to map to available models:
   ```yaml
   model_rewrites:
     - pattern: "gpt-4"
       replacement: "openai:gpt-4-turbo"
   ```

### Rate Limiting

#### 429 Too Many Requests

**Error**: `429 Too Many Requests` response

**Cause**: Rate limit exceeded (proxy or backend)

**Solutions**:

1. **Check if it's proxy brute-force protection**:
   ```
   Response headers:
   Retry-After: 30
   ```
   Wait for the specified time before retrying

2. **Check if it's backend rate limiting**:
   - Review your API plan limits
   - Upgrade your API plan
   - Use multiple backend instances (e.g. `openai.1`, `openai.2`) for load balancing

3. **Enable API Key Rotation (multi-instance load balancing)**:
   ```yaml
   # Configure multiple backend instances in environment or config files
   # Environment:
   # OPENAI_API_KEY_1=sk-...
   # OPENAI_API_KEY_2=sk-...
   ```

4. **Adjust brute-force protection** (if proxy-side):
   ```yaml
   auth:
     brute_force_protection:
       max_failed_attempts: 10
       ttl_seconds: 900
   ```

## Debugging Tips

### Enable Wire Capture

For tricky issues, enable wire capture to see exact requests and responses:

```bash
python -m src.core.cli \
  --capture-file logs/debug.log \
  --default-backend openai
```

Then analyze the capture:

```bash
# View all requests
jq 'select(.direction=="outbound_request")' logs/debug.log

# View all errors
jq 'select(.direction=="inbound_response" and .payload.error)' logs/debug.log
```

### Use Interactive Commands

Test different backends and models without restarting:

```bash
# In your LLM client, send these commands:
!/backend(anthropic)
!/model(claude-3-opus)
!/temperature(0.5)
```

### Check Environment Variables

Verify all required environment variables are set:

```bash
# List all LLM-related environment variables
env | grep -E "(OPENAI|ANTHROPIC|GEMINI|API_KEY)"

# Check specific backend
echo "OpenAI: $OPENAI_API_KEY"
echo "Anthropic: $ANTHROPIC_API_KEY"
```

### Review Logs

Check proxy logs for detailed error information:

```bash
# View recent logs
tail -f logs/proxy.log

# Search for errors
grep ERROR logs/proxy.log

# Search for specific session
grep "session-123" logs/proxy.log
```

### Test with curl

Isolate issues by testing with curl:

```bash
# Basic test
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test-key" \
  -d '{
    "model": "openai:gpt-3.5-turbo",
    "messages": [{"role": "user", "content": "Hello"}]
  }' | jq .

# Test streaming
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test-key" \
  -d '{
    "model": "openai:gpt-3.5-turbo",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

## Configuration Issues

### Configuration Not Loading

**Problem**: Configuration changes don't take effect

**Solutions**:

1. **Verify configuration file path**:
   ```bash
   python -m src.core.cli --config config.yaml
   ```

2. **Check YAML syntax**:
   ```bash
   # Validate YAML
   python -c "import yaml; yaml.safe_load(open('config.yaml'))"
   ```

3. **Check configuration precedence**:
   - CLI arguments override environment variables
   - Environment variables override config file
   - Config file is the lowest priority

4. **Restart the proxy** after configuration changes

### Environment Variables Not Working

**Problem**: Environment variables are not being recognized

**Solutions**:

1. **Export variables** in the same shell:
   ```bash
   export OPENAI_API_KEY="sk-..."
   python -m src.core.cli
   ```

2. **Use .env file**:
   ```bash
   # Create .env file
   echo "OPENAI_API_KEY=sk-..." > .env
   
   # Load with python-dotenv
   python -m src.core.cli
   ```

3. **Check variable names** match expected format:
   ```bash
   # Correct
   OPENAI_API_KEY=sk-...
   
   # Incorrect
   OPENAI_KEY=sk-...
   ```

## Performance Issues

### Slow Response Times

**Problem**: Requests take too long to complete

**Solutions**:

1. **Check backend latency**:
   ```bash
   # Enable wire capture and analyze timing
   jq -r 'select(.direction=="inbound_response") | 
     "\(.timestamp_iso) \(.model)"' logs/wire_capture.log
   ```

2. **Reduce request size**:
   - Shorter prompts
   - Fewer messages in history
   - Lower max_tokens

3. **Use faster models**:
   ```
   Fast: openai:gpt-3.5-turbo
   Fast: anthropic:claude-3-haiku
   Slow: openai:gpt-4
   Slow: anthropic:claude-3-opus
   ```

4. **Check network connectivity**:
   ```bash
   ping api.openai.com
   traceroute api.openai.com
   ```

### High Memory Usage

**Problem**: Proxy consumes too much memory

**Solutions**:

1. **Reduce buffer sizes**:
   ```yaml
   logging:
     capture_buffer_size: 32768  # 32KB instead of 64KB
   ```

2. **Disable wire capture** when not needed

3. **Limit session history**:
   ```yaml
   session:
     max_history_turns: 50
   ```

4. **Restart proxy periodically** for long-running instances

## Feature-Specific Issues



**Solutions**:

1. **Verify assessment is enabled**:
   ```bash
   ```

2. **Check turn threshold**:
   ```yaml
     turn_threshold: 30  # Lower for more frequent checks
   ```

3. **Verify assessment backend is configured**:
   ```yaml
     backend: openai
     model: gpt-4o-mini
   ```

4. **Check logs** for assessment activity:
   ```bash
   grep "LLM Assessment" logs/proxy.log
   ```

### Tool Access Control Not Blocking

**Problem**: Tool calls are not being blocked by [access control](../features/tool-access-control.md)

**Solutions**:

1. **Verify tool access control is enabled**:
   ```yaml
   session:
     tool_call_reactor:
       enabled: true
   ```

2. **Check policy patterns**:
   ```yaml
   access_policies:
     - name: block_dangerous
       model_pattern: ".*"  # Matches all models
       blocked_patterns:
         - "delete_.*"
         - "rm_.*"
   ```

3. **Review policy priority**:
   - Higher priority policies override lower ones
   - Allowed patterns override blocked patterns

4. **Check logs** for policy evaluation:
   ```bash
   grep "Tool Access Control" logs/proxy.log
   ```

### Dangerous Command Protection Not Working

**Problem**: [Dangerous git commands](../features/dangerous-command-protection.md) are not being blocked

**Solutions**:

1. **Verify protection is enabled**:
   ```bash
   # Should NOT have this flag
   python -m src.core.cli  # (without --disable-dangerous-git-commands-protection)
   ```

2. **Check environment variable**:
   ```bash
   echo $DANGEROUS_COMMAND_PREVENTION_ENABLED  # Should be "true" or unset
   ```

3. **Review configuration**:
   ```yaml
   session:
     dangerous_command_prevention_enabled: true
   ```

4. **Check logs** for blocked commands:
   ```bash
   grep "Dangerous command blocked" logs/proxy.log
   ```

## Getting Help

### Collect Diagnostic Information

When reporting issues, include:

1. **Proxy version**:
   ```bash
   python -m src.core.cli --version
   ```

2. **Configuration** (sanitized):
   ```bash
   # Remove API keys before sharing
   cat config.yaml | grep -v "api_key"
   ```

3. **Error messages** from logs:
   ```bash
   grep ERROR logs/proxy.log | tail -20
   ```

4. **Wire capture** (if applicable):
   ```bash
   # Sanitize and share relevant entries
   jq 'del(.payload.messages[].content)' logs/wire_capture.log
   ```

5. **Steps to reproduce** the issue

### Where to Get Help

- **GitHub Issues**: [Open an issue](https://github.com/matdev83/llm-interactive-proxy/issues)
- **Documentation**: Check other guides in this documentation
- **Wire Capture**: Use wire capture to diagnose complex issues

## Related Features

- [Wire Capture](wire-capture.md) - Capture and analyze HTTP traffic
- [CBOR Capture](cbor-capture.md) - Binary capture for regression testing
- [Security](../security/authentication.md) - Authentication and security features
- [Configuration](../configuration.md) - Configuration guide
