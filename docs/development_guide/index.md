# Development Guide Index

Welcome to the LLM Interactive Proxy development guide. This section contains documentation for developers who want to understand, contribute to, or extend the codebase.

## Architecture & Design

- **[Architecture](./architecture.md)** - System architecture, design patterns, and component overview
- **[Code Organization](./code-organization.md)** - Directory structure, module organization, and key components
- **[Typed Data Contracts](./typed-data-contracts.md)** - Canonical contracts and boundary conversion points for cross-layer data exchange
- **[Typed Contract Boundaries](./typed-contracts-boundaries.md)** - Strategy for hardening cross-layer data exchange using canonical typed contracts
- **[Routing Selectors](./routing-selectors.md)** - Composite selector grammar, failover, weighted routing, and parameter rules
- **[God Objects Report](./god-objects-report.md)** - Snapshot report of oversized modules/classes
- **[VTC Architecture](./vtc-architecture.md)** - Virtual Tool Calling subsystem for Cline-like clients
- **[Critical Fixes (2026-01-25)](./2026-01-25-critical-fixes.md)** - Report on critical stability fixes implemented on 2026-01-25

## Building & Setup

- **[Building](./building.md)** - Installation, dependency management, and virtual environment setup
- **[Testing](./testing.md)** - Test execution, test organization, and testing best practices

## Development Workflows

- **[Contributing](./contributing.md)** - Contribution guidelines, pull request process, and code review standards
- **[Adding Features](./adding-features.md)** - Guide for implementing new features in the proxy
- **[Adding Backends](./adding-backends.md)** - Guide for creating new backend connectors
- **[Plugin API](./plugin-api.md)** - Supported contract for entry-point backend plugins

## Integration Guides

- **[Usage Tracking Integration](../../docs/usage-tracking-integration.md)** - Integrate usage tracking into custom controllers and middleware

## Debugging & Troubleshooting

- **[Debugging](./debugging.md)** - Debugging techniques, wire capture analysis, and troubleshooting tools
- **[Zombie Request Fix](./zombie-request-fix.md)** - Fix for zombie request handling issues

## Related Documentation

- [AGENTS.md](../../dev/AGENTS.md) - Coding standards and development guidelines
- [CONTRIBUTING.md](../../dev/CONTRIBUTING.md) - Project contribution guidelines
- [CHANGELOG.md](../../dev/CHANGELOG.md) - Project changelog with version history
- [User Guide](../user_guide/index.md) - Documentation for end-users

## Quick Links

- [Project Repository](https://github.com/matdev83/llm-interactive-proxy)
- [Issue Tracker](https://github.com/matdev83/llm-interactive-proxy/issues)
