# Changelog

## 2025-09-11 – Enhanced Authentication Reliability with Stale Token Handling

- **Major Enhancement**: Implemented comprehensive stale authentication token handling pattern across all file-backed OAuth backends
  - **Affected Backends**: `gemini-cli-cloud-project`, `gemini-cli-oauth-personal`, `anthropic-oauth`, and `openai-oauth`
  - **Startup Validation**: Enhanced initialization with fail-fast validation pipeline
    - File existence and readability checks
    - JSON structure validation
    - Token/credential field validation
    - Automatic file watching activation
  - **Health Tracking API**: New methods for backend health monitoring
    - `is_backend_functional()`: Returns current backend operational status
    - `get_validation_errors()`: Provides detailed validation error information
  - **Runtime Validation**: Throttled credential validation during API calls
    - Smart validation caching (30-second intervals)
    - Graceful degradation on validation failures
    - Automatic recovery when credentials become valid again
  - **File Watching**: Cross-platform credential file monitoring
    - Real-time detection of credential file changes using `watchdog`
    - Asynchronous credential reloading on file modifications
    - Race condition prevention with pending task tracking
  - **Enhanced Error Handling**: Descriptive HTTP 502 responses for authentication failures
    - Structured error payloads with specific error codes
    - Detailed suggestions for credential resolution
    - Backend-specific error context and troubleshooting hints
  - **Resource Management**: Proper cleanup with `__del__` methods for file watchers
  - **Pattern Compliance**: All implementations follow the standardized pattern documented in `docs/stale_auth_token_handling.md`
- **Testing**: Updated unit tests with proper mocking while maintaining 100% test coverage (2100/2100 tests passing)
- **Code Quality**: All implementations pass `ruff`, `black`, and `mypy` quality checks
- **Backward Compatibility**: No breaking changes to existing functionality or configuration

## 2025-09-10 – Wire Capture Format Unification and Stability

- Unified wire capture handling to consistently use the Buffered JSON Lines format
  - Removed legacy `StructuredWireCapture` service registration from `src/core/di/services.py` to avoid conflicting registrations.
  - `IWireCapture` is now bound exclusively to `BufferedWireCapture` via `CoreServicesStage`.
- Improved `BufferedWireCapture` initialization
  - Background flush task now starts lazily only when an event loop is running, preventing runtime warnings ("coroutine was never awaited") in sync contexts.
  - Capture remains enabled as soon as a file path is configured; background flushing starts on first async use.
- Tests and docs updated
  - Integration tests adjusted to assert the active buffered format semantics.
  - README updated with service registration notes and initialization behavior.

## 2025-09-09 – Dangerous Git Command Prevention (Reactor-based)

- New Feature: Configurable prevention layer that intercepts dangerous git commands issued via local execution tool calls in LLM responses.
  - Implemented as a Tool Call Reactor handler (`dangerous_command_handler`) that runs after JSON and tool-call repair and loop detection, just before forwarding.
  - Swallows matching tool calls and returns an instructive steering message back to the LLM; logs a WARNING with matched rule and command.
  - Comprehensive pattern coverage: hard reset, clean -f (except dry-run), destructive restore/checkout forms, forced switch/checkout, orphan checkout, git rm --force (no --cached), rebase, commit --amend, filter-branch, filter-repo, replace, force/force-with-lease push, remote delete (including legacy `:ref`), push --mirror, local branch/tag deletion, update-ref -d, aggressive reflog expiration, prune/gc/repack/lfs prune, worktree remove/prune, submodule deinit/foreach clean -f.
  - Configurable steering message via `session.dangerous_command_steering_message` or env `DANGEROUS_COMMAND_STEERING_MESSAGE`.
  - Feature flag: `session.dangerous_command_prevention_enabled` (env `DANGEROUS_COMMAND_PREVENTION_ENABLED`, default true).
  - Tests: Extensive unit and integration coverage for detection patterns, argument extraction (raw/JSON/arrays/nested), and DI-driven steering message configuration.

This document outlines significant changes and updates to the LLM Interactive Proxy.

## 2025-09-09 - Header Override Feature

- **New Feature**: Added support for overriding application title, URL, and User-Agent headers
  - **Header Configuration**: Introduced `HeaderConfig` class to encapsulate header configuration with multiple modes (PASSTHROUGH, OVERRIDE, DISABLED)
  - **Flexible Header Handling**: Headers can now be configured to pass through from incoming requests, overridden with specific values, or completely disabled
  - **Backward Compatibility**: Existing configurations continue to work while new override capabilities are available
  - **Per-Backend Identity**: Each backend can now have its own identity configuration for more granular control

