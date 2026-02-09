# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

### Removed

- **Gemini ACP Connector**: Removed `gemini-cli-acp` backend connector due to problematic implementation and poor fit with project architecture. All related code, tests, configuration, and documentation have been removed. The connector is no longer available in the backend registry.

### Added

- **Model Registry**: Implemented automated LLM model catalog registry and limit enforcement. This includes `ModelCatalogService` for metadata discovery, `ModelCatalogUpdater` for periodic background updates from models.dev, and automated enforcement of context window/token limits in `BackendPreparer` when local configuration is missing.
- **Model Registry**: Added input modality validation (image/audio) when registry data provides `modalities` for a model; skipped when registry or model metadata is missing.
- **Notification Service**: Implemented a SOLID-based desktop notification system with provider-based architecture. This includes `NotificationService` for coordination and `DesktopNotifierProvider` as a pluggable delivery mechanism.
- **Gemini OAuth Auto**: Implemented `random` and `first-available` selection strategies for multi-account rotation.
- **Gemini OAuth Auto**: Added `last_used` usage tracking for registered accounts.
- **Gemini OAuth Auto**: Added `show` command to `manage_gemini_accounts.py` for detailed account inspection.
- **Access Modes**: Introduced Single User Mode (default) and Multi User Mode for explicit security boundary enforcement. Single User Mode allows OAuth connectors and optional auth for localhost development. Multi User Mode blocks OAuth connectors, requires authentication for non-localhost binding, and rejects desktop notifications. New CLI flags: `--single-user-mode`, `--multi-user-mode`. Backward compatible (defaults to Single User Mode). See [Access Modes User Guide](docs/user_guide/access-modes.md).
- OpenAI Codex enthusiast mode configuration for third-party agents (Factory Droid, OpenCode, etc.)

- New configuration profiles for Chat Completions and Responses API clients
- Per-request capability overrides via extra_body parameter
- Lazy discovery mechanism for strategy registry to avoid circular imports
- **B2BUA Session Handling**: Comprehensive identity contract and boundary rules for A-leg/B-leg session handling with typed identity containers and connector-safe diagnostics
- Implemented non-forwardable message tagging system with configuration and domain models
- Implemented Kiro spec archiving system with documentation updates
- Added archive functionality and allowlist for completed specifications
- Added test execution reminder functionality
- Implemented vendor model dynamic routing capabilities
- Added SSO authentication integration
- Added random model replacement feature with DI wiring, configuration options, and metrics docs
- **Context Compaction**: Max tokens overflow warnings (Req 3.2) - operators now receive warnings when compaction cannot reduce tokens below configured maximum, enabling proactive capacity planning
- **Context Compaction**: Metrics export via structured logging (Req 4.1) - all compaction operations now emit detailed metrics for observability, including messages compacted, bytes saved, and estimated token savings
- **Context Compaction**: Configurable resource identifier redaction (Req 4.5) - optional redaction of file paths and commands in compaction stubs for security-sensitive environments (default: OFF for debuggability)
- **Documentation**: Comprehensive user guide for context compaction feature with configuration examples, troubleshooting, and best practices
- Implemented typed contracts boundary hardening with enhanced validation and error handling
- Enhanced non-forwardable message handling with improved security and reliability measures

### Changed

- Improved error handling for "Instructions are not valid" errors in OpenAI Codex connector with actionable messages
- **Gemini OAuth / Antigravity OAuth**: Align Code Assist request preparation with gemini-cli by stripping `reasoning_content` by default, adding `session_id`, and supporting optional tool output truncation that is auto-skipped when history compaction is enabled (with configurable log level).
- **Model Registry**: Graceful degradation for context and modality enforcement when registry data is missing/unparsable or the model is absent.
- Enhanced prompt handling with robust fallbacks and codex_default enforcement
- Updated OpenAI Codex documentation with detailed configuration examples
- Improved type safety in ToolArgumentsParser with proper TelemetryRecorder typing
- Added race condition prevention with sequential execution for mypy validation tests
- Enhanced test coverage for tool call deduplicator and stream buffer adapter
- Refactored backend completion flow with improved availability checking
- Enhanced resilience layer architecture with better error handling
- Fixed concurrency issues in usage accounting and streaming metrics
- Updated configuration schemas and documentation
- **Gemini OAuth Auto**: Refactored account blocking notifications to use the new centralized SOLID notification service.
- Cleaned up completed specifications by moving to archive directory

- **Context Compaction**: Enhanced logging to include both observability context and metrics in structured format

### Fixed

- Fixed circular import issues in strategy registry initialization
- **Context Compaction**: Completed all P1 observability and safety requirements per specification
- **Tests**: Fixed redaction test API key patterns to match expected regex format
- **Tool Execution**: Improved logging safety by using isEnabledFor checks before logging debug messages
- **Streaming Handler**: Refactored retry state management with dedicated RetryState dataclass for better type safety
- **Wire Capture**: Made file rotation methods async to properly handle I/O operations in async context
- **Boundary Validation**: Added boundary validation service with enhanced validation and error handling for connector communications
- **Typing**: Added explicit async iterator/receive type annotations in content rewriting middleware to satisfy mypy checks

### Changed

- **Backend Refactoring**: Refactored backend stage with improved validation services and connector strategies
- **Dependency Injection**: Enhanced DI container with improved provider lifecycle management and post-build actions
- **Validation Services**: Added backend validation service with HTTP client manager for improved backend initialization
- **Application Builder**: Enhanced application builder with improved validation lifecycle and backend factory integration
