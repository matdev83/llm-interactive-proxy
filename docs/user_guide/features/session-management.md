# Intelligent Session Management

Automatically detect conversation continuity without requiring clients to send session IDs, eliminating context loss issues.

## Overview

The Intelligent Session Management feature uses message history fingerprinting to automatically detect conversation continuity without requiring clients to send session IDs. This eliminates context loss issues common with stateless LLM clients. The proxy analyzes message history to determine if a request is a continuation of an existing conversation or a genuinely new session, enabling seamless multi-conversation support and long-lived sessions.

## Key Features

- **Automatic Session Detection**: Detects conversation continuity without explicit session IDs
- **Message Fingerprinting**: Creates stable hashes from message history for identification
- **Fuzzy Matching**: Detects continuations even when history doesn't match exactly
- **Multi-Conversation Support**: Different conversations automatically get different sessions
- **Long-Lived Sessions**: Sessions can resume after hours or days of inactivity
- **Zero Client Changes**: Works with any LLM client without modifications

## Configuration

Session management is configured in the `session.session_continuity` section of your config file.

### YAML Configuration

```yaml
session:
  session_continuity:
    enabled: true                       # Enable intelligent session detection
    fuzzy_matching: true                # Enable fuzzy matching for continuations
    max_session_age_seconds: 604800     # 7 days (default)
    fingerprint_message_count: 5        # Number of messages to fingerprint
    client_key_includes_ip: true        # Include client IP in fingerprinting
```

### Configuration Options

- **enabled**: Enable/disable intelligent session detection (default: true)
- **fuzzy_matching**: Enable fuzzy matching for continuations (default: true)
- **max_session_age_seconds**: Maximum session age before expiration (default: 604800 = 7 days)
- **fingerprint_message_count**: Number of recent messages to use for fingerprinting (default: 5)
- **client_key_includes_ip**: Include client IP address in fingerprinting (default: true)

## Usage Examples

### Basic Configuration

Enable with default settings:

```yaml
session:
  session_continuity:
    enabled: true
```

### Custom Fingerprint Size

Use more messages for fingerprinting (more precise, but less flexible):

```yaml
session:
  session_continuity:
    enabled: true
    fingerprint_message_count: 10  # Use last 10 messages
```

### Shorter Session Lifetime

Expire sessions after 1 day instead of 7:

```yaml
session:
  session_continuity:
    enabled: true
    max_session_age_seconds: 86400  # 1 day
```

### Disable IP-Based Fingerprinting

Don't include client IP in fingerprinting (useful for proxied environments):

```yaml
session:
  session_continuity:
    enabled: true
    client_key_includes_ip: false
```

### Disable Fuzzy Matching

Require exact history matches (more strict):

```yaml
session:
  session_continuity:
    enabled: true
    fuzzy_matching: false
```

## How It Works

### 1. Automatic Session Detection

When a client sends a request without an `x-session-id` header, the proxy analyzes the message history to determine if it's a continuation or a new session.

### 2. Message Fingerprinting

The proxy computes a stable hash from the last N messages (configurable) to create a unique conversation fingerprint:

```
Messages: ["Hello", "How are you?", "I'm fine", "What's the weather?", "It's sunny"]
Fingerprint: hash(last 5 messages) = "a1b2c3d4e5f6..."
```

### 3. Fuzzy Matching

If an exact fingerprint match isn't found, the proxy uses fuzzy matching to detect if the current request's messages contain the history from a recent session:

```
Existing session: ["Hello", "How are you?", "I'm fine"]
New request: ["Hello", "How are you?", "I'm fine", "What's the weather?"]
Result: Fuzzy match found - continuation of existing session
```

### 4. Multi-Conversation Support

Different conversations from the same client (different fingerprints) automatically get different sessions:

```
Conversation A: "Tell me about Python" -> Session 1
Conversation B: "What's the capital of France?" -> Session 2
```

### 5. Long-Lived Sessions