## 2025-09-09 - ZAI Coding Plan Backend

- **New Backend**: Added `zai-coding-plan` backend to integrate with the ZAI Coding Plan API.
  - **Inheritance**: Inherits from the `AnthropicBackend` to reuse existing logic.
  - **Custom URL**: Overrides the Anthropic API URL to `https://api.z.ai/api/anthropic`.
  - **Authentication**: Uses the `Authorization` header with a Bearer token for API key authentication.
  - **KiloCode Integration**: Includes proper application identification headers for ZAI server compatibility.
  - **Model Rewriting**: Hardcodes the model name to `claude-sonnet-4-20250514` and rewrites any other model names.
  - **Local Model List**: Serves a hardcoded list of models containing only `claude-sonnet-4-20250514`.
  - **Error Handling**: Correctly surfaces a `BackendError` when the ZAI API returns ZAI-specific error responses.
  - **Testing**: Comprehensive unit and integration tests with real API validation.
  - **Documentation**: Complete setup guide with configuration examples and troubleshooting.

## 2025-09-09 - Context Window Size Overrides

- **New Feature**: Added context window size overrides to enforce per-model context window limits at the proxy level.
  - **Per-Model Overrides**: Add `ModelDefaults.limits` (`ModelLimits`) for per-model overrides.
  - **Input Hard Error**: Enforce an input hard error (`max_input_tokens`).
  - **Structured Error Payload**: Provides a structured error payload with the code `input_limit_exceeded`.
  - **Token Counting Utility**: Includes a token counting utility with `tiktoken` fallback.
  - **Documentation**: Added a new section to the `README.md` file with detailed usage examples and configuration options.

## 2025-09-02 - Content Rewriting

- **New Feature**: Added a content rewriting middleware that allows for the modification of incoming and outgoing messages.
  - **Rule-Based Rewriting**: Rules are defined in the `config/replacements` directory, with support for `prompts/system`, `prompts/user`, and `replies`.
  - **Multiple Rewriting Modes**: Supports `REPLACE`, `PREPEND`, and `APPEND` modes.
  - **Streaming Support**: Correctly handles and rewrites streaming responses.
  - **Sanity Checks**: Ensures that search patterns are at least 8 characters long and that each rule has a unique mode file.
  - **Documentation**: Added a new section to the `README.md` file with detailed usage examples and configuration options.

## 2025-08-31 – Trusted IP Authorization Bypass

- **New Feature**: Added `--trusted-ip` command-line parameter for bypassing API key authentication from specified IP addresses
  - **Multiple IPs Support**: `--trusted-ip` can be specified multiple times to define multiple trusted IP addresses
  - **Security-First Design**: Only bypasses authentication when `--disable-auth` is not set (authentication remains enabled)
  - **CIDR Support**: Supports IP ranges using CIDR notation (e.g., `10.0.0.0/8`, `192.168.0.0/16`)
  - **Audit Logging**: Logs when authentication is bypassed for trusted IPs for security monitoring
  - **Flexible Configuration**: Works with both CLI parameters and YAML configuration files
  - **Use Cases**: Ideal for internal networks, load balancers, reverse proxies, CI/CD pipelines, and development environments
- **Configuration Options**:
  - CLI: `--trusted-ip 192.168.1.100 --trusted-ip 10.0.0.0/8`
  - YAML: `auth.trusted_ips: ["192.168.1.100", "10.0.0.0/8"]`
  - Environment: Can be configured through environment variables if needed
- **Implementation Details**:
  - Added `trusted_ips` field to `AuthConfig` class in `src/core/config/app_config.py`
  - Extended `APIKeyMiddleware` to check client IP against trusted IPs list before authentication
  - Updated middleware configuration to pass trusted IPs to the authentication middleware
  - Added comprehensive test coverage for trusted IP bypass functionality
- **Documentation**: Updated README.md with detailed usage examples, configuration options, and security considerations
- **Backward Compatibility**: No impact on existing functionality; feature is opt-in and secure by default

## 2025-08-31 – Anthropic OAuth Backend

