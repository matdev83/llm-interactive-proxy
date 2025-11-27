# User Guide

Welcome to the LLM Interactive Proxy User Guide. This guide provides comprehensive documentation for end-users who want to use and configure the proxy.

## Getting Started

- **[Quick Start Guide](quick-start.md)** - Get up and running in minutes with installation, basic configuration, and first steps
- **[Configuration Guide](configuration.md)** - Learn about configuration methods, precedence, and common scenarios

## Features

Advanced features that enhance the proxy's capabilities:

### Security Features

- **[LLM Assessment System](features/llm-assessment.md)** - Intelligent conversation monitoring that detects unproductive patterns
- **[Angel Verification System](features/angel-verification.md)** - Real-time response verification using a secondary model
- **[Tool Access Control](features/tool-access-control.md)** - Fine-grained control over which tools models can access
- **[Dangerous Command Protection](features/dangerous-command-protection.md)** - Prevent execution of potentially harmful commands
- **[File Access Sandboxing](features/file-access-sandboxing.md)** - Restrict file system access to specific directories

### Model Management

- **[Hybrid Backend](features/hybrid-backend.md)** - Use two models in sequence for reasoning and execution phases (experimental)
- **[Model Name Rewrites](features/model-name-rewrites.md)** - Transform model names dynamically with aliases and patterns
- **[URI Model Parameters](features/uri-model-parameters.md)** - Specify model parameters directly in model name strings
- **[Planning Phase Overrides](features/planning-phase.md)** - Use stronger models for planning phases in coding workflows

### Response Processing

- **[Think Tags Fix](features/think-tags-fix.md)** - Correct improperly formatted thinking tags in model responses
- **[Edit Precision Tuning](features/edit-precision.md)** - Automatically adjust temperature and top_p for code editing tasks

### Development Tools

- **[Pytest Output Compression](features/pytest-compression.md)** - Compress verbose pytest output to save context tokens
- **[Pytest Context Saving](features/pytest-context-saving.md)** - Automatically add helpful pytest flags for better output
- **[Session Management](features/session-management.md)** - Intelligent session handling and state management
- **[Context Window Enforcement](features/context-window-enforcement.md)** - Enforce context window limits and prevent overruns

### Client Integration

- **[Client Identity Override](features/identity-override.md)** - Override client identity headers for compatibility with specific tools

## Backends

Backend provider configuration and usage:

- **[Backend Overview](backends/overview.md)** - Supported backends, choosing a backend, and switching between providers
- **[OpenAI Backend](backends/openai.md)** - OpenAI API and ChatGPT OAuth configuration
- **[Anthropic Backend](backends/anthropic.md)** - Claude API and OAuth configuration
- **[Gemini Backends](backends/gemini.md)** - Google Gemini API, OAuth, and GCP configurations
- **[OpenRouter Backend](backends/openrouter.md)** - OpenRouter multi-model access
- **[ZAI Backend](backends/zai.md)** - Zhipu/Z.ai configuration
- **[Qwen Backend](backends/qwen.md)** - Alibaba Qwen OAuth configuration
- **[Custom Backends](backends/custom-backends.md)** - Creating and configuring custom backend connectors

## Debugging

Tools and techniques for troubleshooting:

- **[Wire Capture](debugging/wire-capture.md)** - Record and analyze HTTP requests and responses
- **[CBOR Capture](debugging/cbor-capture.md)** - Binary wire capture format with simulation capabilities
- **[Troubleshooting Guide](debugging/troubleshooting.md)** - Common issues and solutions

## Security

Authentication and security best practices:

- **[Authentication](security/authentication.md)** - API key authentication and access control
- **[Brute-Force Protection](security/brute-force-protection.md)** - Rate limiting and attack prevention
- **[Key Hygiene](security/key-hygiene.md)** - API key redaction and secure handling

## Additional Resources

- **[Development Guide](../development_guide/index.md)** - For contributors and developers
- **[CHANGELOG](../../CHANGELOG.md)** - Version history and release notes
- **[CONTRIBUTING](../../CONTRIBUTING.md)** - How to contribute to the project
- **[LICENSE](../../LICENSE)** - Project license information

## Getting Help

If you encounter issues or have questions:

1. Check the [Troubleshooting Guide](debugging/troubleshooting.md)
2. Review the relevant feature or backend documentation
3. Search existing [GitHub Issues](https://github.com/matdev83/llm-interactive-proxy/issues)
4. Open a new issue with detailed information about your problem

## Quick Navigation

### By Use Case

- **First-time setup**: Start with [Quick Start Guide](quick-start.md)
- **Production deployment**: Review [Configuration Guide](configuration.md) and [Authentication](security/authentication.md)
- **Debugging issues**: See [Wire Capture](debugging/wire-capture.md) and [Troubleshooting](debugging/troubleshooting.md)
- **Advanced features**: Browse the [Features](#features) section
- **Backend setup**: Check [Backend Overview](backends/overview.md)

### By Role

- **End Users**: Quick Start, Configuration, Features, Backends
- **Security Administrators**: Security section, Tool Access Control, Authentication
- **Developers**: Development Guide, Debugging section, Wire Capture
- **DevOps**: Configuration, Authentication, Troubleshooting
