# API Reference

This document provides a reference for the API endpoints exposed by the LLM Interactive Proxy.

## API Versioning

The API is versioned using URL path prefixes:

- `/v1/` - Legacy API (compatible with OpenAI/Anthropic)
- `/v2/` - New SOLID architecture API

## Authentication

All endpoints require authentication unless the server is started with `--disable-auth`.

Authentication is performed using the `Authorization` header with a bearer token:

```
Authorization: Bearer <api-key>
```

## Session Management

Sessions are identified using the `x-session-id` header. If not provided, a new session ID will be generated.

```
x-session-id: <session-id>
```

## Endpoints

### Chat Completions

#### Legacy Endpoint (OpenAI Compatible)

```
POST /v1/chat/completions
```

#### New SOLID Architecture Endpoint

```
POST /v2/chat/completions
```

**Request Body:**

```json
{
  "model": "gpt-3.5-turbo",
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant."
    },
    {
      "role": "user",
      "content": "Hello, how are you?"
    }
  ],
  "stream": false,
  "temperature": 0.7,
  "max_tokens": 1024,
  "session_id": "optional-session-id"
}
```

**Response:**

```json
{
  "id": "chatcmpl-123",
  "object": "chat.completion",
  "created": 1677858242,
  "model": "gpt-3.5-turbo",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello! I'm doing well, thank you for asking. How can I assist you today?"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 25,
    "completion_tokens": 18,
    "total_tokens": 43
  }
}
```

### Anthropic Messages

#### Legacy Endpoint (Anthropic Compatible)

```
POST /v1/messages
```

#### New SOLID Architecture Endpoint

```
POST /v2/messages
```

**Request Body:**

```json
{
  "model": "claude-3-opus-20240229",
  "messages": [
    {
      "role": "user",
      "content": "Hello, how are you?"
    }
  ],
  "stream": false,
  "temperature": 0.7,
  "max_tokens": 1024,
  "session_id": "optional-session-id"
}
```

**Response:**

```json
{
  "id": "msg_123",
  "type": "message",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "Hello! I'm doing well, thank you for asking. How can I assist you today?"
    }
  ],
  "model": "claude-3-opus-20240229",
  "stop_reason": "end_turn",
  "usage": {
    "input_tokens": 12,
    "output_tokens": 18
  }
}
```

## In-Chat Commands

The LLM Interactive Proxy supports in-chat commands that can be used to control the proxy's behavior. Commands are prefixed with `!/` by default.

### Available Commands

#### Basic Commands
- `!/set(param=value)` - Set a parameter value
- `!/unset(param)` - Unset a parameter value
- `!/help` - Show help information
- `!/pwd` - Show current project directory
- `!/hello` - Test command
- `!/oneoff(backend/model)` or `!/one-off(backend:model)` - Set a one-time override for the backend and model for the next request

#### Failover Route Commands
- `!/create-failover-route(name=<route>,policy=<policy>)` - Create a new failover route with the specified policy
- `!/delete-failover-route(name=<route>)` - Delete a failover route
- `!/list-failover-routes` - List all configured failover routes
- `!/route-list(name=<route>)` - List elements in a failover route
- `!/route-append(name=<route>,element=<backend:model>)` - Append an element to a failover route
- `!/route-prepend(name=<route>,element=<backend:model>)` - Prepend an element to a failover route
- `!/route-clear(name=<route>)` - Clear all elements from a failover route

### Failover Routes

Failover routes allow you to define fallback strategies when a backend or model is unavailable. Each route has a policy and a list of elements.

#### Policies

- `k` - Single backend, all keys: Try all API keys for the first backend:model in the route
- `m` - Multiple backends, first key: Try the first API key for each backend:model in the route
- `km` - All keys for all models: Try all API keys for each backend:model in the route
- `mk` - Round-robin keys across models: Try API keys in a round-robin fashion across all backend:model pairs

#### Examples

```
# Create a failover route with the "k" policy
User: !/create-failover-route(name=my-route,policy=k)
Assistant: Failover route 'my-route' created with policy 'k'

# Add elements to the route
User: !/route-append(name=my-route,element=openai:gpt-4)
Assistant: Element 'openai:gpt-4' appended to failover route 'my-route'

User: !/route-append(name=my-route,element=anthropic:claude-3-opus)
Assistant: Element 'anthropic:claude-3-opus' appended to failover route 'my-route'

# List elements in the route
User: !/route-list(name=my-route)
Assistant: Failover route 'my-route' (policy: k) elements: openai:gpt-4, anthropic:claude-3-opus

# Basic command examples
User: !/set(model=gpt-4)
Assistant: Model set to gpt-4

User: What is the capital of France?
Assistant: The capital of France is Paris.

# One-off command example
User: !/oneoff(anthropic/claude-3-opus)
Assistant: One-off route set to anthropic/claude-3-opus.

User: What is the capital of Germany?
Assistant: The capital of Germany is Berlin.

# Note: The next request will use the default model again

# PWD command example
User: !/pwd
Assistant: /home/user/projects/my-project

# If project directory is not set
User: !/pwd
Assistant: Project directory not set.
```

## Error Handling

Errors are returned as JSON objects with the following structure:

```json
{
  "error": {
    "message": "Error message",
    "type": "error_type",
    "details": {
      "additional": "error details"
    }
  }
}
```

Common error types:

- `authentication_error` - Invalid API key
- `rate_limit_error` - Rate limit exceeded
- `backend_error` - Error from the backend LLM provider
- `validation_error` - Invalid request parameters
- `loop_detected` - Loop detection triggered

## Rate Limiting

Rate limiting is applied based on the client API key. The default limits are:

- 60 requests per minute
- 1000 requests per day

Rate limit headers are included in the response:

```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 59
X-RateLimit-Reset: 1677858302
```