- New backend: `anthropic-oauth` for using Anthropic without configuring API keys in the proxy.
  - Reads a local OAuth-style credential file `oauth_creds.json` (e.g., from Claude Code) and uses its `access_token`/`api_key` as `x-api-key`.
  - Default search paths: `~/.anthropic`, `~/.claude`, `~/.config/claude`, and on Windows `%APPDATA%/Claude`.
  - Optional `anthropic_oauth_path` to point at a specific directory containing `oauth_creds.json`.
  - Optional `anthropic_api_base_url` to override the default `https://api.anthropic.com/v1`.
  - Can be set as the default backend via `LLM_BACKEND=anthropic-oauth` or `backends.default_backend`.
  - Documentation added under README “Anthropic OAuth Backend”.

## 2025-08-31 – OpenAI OAuth Backend

- New backend: `openai-oauth` for using OpenAI without storing API keys in proxy config.
  - Reads Codex CLI `auth.json` (ChatGPT login) and uses `tokens.access_token` as bearer; falls back to `OPENAI_API_KEY` if present.
  - Default search paths: `~/.codex/auth.json` and on Windows `%USERPROFILE%/.codex/auth.json`.
  - Optional `openai_oauth_path` to point at a specific directory containing `auth.json`.
  - Optional `openai_api_base_url` to override the default `https://api.openai.com/v1` (env `OPENAI_BASE_URL` can also be used in some environments).
  - Can be selected via `LLM_BACKEND=openai-oauth` or per-request model prefix `openai-oauth:<model>`.
  - Documentation added under README “OpenAI OAuth Backend”.

## 2025-08-29 – Automated Edit-Precision Tuning

- New feature: Automatically tune model sampling parameters after failed file-edit attempts from popular coding agents.
  - Request-side detection: scans incoming user/agent prompts for known failure phrases (SEARCH/REPLACE no match, multiple matches, unified-diff hunk failures, fuzzy patch warnings).
  - Response-side detection: middleware inspects non-streaming responses and streaming chunks for markers like `diff_error` and hunk failures; flags a one-shot tune for the next request.
  - Single-call override: applies lowered `temperature` and optionally `top_p` to just the next backend call; then resets.
  - Configurable via `AppConfig.edit_precision` and environment variables: `EDIT_PRECISION_ENABLED`, `EDIT_PRECISION_TEMPERATURE`, `EDIT_PRECISION_OVERRIDE_TOP_P`, `EDIT_PRECISION_MIN_TOP_P`, `EDIT_PRECISION_EXCLUDE_AGENTS_REGEX`, `EDIT_PRECISION_PATTERNS_PATH`.
  - Patterns externalized at `conf/edit_precision_patterns.yaml`.
  - Documentation: README section "Automated Edit-Precision Tuning (new)" and `dev/agents-edit-error-prompts.md` with curated failure prompts from Cline, Roo/Kilo, Gemini-CLI, Aider, Crush, OpenCode.
  - Tests: request-side overrides, exclusion regex, response/streaming detection pending flag, and pending-flag application on the next request.

## 2025-08-28 – Tool Call Reactor - Event-Driven Agent Steering

- **New Feature**: Added Tool Call Reactor system for event-driven agent steering functionality
  - **Event-Driven Architecture**: Pluggable code to react to tool calls from remote LLMs with custom handlers
  - **Handler Types**: Support for both passive event receivers and active handlers that can swallow and replace LLM responses
  - **Built-in ApplyDiff Handler**: Automatically steers LLMs from `apply_diff` to `patch_file` tool usage with configurable rate limiting
  - **Rate Limiting**: Per-session rate limiting to prevent excessive steering messages (default: once per 60 seconds)
  - **Session Information**: Handlers receive full context including session ID, backend name, model name, tool call details, and calling agent
  - **Middleware Integration**: Properly positioned in response processing pipeline after JSON repair and tool call repair
  - **Configuration**: Environment variables `TOOL_CALL_REACTOR_ENABLED`, `APPLY_DIFF_STEERING_ENABLED`, `APPLY_DIFF_STEERING_RATE_LIMIT_SECONDS`
  - **Architecture**: Follows SOLID principles with dependency injection, interfaces, and proper separation of concerns
  - **Testing**: Comprehensive test suite with 52 tests covering all functionality including unit tests, integration tests, and edge cases
  - **Documentation**: Complete feature documentation in README with configuration examples and usage patterns

## 2025-08-28 – JSON Repair Centralization, Strict Gating, and Loop/Tool-Call Ordering

- Centralized JSON repair across the codebase:
  - Streaming: `JsonRepairProcessor` in the pipeline; buffers and repairs complete JSON blocks; uses `json_repair` library with optional schema validation.
  - Non-streaming: `JsonRepairMiddleware` applied through `MiddlewareApplicationProcessor`.
