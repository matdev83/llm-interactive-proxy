# Product Overview

**LLM Interactive Proxy** - A universal gateway for Large Language Model APIs providing intelligent routing, failover, and observability.

## Core Purpose

Acts as a transparent intermediary between LLM clients and backend providers, enabling:
- **Vendor independence**: Single integration point for multiple LLM providers
- **Operational resilience**: Automatic failover and health-aware routing
- **Development productivity**: Traffic capture, replay, and debugging tools
- **Cost management**: Usage tracking, rate limiting, and token accounting

## Core Capabilities

### 1. Multi-Protocol Frontend Support
- **OpenAI Chat Completions** (`/v1/chat/completions`) - Standard OpenAI SDK compatibility
- **OpenAI Responses API** (`/v1/responses`) - Structured output generation
- **Anthropic Messages** (`/anthropic/v1/messages`) - Native Claude support
- **Dedicated Anthropic Server** (`:8001/v1/messages`) - Drop-in Anthropic replacement
- **Google Gemini v1beta** - Native Gemini tools and streaming

### 2. Multi-Backend Routing
- **Major Providers**: OpenAI, Anthropic, Google Gemini, OpenRouter
- **Regional Providers**: ZAI (Zhipu), Qwen (Alibaba), MiniMax (Hailuo)
- **Specialized**: Hybrid (two-phase reasoning), ZenMux (aggregator)
- **OAuth Support**: Gemini OAuth (free/paid tiers), Qwen OAuth, Anthropic OAuth

### 3. Intelligence & Safety
- **Test Execution Reminder**: Automatically reminds agents to run tests (14+ languages)
- **LLM Assessment**: Detects conversation loops and stuck patterns
- **Dangerous Command Protection**: Blocks destructive git operations
- **Tool Access Control**: Fine-grained control over LLM tool permissions
- **File Access Sandboxing**: Restricts file operations to safe directories

### 4. Traffic Management
- **Model Override**: Force applications to use specific models
- **Random Model Replacement**: Probabilistically swap models for resilience
- **API Key Rotation**: Aggregate and auto-rotate keys to maximize free-tier usage
- **Edit Precision Tuning**: Auto-adjust parameters when models struggle

### 5. Observability & Debugging
- **Wire Capture**: CBOR-encoded binary captures of all traffic
- **Usage Tracking**: Token consumption, costs, performance metrics
- **Traffic Replay**: Simulation tools for testing and debugging
- **Structured Logging**: JSON logs with request correlation

### 6. Codebuff WebSocket Server
- Real-time AI communication via WebSocket
- Session management and streaming responses
- File context support for AI agents

## Target Use Cases

- **Development Teams**: Unified LLM integration without vendor lock-in, rapid prototyping
- **Enterprise Deployments**: Centralized access control, cost tracking, rate limiting
- **AI Agent Platforms**: Reliable backend routing with failover for autonomous agents
- **Testing & Debugging**: Traffic replay, simulation, and inspection for development
- **Multi-Cloud Deployments**: Abstract provider differences, maintain consistency

## Value Proposition

- **Vendor Agnostic**: Switch providers without changing client code
- **Resilient**: Automatic failover reduces downtime and improves reliability
- **Observable**: Deep visibility into LLM usage patterns and costs
- **Safe**: Built-in protections against common AI agent mistakes
- **Extensible**: Plugin architecture for custom backends and middleware

## Non-Goals

- **Model Training**: Not an ML training platform
- **Fine-Tuning**: Not a model customization service
- **Data Storage**: Not a long-term conversation database
- **Model Hosting**: Not an inference server (routes to external providers)

---

_Generated: 2025-01-XX_
_Focus on patterns and purpose, not exhaustive feature lists_
