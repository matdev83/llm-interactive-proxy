# Troubleshooting Guide

This document provides solutions for common issues encountered when working with the LLM Interactive Proxy. It covers installation problems, configuration issues, runtime errors, and debugging techniques.

## Table of Contents

1. [Installation Issues](#installation-issues)
2. [Configuration Problems](#configuration-problems)
3. [API Authentication Issues](#api-authentication-issues)
4. [Backend Connection Problems](#backend-connection-problems)
5. [Command Processing Errors](#command-processing-errors)
6. [Session Management Issues](#session-management-issues)
7. [Streaming Response Problems](#streaming-response-problems)
8. [Loop Detection Issues](#loop-detection-issues)
9. [Tool Call Loop Detection Problems](#tool-call-loop-detection-problems)
10. [Rate Limiting Issues](#rate-limiting-issues)
11. [Performance Problems](#performance-problems)
12. [Debugging Techniques](#debugging-techniques)
13. [Logging and Observability](#logging-and-observability)

## Installation Issues

### Issue: Package Installation Fails

**Symptoms**:
- Error messages during `pip install`
- Missing dependencies
- Version conflicts

**Solutions**:

1. **Ensure Python Version Compatibility**:
   ```bash
   python --version  # Should be 3.9 or newer
   ```

2. **Create a Fresh Virtual Environment**:
   ```bash
   python -m venv .venv-new
   source .venv-new/bin/activate  # Linux/Mac
   .venv-new\Scripts\activate      # Windows
   ```

3. **Install with Verbose Output**:
   ```bash
   pip install -e ".[dev]" -v
   ```

4. **Check for System Dependencies**:
   Some packages may require system libraries. For example, on Ubuntu:
   ```bash
   sudo apt-get update
   sudo apt-get install python3-dev build-essential
   ```

### Issue: Import Errors After Installation

**Symptoms**:
- `ModuleNotFoundError` when running the application
- Incorrect module resolution

**Solutions**:

1. **Verify Package is Installed in Development Mode**:
   ```bash
   pip list | grep llm-interactive-proxy
   ```

2. **Check PYTHONPATH**:
   ```bash
   echo $PYTHONPATH  # Linux/Mac
   echo %PYTHONPATH%  # Windows
   ```

3. **Reinstall with Development Mode**:
   ```bash
   pip uninstall llm-interactive-proxy
   pip install -e .
   ```

## Configuration Problems

### Issue: Missing or Invalid Configuration

**Symptoms**:
- Error messages about missing configuration
- Application fails to start with configuration errors

**Solutions**:

1. **Create/Verify Configuration File**:
   ```bash
   cp config.example.yaml config.yaml
   # Edit config.yaml with your settings
   ```

2. **Set Required Environment Variables**:
   ```bash
   export OPENROUTER_API_KEY=your-api-key  # Linux/Mac
   set OPENROUTER_API_KEY=your-api-key     # Windows CMD
   $env:OPENROUTER_API_KEY="your-api-key"  # Windows PowerShell
   ```

3. **Check Configuration Path**:
   ```bash
   python -m src.core.cli --config /absolute/path/to/config.yaml
   ```

4. **Validate Configuration Format**:
   ```bash
   python -c "import yaml; yaml.safe_load(open('config.yaml'))"
   ```

### Issue: Backend Configuration Problems

**Symptoms**:
- "No functional backends available" error
- "Unknown backend" errors
- Backend not being recognized

**Solutions**:

1. **Check Backend Configuration**:
   ```yaml
   # config.yaml
   backends:
     openrouter:
       api_keys:
         default: your-api-key
     gemini:
       api_keys:
         default: your-api-key
   ```

2. **Verify API Keys**:
   ```bash
   curl -H "Authorization: Bearer your-api-key" https://api.openrouter.ai/v1/models
   ```

3. **Set Default Backend**:
   ```bash
   python -m src.core.cli --default-backend openrouter
   ```

## API Authentication Issues

### Issue: Unauthorized Access

**Symptoms**:
- HTTP 401 Unauthorized errors
- "Unauthorized" error messages

**Solutions**:

1. **Check API Key in Request**:
   ```bash
   curl -H "Authorization: Bearer your-api-key" http://localhost:8000/v2/chat/completions
   ```

2. **Disable Authentication for Testing**:
   ```bash
   python -m src.core.cli --disable-auth
   ```

3. **Verify API Key in Configuration**:
   ```yaml
   # config.yaml
   api_keys:
     - your-api-key
   ```

4. **Check Authorization Header Format**:
   Ensure it's `Bearer your-api-key` with a space after "Bearer"

### Issue: Invalid API Key Format

**Symptoms**:
- "Invalid API key format" errors
- Authentication fails despite providing API key

**Solutions**:

1. **Check API Key Format**:
   - OpenAI: Starts with "sk-"
   - Anthropic: Starts with "sk-ant-"
   - Gemini: No specific format

2. **Remove Whitespace or Quotes**:
   ```bash
   # Wrong
   export OPENAI_API_KEY=" sk-abcdef "
   
   # Correct
   export OPENAI_API_KEY=sk-abcdef
   ```

## Backend Connection Problems

### Issue: Connection Timeout

**Symptoms**:
- "Connection timeout" errors
- Requests hang for a long time before failing

**Solutions**:

1. **Increase Timeout Settings**:
   ```yaml
   # config.yaml
   proxy_timeout: 600  # 10 minutes
   ```

2. **Check Network Connectivity**:
   ```bash
   curl -v https://api.openrouter.ai/ping
   ```

3. **Use Proxy if Needed**:
   ```bash
   export HTTPS_PROXY=http://proxy.example.com:8080
   ```

### Issue: Invalid Backend or Model

**Symptoms**:
- "Unknown backend" errors
- "Model not found" errors

**Solutions**:

1. **List Available Models**:
   ```bash
   curl -H "Authorization: Bearer your-api-key" http://localhost:8000/v2/models
   ```

2. **Check Model Format**:
   - OpenAI: `gpt-4`, `gpt-3.5-turbo`
   - Anthropic: `claude-3-opus-20240229`
   - Gemini: `gemini-pro`, `gemini-1.5-pro`

3. **Specify Backend and Model**:
   ```bash
   curl -X POST \
     -H "Authorization: Bearer your-api-key" \
     -H "Content-Type: application/json" \
     -d '{"model":"openai:gpt-4", "messages":[{"role":"user","content":"Hello"}]}' \
     http://localhost:8000/v2/chat/completions
   ```

## Command Processing Errors

### Issue: Commands Not Recognized

**Symptoms**:
- Commands in messages are not processed
- Commands are sent to the LLM instead of being processed

**Solutions**:

1. **Check Command Prefix**:
   ```yaml
   # config.yaml
   command_prefix: "!/"
   ```

2. **Verify Command Format**:
   ```
   !/set(project=myproject)
   ```
   
   Not:
   ```
   !/ set(project=myproject)  # Space after prefix
   !/set (project=myproject)  # Space before parenthesis
   ```

3. **Enable Interactive Mode**:
   ```bash
   curl -X POST \
     -H "Authorization: Bearer your-api-key" \
     -H "Content-Type: application/json" \
     -d '{"model":"gpt-4", "messages":[{"role":"user","content":"!/interactive(true)"}]}' \
     http://localhost:8000/v2/chat/completions
   ```

4. **Check if Interactive Commands are Disabled**:
   ```yaml
   # config.yaml
   disable_interactive_commands: false  # Should be false
   ```

### Issue: Command Arguments Not Parsed Correctly

**Symptoms**:
- "Invalid arguments" errors
- Command executes but with unexpected behavior

**Solutions**:

1. **Check Argument Syntax**:
   ```
   !/set(project=myproject)  # Correct
   ```
   
   Not:
   ```
   !/set(project = myproject)  # Spaces around =
   !/set("project"="myproject")  # Quotes around keys
   ```

2. **Quote String Values with Spaces**:
   ```
   !/set(project="my project with spaces")
   ```

3. **Use Proper Comma Separation**:
   ```
   !/set(project=myproject, temperature=0.7)  # Correct
   ```
   
   Not:
   ```
   !/set(project=myproject temperature=0.7)  # Missing comma
   ```

## Session Management Issues

### Issue: Session State Not Persisting

**Symptoms**:
- Settings like project or backend don't persist between requests
- Each request seems to start with a fresh state

**Solutions**:

1. **Provide Session ID in Requests**:
   ```bash
   curl -X POST \
     -H "Authorization: Bearer your-api-key" \
     -H "Content-Type: application/json" \
     -H "x-session-id: my-session-id" \
     -d '{"model":"gpt-4", "messages":[{"role":"user","content":"Hello"}]}' \
     http://localhost:8000/v2/chat/completions
   ```

2. **Check Session Repository Configuration**:
   ```yaml
   # config.yaml
   session:
     repository: "in_memory"  # or "file" for persistent sessions
   ```

3. **Use Persistent Session Repository**:
   ```yaml
   # config.yaml
   session:
     repository: "file"
     file_path: "./data/sessions"
   ```

### Issue: Session ID Conflicts

**Symptoms**:
- Unexpected behavior when multiple clients use the same session ID
- Sessions overwriting each other

**Solutions**:

1. **Use Unique Session IDs**:
   ```bash
   # Generate a UUID for session ID
   SESSION_ID=$(python -c "import uuid; print(uuid.uuid4())")
   curl -X POST \
     -H "Authorization: Bearer your-api-key" \
     -H "Content-Type: application/json" \
     -H "x-session-id: $SESSION_ID" \
     -d '{"model":"gpt-4", "messages":[{"role":"user","content":"Hello"}]}' \
     http://localhost:8000/v2/chat/completions
   ```

2. **Namespace Session IDs**:
   ```bash
   # Use a prefix for each client
   curl -X POST \
     -H "Authorization: Bearer your-api-key" \
     -H "Content-Type: application/json" \
     -H "x-session-id: client1-session1" \
     -d '{"model":"gpt-4", "messages":[{"role":"user","content":"Hello"}]}' \
     http://localhost:8000/v2/chat/completions
   ```

## Streaming Response Problems

### Issue: Streaming Responses Not Working

**Symptoms**:
- No streaming data received
- Response only arrives when complete

**Solutions**:

1. **Set `stream` Parameter to `true`**:
   ```bash
   curl -X POST \
     -H "Authorization: Bearer your-api-key" \
     -H "Content-Type: application/json" \
     -d '{"model":"gpt-4", "messages":[{"role":"user","content":"Hello"}], "stream": true}' \
     http://localhost:8000/v2/chat/completions
   ```

2. **Check Client Streaming Support**:
   Ensure your client can handle server-sent events (SSE).

3. **Disable Response Buffering**:
   Some HTTP clients or proxies may buffer streaming responses.

4. **Test with a Simple Client**:
   ```python
   import requests
   response = requests.post(
       "http://localhost:8000/v2/chat/completions",
       headers={"Authorization": "Bearer your-api-key"},
       json={"model": "gpt-4", "messages": [{"role": "user", "content": "Hello"}], "stream": true},
       stream=True
   )
   for line in response.iter_lines():
       if line:
           print(line.decode('utf-8'))
   ```

### Issue: Streaming Responses Cut Off

**Symptoms**:
- Streaming starts but stops prematurely
- Incomplete responses

**Solutions**:

1. **Increase Proxy Timeout**:
   ```yaml
   # config.yaml
   proxy_timeout: 600  # 10 minutes
   ```

2. **Increase Client Timeout**:
   ```python
   import requests
   response = requests.post(
       "http://localhost:8000/v2/chat/completions",
       headers={"Authorization": "Bearer your-api-key"},
       json={"model": "gpt-4", "messages": [{"role": "user", "content": "Hello"}], "stream": true},
       stream=True,
       timeout=300  # 5 minutes
   )
   ```

3. **Check for Network Issues**:
   Ensure stable network connection between client, proxy, and LLM provider.

## Loop Detection Issues

### Issue: False Positives in Loop Detection

**Symptoms**:
- Legitimate responses are cut off with loop detection warnings
- Non-repetitive content is flagged as repetitive

**Solutions**:

1. **Adjust Loop Detection Configuration**:
   ```yaml
   # config.yaml
   loop_detection:
     enabled: true
     min_pattern_length: 50
     max_pattern_length: 500
     min_repetitions: 3
   ```

2. **Disable Loop Detection for Specific Sessions**:
   ```bash
   curl -X POST \
     -H "Authorization: Bearer your-api-key" \
     -H "Content-Type: application/json" \
     -d '{"model":"gpt-4", "messages":[{"role":"user","content":"!/set(loop_detection_enabled=false)"}]}' \
     http://localhost:8000/v2/chat/completions
   ```

3. **Tune Threshold for Different Content Types**:
   - For code: Increase `min_pattern_length` to 100+
   - For prose: Lower `min_repetitions` to 2

### Issue: Loop Detection Not Working

**Symptoms**:
- Repetitive content continues without interruption
- No loop detection warnings

**Solutions**:

1. **Enable Loop Detection**:
   ```yaml
   # config.yaml
   loop_detection:
     enabled: true
   ```

2. **Check Minimum Pattern Length**:
   ```yaml
   # config.yaml
   loop_detection:
     min_pattern_length: 20  # Lower value to catch shorter patterns
   ```

3. **Verify Loop Detection Middleware is Registered**:
   Check logs for middleware initialization messages.

## Tool Call Loop Detection Problems

### Issue: Tool Call Loops Not Detected

**Symptoms**:
- Same tool is called repeatedly with similar arguments
- No intervention from the tool call loop detection

**Solutions**:

1. **Enable Tool Call Loop Detection**:
   ```yaml
   # config.yaml
   tool_call_loop:
     enabled: true
     max_repeats: 3
     ttl_seconds: 300
     mode: "block"  # Options: block, warn, chance_then_block
   ```

2. **Set Session-Level Configuration**:
   ```bash
   curl -X POST \
     -H "Authorization: Bearer your-api-key" \
     -H "Content-Type: application/json" \
     -d '{"model":"gpt-4", "messages":[{"role":"user","content":"!/set(tool_loop_detection_enabled=true, tool_loop_max_repeats=3)"}]}' \
     http://localhost:8000/v2/chat/completions
   ```

3. **Check for Tool Call Format**:
   Ensure tool calls follow the standard OpenAI format.

### Issue: False Positives in Tool Call Loop Detection

**Symptoms**:
- Legitimate tool calls are blocked
- Different tool calls are identified as repeats

**Solutions**:

1. **Increase Max Repeats**:
   ```yaml
   # config.yaml
   tool_call_loop:
     max_repeats: 5  # Allow more repetitions
   ```

2. **Use chance_then_block Mode**:
   ```yaml
   # config.yaml
   tool_call_loop:
     mode: "chance_then_block"  # Give a warning before blocking
   ```

3. **Increase TTL**:
   ```yaml
   # config.yaml
   tool_call_loop:
     ttl_seconds: 600  # 10 minutes
   ```

## Rate Limiting Issues

### Issue: Rate Limit Exceeded

**Symptoms**:
- HTTP 429 Too Many Requests errors
- "Rate limit exceeded" error messages

**Solutions**:

1. **Check Rate Limit Configuration**:
   ```yaml
   # config.yaml
   rate_limits:
     default:
       limit: 60  # Requests per minute
       time_window: 60  # Seconds
     backend:openai:
       limit: 100
       time_window: 60
   ```

2. **Use Multiple API Keys**:
   ```yaml
   # config.yaml
   backends:
     openai:
       api_keys:
         key1: sk-key1
         key2: sk-key2
   ```

3. **Implement Backoff and Retry Logic**:
   ```python
   import requests
   import time
   
   def make_request_with_retry(url, headers, data, max_retries=5):
       for i in range(max_retries):
           response = requests.post(url, headers=headers, json=data)
           if response.status_code != 429:
               return response
           retry_after = int(response.headers.get("Retry-After", 1))
           time.sleep(retry_after)
       return response  # Return last response if all retries failed
   ```

### Issue: Uneven API Key Usage

**Symptoms**:
- Some API keys are used more than others
- Unbalanced load across keys

**Solutions**:

1. **Use Round-Robin Policy**:
   ```yaml
   # config.yaml
   backends:
     openai:
       policy: "round-robin"
       api_keys:
         key1: sk-key1
         key2: sk-key2
   ```

2. **Configure Failover Routes**:
   ```bash
   curl -X POST \
     -H "Authorization: Bearer your-api-key" \
     -H "Content-Type: application/json" \
     -d '{"model":"gpt-4", "messages":[{"role":"user","content":"!/route-list"}]}' \
     http://localhost:8000/v2/chat/completions
   ```

## Performance Problems

### Issue: High Latency

**Symptoms**:
- Requests take a long time to process
- High response times

**Solutions**:

1. **Use Faster Models**:
   ```bash
   curl -X POST \
     -H "Authorization: Bearer your-api-key" \
     -H "Content-Type: application/json" \
     -d '{"model":"gpt-3.5-turbo", "messages":[{"role":"user","content":"Hello"}]}' \
     http://localhost:8000/v2/chat/completions
   ```

2. **Monitor Performance with Tracking**:
   ```python
   from src.performance_tracker import track_request_performance
   
   with track_request_performance() as perf:
       # Your code here
       pass
   
   print(f"Processing time: {perf.elapsed_time_ms}ms")
   ```

3. **Enable Response Caching**:
   ```yaml
   # config.yaml
   response_cache:
     enabled: true
     ttl: 3600  # 1 hour
   ```

### Issue: Memory Leaks

**Symptoms**:
- Increasing memory usage over time
- Application crashes with out-of-memory errors

**Solutions**:

1. **Limit Session History**:
   ```yaml
   # config.yaml
   session:
     max_history_items: 10
   ```

2. **Implement Session Expiry**:
   ```yaml
   # config.yaml
   session:
     expiry_seconds: 3600  # 1 hour
   ```

3. **Monitor Memory Usage**:
   ```python
   import psutil
   import os
   
   def print_memory_usage():
       process = psutil.Process(os.getpid())
       print(f"Memory usage: {process.memory_info().rss / 1024 / 1024} MB")
   ```

## Debugging Techniques

### Command Line Debugging

1. **Enable Debug Logging**:
   ```bash
   python -m src.core.cli --log-level debug
   ```

2. **Test Individual Components**:
   ```python
   # Example: Test session service
   python -c "from src.core.services.session_service import SessionService; from src.core.repositories.in_memory_session_repository import InMemorySessionRepository; s = SessionService(InMemorySessionRepository()); print(s.get_session('test'))"
   ```

3. **Use the Debug Scripts**:
   ```bash
   python debug_streaming.py
   ```

### HTTP Request Debugging

1. **Check Request Format**:
   ```bash
   curl -v -X POST \
     -H "Authorization: Bearer your-api-key" \
     -H "Content-Type: application/json" \
     -d '{"model":"gpt-4", "messages":[{"role":"user","content":"Hello"}]}' \
     http://localhost:8000/v2/chat/completions
   ```

2. **Monitor HTTP Traffic**:
   ```bash
   pip install mitmproxy
   mitmproxy -p 8080
   
   # Then set environment variables
   export HTTPS_PROXY=http://localhost:8080
   ```

3. **Test with Minimal Request**:
   ```bash
   curl -X POST \
     -H "Authorization: Bearer your-api-key" \
     -H "Content-Type: application/json" \
     -d '{"model":"gpt-3.5-turbo", "messages":[{"role":"user","content":"Hi"}], "max_tokens": 10}' \
     http://localhost:8000/v2/chat/completions
   ```

### Python Debugging

1. **Use `pdb` for Interactive Debugging**:
   ```python
   import pdb; pdb.set_trace()
   ```

2. **Add Debug Logging**:
   ```python
   import logging
   logging.basicConfig(level=logging.DEBUG)
   logger = logging.getLogger(__name__)
   logger.debug(f"Variable value: {variable}")
   ```

3. **Profile Code Execution**:
   ```bash
   python -m cProfile -o profile.pstats -m src.core.cli
   python -m pstats profile.pstats
   ```

## Logging and Observability

### Issue: Missing Logs

**Symptoms**:
- No logs being generated
- Logs missing important information

**Solutions**:

1. **Set Log Level**:
   ```bash
   python -m src.core.cli --log-level debug
   ```

2. **Configure Log Format**:
   ```yaml
   # config.yaml
   logging:
     level: debug
     format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
   ```

3. **Enable File Logging**:
   ```yaml
   # config.yaml
   logging:
     file: "logs/llm-proxy.log"
     max_size_mb: 10
     backup_count: 5
   ```

### Issue: Too Many Logs

**Symptoms**:
- Logs filled with unnecessary information
- Hard to find relevant information

**Solutions**:

1. **Filter Logs by Module**:
   ```yaml
   # config.yaml
   logging:
     level: info
     per_module:
       src.core.services.backend_service: debug
       src.core.services.command_service: debug
       httpx: warning
   ```

2. **Use Log Rotation**:
   ```yaml
   # config.yaml
   logging:
     file: "logs/llm-proxy.log"
     max_size_mb: 10
     backup_count: 5
   ```

3. **Filter by Component at Runtime**:
   ```bash
   python -m src.core.cli | grep "BackendService"
   ```

### Issue: No Audit Trail

**Symptoms**:
- Unable to trace requests and responses
- Missing usage information

**Solutions**:

1. **Enable Audit Logging**:
   ```yaml
   # config.yaml
   audit:
     enabled: true
     file: "logs/audit.log"
   ```

2. **Access Audit Logs API**:
   ```bash
   curl -H "Authorization: Bearer your-api-key" \
     http://localhost:8000/v2/audit/logs
   ```

3. **Configure Usage Tracking**:
   ```yaml
   # config.yaml
   usage_tracking:
     enabled: true
     repository: "file"
     file_path: "./data/usage"
   ```

## Additional Resources

- **API Reference**: See `docs/API_REFERENCE.md` for detailed API documentation
- **Configuration**: See `docs/CONFIGURATION.md` for configuration options
- **Architecture**: See `docs/ARCHITECTURE.md` for architecture information
- **Developer Guide**: See `docs/DEVELOPER_GUIDE.md` for development guidelines

If you're still experiencing issues, please [open an issue](https://github.com/your-org/llm-interactive-proxy/issues) with detailed information about your problem.
