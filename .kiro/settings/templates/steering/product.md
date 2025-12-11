# Product Overview

**Universal LLM Proxy** - A high-performance traffic routing and management layer for Large Language Model APIs.

## Core Capabilities

1. **Multi-Backend Routing** - Route requests to OpenAI, Anthropic, Gemini, and other LLM providers through a unified API
2. **Intelligent Failover** - Automatic backend switching with circuit breakers and health-aware routing
3. **Traffic Capture & Replay** - CBOR-encoded wire captures for debugging, testing, and traffic analysis
4. **Usage Accounting** - Track token usage, costs, and quotas across all backends
5. **Request Transformation** - Translate between API formats, inject prompts, and apply middleware

## Target Use Cases

- **Development Teams**: Unified LLM integration without vendor lock-in
- **Enterprise Deployments**: Centralized LLM access with rate limiting and accounting
- **AI Agent Platforms**: Reliable backend routing for autonomous agent workloads
- **Testing & Debugging**: Traffic replay and simulation for development

## Value Proposition

- **Vendor Agnostic**: Single integration point for multiple LLM providers
- **Resilient**: Automatic failover and health-aware routing reduce downtime
- **Observable**: Comprehensive logging, wire captures, and usage tracking
- **Extensible**: Plugin architecture for new backends and middleware

---
_Focus on patterns and purpose, not exhaustive feature lists_
