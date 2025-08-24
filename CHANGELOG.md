# Changelog

This document outlines significant changes and updates to the LLM Interactive Proxy.

## 2025-08-24 – Tool Call Repair and Streaming Safeguards

- Added automated Tool Call Repair mechanism to detect and convert plain-text tool/function call instructions into OpenAI-compatible `tool_calls` in responses.
  - Supports common patterns: inline JSON objects (e.g., `{"function_call":{...}}`), JSON in code fences, and textual forms like `TOOL CALL: name {...}`.
  - Non-streaming responses: repairs are applied before returning to the client; `finish_reason` set to `tool_calls` and conflicting `content` cleared.
  - Streaming responses: introduced a streaming repair processor that accumulates minimal context, detects tool calls, and emits repaired chunks. Trailing free text after a repaired tool call is intentionally not emitted to avoid ambiguity.
- Configuration:
  - `session.tool_call_repair_enabled` (default: `true`)
  - `session.tool_call_repair_buffer_cap_bytes` (default: `65536`)
  - Env vars: `TOOL_CALL_REPAIR_ENABLED`, `TOOL_CALL_REPAIR_BUFFER_CAP_BYTES`
- Safety/performance:
  - Added a per-session buffer cap (default 64 KB) in the repair service to guard against pathological streams and reduce scanning overhead.
  - Optimized detection using fast-path guards and a balanced JSON extractor to avoid heavy regex backtracking on large buffers.

## API Versioning and Deprecation

- **API Versioning**: The API is now versioned using URL path prefixes:
  - `/v1/` - Legacy API (compatible with OpenAI/Anthropic) - **DEPRECATED**
  - `/v2/` - New SOLID architecture API (recommended)
- **Deprecation Notice**: Legacy endpoints (`/v1/*`) are deprecated and will return deprecation headers (`Deprecation: true`, `Sunset: 2023-12-31`). It is recommended to migrate to the `/v2/` endpoints as soon as possible.

## Migration Timeline

- **July 2024**: Legacy endpoints marked as deprecated in code and documentation.
- **September 2024**: Legacy endpoints will begin returning deprecation warnings in headers and responses.
- **October 2024**: Legacy endpoints will log warnings for each use.
- **November 2024**: Legacy code will be completely removed from the codebase.
- **December 2024**: Only the new architecture endpoints will be available.

### Legacy Code Deprecation Timeline

| Component | Deprecation Date | Removal Date |
|---|---|---|
| `src/proxy_logic.py` | July 2024 | November 2024 |
| `src/main.py` endpoints | July 2024 | November 2024 |
| Legacy adapters (`src/core/adapters/`) | July 2024 | October 2024 |
| Feature flags | July 2024 | September 2024 |

## Key Architectural Improvements

### Improved Application Factory

- The application factory has been redesigned following SOLID principles to address critical architectural issues.
- **ApplicationBuilder**: Main orchestrator for the build process.
- **ServiceConfigurator**: Responsible for registering and configuring services in the DI container.
- **MiddlewareConfigurator**: Handles all middleware setup and configuration.
- **RouteConfigurator**: Manages route registration and endpoint configuration.
- Proper service registration with factories for dependencies.
- New `ModelsController` added to handle the `/models` endpoint.
- Separation of concerns into distinct configurator classes.

### Command DI Implementation Fixes

- Implemented a consistent Dependency Injection (DI) architecture for the command system.
- **CommandRegistry**: Enhanced to serve as a bridge between the DI container and the command system, with static methods for global access.
- **CommandParser**: Modified to prioritize DI-registered commands.
- **BaseCommand**: Added `_validate_di_usage()` method to enforce DI instantiation.
- **Centralized Command Registration**: New utility file `src/core/services/command_registration.py` centralizes command registration.
- Enhanced test helpers to work with the DI system.
- Removed duplicate legacy command implementations.
- New DI-based implementation for the OpenAI URL command.

### Dependency Injection Container Fixes

- Ensured `BackendRegistry` is registered as a singleton instance before `BackendFactory`.
- Registered interfaces (`IBackendService`, `IResponseProcessor`) using the same factory functions as their concrete implementations.
- Added explicit registration for controllers (`ChatController`, `AnthropicController`) with proper dependency injection.
- Improved service resolution with `get_required_service_or_default` and enhanced error handling.
- Fixed backend selection and registration, including default backend logic.
- Enhanced test infrastructure with improved fixtures and isolation.
- Fixed ZAI connector URL normalization and model loading.
- Improved command handling regex and updated tests.

## New Features

### Enhanced Empty Response Handling

- Implements automated detection and recovery for empty responses from remote LLMs.
- **Detection Criteria**: HTTP 200 OK, empty/whitespace content, no tool calls.
- **Recovery Mechanism**: Reads recovery prompt from `config/prompts/empty_response_auto_retry_prompt.md`, retries the request, or generates HTTP error if retry fails.
- Configurable via `EMPTY_RESPONSE_HANDLING_ENABLED` and `EMPTY_RESPONSE_MAX_RETRIES` environment variables.

### Tool Call Loop Detection

- Identifies and mitigates repetitive tool calls in LLM responses to prevent infinite loops.
- **Detection Mechanism**: Tracks tool calls, compares similarity, uses time windows.
- **Configuration Options**: `enabled`, `max_repeats`, `ttl_seconds`, `mode` (block, warn, chance_then_block), `similarity_threshold`.
- Supports session-level configuration using `!/set` commands.
- **Interactive Mitigation**: In `chance_then_block` mode, provides guidance to the LLM before blocking.

## Minor Improvements and Fixes

- **HTTP Status Constants**: Introduced `src/core/constants/http_status_constants.py` for standardized HTTP status messages, reducing test fragility and improving maintainability.
- **Test Suite Optimization**: Significant improvements in test suite performance by optimizing fixtures, simplifying mocks, and reducing debug logging.
- **Test Suite Status**: All tests are now passing, with improved test isolation, fixtures, and categorization using pytest markers.