Sessions can resume after hours or days of inactivity (up to `max_session_age_seconds`):

```
Day 1: Start conversation about Python
Day 3: Resume conversation about Python (same session)
Day 8: Session expired, new session created
```

## Benefits

### Zero Client Changes Required

Works with any LLM client without modifications:

- Kilo Code
- Cline
- Cursor
- Custom clients
- Any OpenAI/Anthropic/Gemini compatible client

### Prevents Context Loss

Mid-conversation context is never lost due to missing session IDs:

```
# Without session management:
Request 1: "Tell me about Python"
Request 2: "What about its history?" -> No context, model doesn't know what "its" refers to

# With session management:
Request 1: "Tell me about Python" -> Session created
Request 2: "What about its history?" -> Same session, model has context
```

### Concurrent Conversations

Same client can have multiple active conversations simultaneously:

```
Client A:
  - Conversation 1: Python discussion -> Session 1
  - Conversation 2: JavaScript discussion -> Session 2
  - Conversation 3: Database design -> Session 3
```

### Transparent Operation

Clients don't need to know about the proxy's session management:

```
# Client just sends requests
POST /v1/chat/completions
{
  "messages": [...]
}

# Proxy automatically manages sessions
```

## Explicit Session Control

Clients can still explicitly control sessions by sending the `x-session-id` header, which takes precedence over automatic detection:

```bash
curl -H "x-session-id: my-custom-session-123" \
  -X POST http://localhost:8000/v1/chat/completions \
  -d '{"messages": [...]}'
```

This is useful for:

- Forcing a new session
- Resuming a specific session by ID
- Debugging session-related issues
- Implementing custom session management

## Use Cases

### Stateless Clients

Clients that don't maintain session state can still have continuous conversations:

```bash
# Client sends requests without session IDs
# Proxy automatically maintains session continuity
```

### Multi-Tab Applications

Web applications with multiple tabs can have separate conversations:

```
Tab 1: Python tutorial -> Session A
Tab 2: JavaScript tutorial -> Session B
Tab 3: Database design -> Session C
```

### Long-Running Projects

Projects that span multiple days maintain context:

```
Day 1: "Let's build a web app"
Day 2: "Add authentication" (same session, has context)
Day 3: "Deploy to production" (same session, has full history)
```

### Development and Testing

Developers can test without worrying about session management:

```bash
# Just send requests, sessions are automatic
curl -X POST http://localhost:8000/v1/chat/completions -d '{"messages": [...]}'
```

## Troubleshooting

**Sessions not being detected:**

- Verify session continuity is enabled in config
- Check that message history is being sent in requests
- Review logs for fingerprinting messages
- Ensure `fingerprint_message_count` is appropriate for your use case

**Wrong session being matched:**

- Increase `fingerprint_message_count` for more precise matching
- Disable fuzzy matching if it's too aggressive
- Use explicit `x-session-id` headers for critical sessions
- Review fingerprinting logs to understand matching behavior

**Sessions expiring too quickly:**

- Increase `max_session_age_seconds` in configuration
- Check system time and timezone settings
- Review logs for session expiration messages
- Consider if sessions should be explicitly managed

**Multiple conversations getting same session:**

- Verify message histories are different enough
- Increase `fingerprint_message_count` for better differentiation
- Check if fuzzy matching is too permissive
- Review fingerprinting logs to understand matching

**Performance impact:**

- Fingerprinting adds minimal overhead (<1ms per request)
- Fuzzy matching may add slight latency for large session counts
- Disable fuzzy matching if performance is critical
- Monitor session count and clean up old sessions

## Related Features

- [Context Window Enforcement](context-window-enforcement.md) - Enforce per-model context window limits
- [LLM Assessment System](llm-assessment.md) - Monitor conversation quality over time
- [Angel Verification System](angel-verification.md) - Verify individual responses
- [Planning Phase Overrides](planning-phase.md) - Use different models during planning