- Strict gating for non-streaming repairs:
  - Strict when any of: global strict flag, Content-Type is `application/json`, `expected_json=True` in context, or a schema is configured.
  - Otherwise best-effort; failures do not raise and original content is preserved.
- Convenience helpers for controllers/adapters:
  - `src/core/utils/json_intent.py#set_expected_json(metadata, True)` to opt-in strict mode per route.
  - `#infer_expected_json(metadata, content)`; ResponseProcessor auto-inferrs and sets `expected_json` if not present.
- Streaming processor order updated:
  - JSON repair → text loop detection → tool-call repair → middleware → accumulation.
  - Cancellation flags are preserved across processors.
- Tool-call loop detection:
  - Middleware detects 4 consecutive identical tool calls; in `CHANCE_THEN_BREAK` mode emits guidance once, then breaks on the next identical call.
- Metrics (in-memory) added:
  - `json_repair.streaming.[strict|best_effort]_{success|fail}`
  - `json_repair.non_streaming.[strict|best_effort]_{success|fail}`
- Documentation updated, and a comprehensive test suite added for:
  - Strict gating (expected_json flag, Content-Type)
  - Streaming order and cancellation vs tool-call conversion
  - Tool-call loop detection break/chance flows

## 2025-08-28 – API Key Redaction Restored and Documented

- Restored API key redaction in outbound requests across all backends via a centralized request redaction middleware. Secrets found in user message content (including multimodal text parts) are replaced with `(API_KEY_HAS_BEEN_REDACTED)` and proxy commands are stripped before forwarding to providers.
- Confirmed and documented global logging redaction filter that masks API keys and bearer tokens in all logs.
- Added focused tests to prevent regressions:
  - Unit tests for `RedactionMiddleware` and `RequestProcessor` redaction behavior (including feature-flag off).
  - Integration tests covering both streaming and non-streaming flows with a fake backend capturing the sanitized payload.
- Updated README and CONTRIBUTING with redaction details and contributor guidance.
- Configuration: redaction can be disabled via `auth.redact_api_keys_in_prompts = false` or CLI `--disable-redact-api-keys-in-prompts`.

## 2025-08-26 – Gemini CLI Cloud Project Backend

- **New Feature**: Added `gemini-cli-cloud-project` backend for enterprise-grade integration with Google Cloud Platform
  - **GCP Project Integration**: Uses user-specified Google Cloud Project ID for billing and quota management
  - **Standard/Enterprise Tier**: Supports standard-tier and enterprise-tier subscriptions (not free-tier)
  - **OAuth + Project ID**: Combines OAuth 2.0 authentication with GCP project context
  - **Billing Control**: All API usage is billed directly to the user's GCP project
  - **Higher Quotas**: Access to project-defined quotas and limits, not limited by free-tier restrictions
  - **Enterprise Features**: Full access to Code Assist API features for production deployments
  - **IAM Integration**: Requires proper IAM permissions (`roles/cloudaicompanion.user`)
  - **Project Validation**: Validates project access, API enablement, and billing during initialization
  - **Automatic Onboarding**: Handles project onboarding to standard-tier automatically
  - **Configuration**: Supports environment variables (`GCP_PROJECT_ID`) or explicit configuration
  - **Testing**: Comprehensive test suite covering project validation, onboarding, and billing context
  - **Documentation**: Complete setup guide with GCP project requirements and troubleshooting

## 2025-08-26 – Gemini CLI OAuth Personal Backend

- **New Feature**: Added `gemini-cli-oauth-personal` backend for seamless integration with Google's Gemini API using OAuth 2.0 credentials
  - **OAuth Integration**: Reads OAuth credentials from `~/.gemini/oauth_creds.json` (created by Gemini CLI tool)
  - **Automatic Token Refresh**: Handles OAuth token expiration automatically using Google's token refresh endpoint
  - **Health Checks**: Performs lightweight connectivity and authentication validation on first use
  - **Cross-Platform Support**: Works on Windows, Linux, and macOS with proper path handling
  - **Error Handling**: Comprehensive error handling for authentication failures, connectivity issues, and token refresh problems
  - **Testing**: Complete test suite with 28 tests covering all functionality including health checks, token refresh, and error scenarios
  - **Configuration**: Simple backend configuration requiring only `gemini_api_base_url` parameter
  - **Usage**: Supports all standard proxy features including interactive commands (`!/backend(gemini-cli-oauth-personal)`, `!/oneoff(gemini-cli-oauth-personal:gemini-pro)`)

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

### Empty Response Recovery

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
