# Frontend APIs Overview

The LLM Interactive Proxy exposes multiple **frontend APIs** that clients can use to communicate with the proxy. Each frontend implements a different LLM provider's API specification, allowing clients built for specific providers to seamlessly use the proxy.

## What are Frontends?

**Frontends** are the API endpoints where clients connect to the proxy. They accept requests in a specific format (e.g., OpenAI, Anthropic, Gemini) and return responses in that same format.

**Backends** are the connectors the proxy uses to communicate with actual LLM providers. The proxy translates requests from any frontend to any backend, enabling protocol-agnostic routing.

```
┌─────────────────┐      ┌─────────────────────────────────────┐      ┌─────────────────┐
│  OpenAI Client  │──────│                                     │──────│   OpenAI API    │
├─────────────────┤      │                                     │      ├─────────────────┤
│ Anthropic Client│──────│     LLM Interactive Proxy           │──────│  Anthropic API  │
├─────────────────┤      │                                     │      ├─────────────────┤
│  Gemini Client  │──────│  Frontend  ──►  Core  ──►  Backend  │──────│   Gemini API    │
├─────────────────┤      │                                     │      ├─────────────────┤
│   Any Client    │──────│                                     │──────│  OpenRouter...  │
└─────────────────┘      └─────────────────────────────────────┘      └─────────────────┘
     FRONTENDS                      PROXY                              BACKENDS
```

## Supported Frontend APIs

The proxy supports four frontend API types:

| Frontend | Endpoints | Documentation |
|----------|-----------|---------------|
| OpenAI Chat Completions | `/v1/chat/completions`, `/v1/models` | [OpenAI Chat Completions](openai-chat-completions.md) |
| OpenAI Responses API | `/v1/responses` | [OpenAI Responses API](openai-responses.md) |
| Anthropic Messages | `/anthropic/v1/messages`, `/v1/messages` (dedicated port) | [Anthropic API](anthropic.md) |
| Google Gemini v1beta | `/v1beta/models`, `:generateContent`, `:streamGenerateContent` | [Gemini API](gemini.md) |

## Frontend-Backend Compatibility

Any frontend can route requests to any backend. The proxy handles all necessary protocol translation:

| Frontend | Can Route To |
|----------|--------------|
| OpenAI Chat Completions | All backends |
| OpenAI Responses API | All backends (with automatic translation) |
| Anthropic Messages | All backends |
| Gemini v1beta | All backends |

## Choosing a Frontend

Choose a frontend based on your client's native API:

- **OpenAI SDKs, Cursor, most coding agents**: Use [OpenAI Chat Completions](openai-chat-completions.md)
- **Structured JSON output with schema validation**: Use [OpenAI Responses API](openai-responses.md)
- **Claude Code, Anthropic SDK**: Use [Anthropic API](anthropic.md)
- **Gemini-compatible tools**: Use [Gemini API](gemini.md)

## Common Configuration

All frontends share common proxy features:

- **Authentication**: API key validation (see [Authentication](../security/authentication.md))
- **Session Management**: Automatic session tracking (see [Session Management](../features/session-management.md))
- **Wire Capture**: Request/response logging (see [Wire Capture](../debugging/wire-capture.md))
- **In-Chat Commands**: Dynamic configuration via `!/` commands

## Related Documentation

- [Backend Overview](../backends/overview.md) - Configure which LLM providers the proxy connects to
- [Architecture](../../development_guide/architecture.md) - Technical details of frontend/backend separation
- [Quick Start](../quick-start.md) - Get started with the proxy

