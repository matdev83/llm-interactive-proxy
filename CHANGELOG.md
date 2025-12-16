# Changelog

## [Unreleased]

### Added

- **Binary File Edit Steering Policy**: Implemented comprehensive binary file edit steering functionality
  - **New Policy**: Added `BinaryFileEditPolicy` to handle binary file operations safely
  - **Configuration Support**: Added configuration options for binary file editing in app settings
  - **CLI Integration**: Extended CLI argument parser to support binary file edit options
  - **Unified Handler**: Updated unified steering handler to support binary file edit operations
  - **Test Coverage**: Added comprehensive unit and integration tests for binary file edit functionality
  - **Environment Configuration**: Updated sample environment configuration with binary file edit settings

- **Phase 5 Completion Report**: Documented completion of backend service god object refactoring verification
  - **Quality Achievement**: Recorded 98.9% test pass rate (9,493 passing / 5 failing / 171 skipped)
  - **Metrics Success**: Verified complexity reduction (Max CC: 10 vs target ≤25) and maintainability improvement (MI: 47.35 vs target ≥20)
  - **Work Completed**: Detailed quick wins, equivalence tests refactoring, failover test migration, and integration test fixes
  - **Achievement Highlights**: Documented 41 tests fixed (89% reduction in failures) and comprehensive failover planner test coverage

### Changed

- **Enhanced Service Registration**: Improved dependency injection system with additional interfaces and services
  - **New Interfaces**: Added core interfaces (`IBackendExecutor`, `IBackendPreparer`, `ICommandHandler`, `IRequestSideEffects`, `IRequestTransformPipeline`, `ISessionEnricher`) for better service decomposition
  - **Service Integration**: Integrated new services into request processing pipeline for enhanced functionality
  - **Test Improvements**: Updated integration tests to reflect new service architecture with proper message handling

### Refactored

- **Backend Completion Flow Architecture**: Major refactoring to extract backend completion logic into dedicated modular services
  - **New Module**: Created `backend_completion_flow` module with focused services (`BackendManager`, `FailoverManager`, `RequestPreparer`, `ResponseHandler`, etc.)
  - **Architecture Improvement**: Separated concerns by moving backend completion responsibilities from monolithic `BackendService` to specialized components
  - **Maintainability**: Improved code organization and testability through modular design
  - **Specification**: Added comprehensive architecture specifications in `.kiro/specs/backend-completion-flow-architecture-refactoring/`
  - **Test Coverage**: Updated test suites to validate new modular architecture

## [2025-12-14]

### Added

- **Improved Streaming Error Handling**: Enhanced error handling for streaming requests with proper SSE error envelope generation when backend calls fail during streaming
  - **SSE Error Envelopes**: New `_as_sse_error()` function to generate proper streaming error responses for failed backend calls
  - **Streaming Error Capture**: Best-effort wire capture of error payloads for debugging when backend calls fail before streaming begins
  - **New Test Coverage**: Added `test_backend_service_streaming_error_envelope.py` to verify streaming error response behavior

- **Enhanced Rate Limit Handling**: Improved rate limit handling with better retry-after header processing and error payload enrichment
  - **Retry-After Processing**: Automatic extraction and inclusion of retry-after headers in error responses when available
  - **Header Capture**: Included full response headers in error payloads for better debugging
  - **New Test Coverage**: Added `test_backend_service_streaming_rate_limit_retry.py` to verify rate limit retry behavior with streaming requests

### Changed

- **Better Error Logging**: Enhanced error logging in Gemini connectors with more detailed status codes and error information
  - **Detailed Error Information**: Error logs now include status codes and error codes alongside the original error message
  - **Improved Debugging**: More context in error messages for troubleshooting backend API call failures

### Refactored

- **Backend Service Refactoring**: Major refactoring of BackendService to extract functionality into dedicated services
  - **Method Extraction**: Moved methods to dedicated services (_apply_model_aliases → ModelAliasResolver, _stream_as_sse_bytes → StreamFormattingService, _wrap_stream_for_usage → UsageTrackingWrapper, etc.)
  - **Backend Lifecycle Management**: Improved backend lifecycle management with BackendLifecycleManager handling backend creation, caching, and shutdown
  - **Service Integration**: Updated BackendService to delegate to specialized services instead of implementing functionality internally
  - **Test Updates**: Updated unit tests to reflect new service architecture with appropriate mocking of extracted services
  - **Completion**: Marked backend service refactoring as completed in project specifications

### Added

- **Prompt Caching Support**: Implemented comprehensive support for prompt caching features across major providers
  - **Anthropic Support**: Full support for Anthropic's prompt caching via `anthropic-beta: prompt-caching-2024-07-31` header and `cache_control` content blocks
  - **Request Preservation**: Updated request models and converters to preserve `cache_control` markers in message content instead of flattening them
  - **Beta Header Handling**: Automatically extracts and forwards `anthropic-beta` headers from client requests
  - **Gemini/OpenAI Compatibility**: Validated support for Gemini's explicit/implicit caching and OpenAI's automatic prefix caching mechanisms via existing passthrough logic
  - **Test Coverage**: Added unit tests for converter logic, controller header handling, and domain serialization to ensure robustness

### Changed

- **Project Documentation**: Updated project steering documents with condensed, high-signal information
  - **Structure Guide**: Simplified architecture overview focusing on key directories and change locations
  - **Tech Stack**: Streamlined technology stack documentation with canonical commands and patterns
  - **Product Overview**: Condensed product features with links to detailed documentation

## [2025-12-13]

### Refactored

- **Cross-API Translation Refactoring**: Major refactoring of cross-API translation system with updated specifications in `.kiro/specs/cross-api-translation-refactoring/tasks.md`
- **CLI Architecture**: Refactored CLI components with updates to `cli.py` and removal of deprecated `cli_v2.py`
- **Translation Infrastructure**: Improved translation service architecture with enhanced translators for Anthropic and Gemini APIs
- **Server Lifecycle Management**: Enhanced server lifecycle management with improvements to the lifecycle manager

### Added

- **Translation System Documentation**: New documentation for the translation system at `docs/development_guide/translation-system.md`
- **Comprehensive Testing**: Added extensive test coverage for translation functionality including validation of default translator factories, API shape backward compatibility, and converter module delegation

### Changed

- **Development Guides**: Updated development documentation in `docs/development_guide/` to reflect new translation system architecture
- **Core Module Structure**: Modified core module initialization and imports to align with new translation architecture

## [2025-12-12]

### Added

- **OpenAI Responses API Translator**: Implemented comprehensive Responses API translation support
  - **ResponsesTranslator**: New `ResponsesTranslator` class implementing `BaseFormatTranslator` and `StreamingTranslatorMixin`
  - **Translation Modules**: Complete request, response, and streaming translation modules in `src/core/domain/translators/responses/`
  - **Test Coverage**: Comprehensive tests in `test_responses_translator_phase9.py` with facade verification
  - **Format Support**: Full support for OpenAI Responses API format including structured output and JSON schema handling

- **OpenRouter Translator**: Implemented `OpenRouterTranslator` with comprehensive request/response/streaming translation
- **Raw Text Translator**: Implemented `RawTextTranslator` for pass-through text support
- **Code Assist Translator**: Implemented `CodeAssistTranslator` for specialized code assistance features
- **CLI Refactoring Implementation**: Implemented `ArgumentParserBuilder` and `CliArgsValidator` to decouple CLI logic from the main entry point

- **CLI Refactoring Specs**: Added initial specifications for CLI God Object refactoring in `.kiro/specs/cli-god-object-refactoring/`.
- **Code Analysis Tools**: Added `scripts/analyze_codebase.py` for cyclomatic complexity and maintainability index analysis, and `GOD_OBJECTS_REPORT.md` baseline.
- **Usage Scripts**: Added ad-hoc analysis scripts `scripts/count_claude_opus_requests.py` and `scripts/list_models.py`.
- **Developer Tool Exemptions**: Intelligent exemption system for safe developer tools in dangerous command protection
  - **Smart Detection**: Automatically exempts common safe tools (linters, formatters, test runners) from dangerous command blocks
  - **Tool Support**: Includes Python (ruff, black, mypy), JS/TS (eslint, prettier), Rust (cargo), Go, and more
  - **Safe Workflows**: Allows `ruff --fix`, `cargo fmt`, and other non-destructive file modifications without interruption
  - **Documentation**: Added comprehensive guide in `docs/user_guide/features/dangerous-command-protection-dev-tools.md`

- **Session Sanitizer**: New `SessionSanitizer` service to ensure session data integrity and security
  - **Sanitization Logic**: Implemented `session_sanitizer.py` to clean and normalize session data
  - **Unit Tests**: Added comprehensive tests in `test_session_sanitizer.py`

- **Gemini Translator**: Implemented `GeminiTranslator` and related components to support the new translation infrastructure
  - **Translator Implementation**: Added `GeminiTranslator` class implementing `BaseFormatTranslator` and `StreamingTranslatorMixin`
  - **Request/Response Mapping**: Implemented comprehensive mapping logic in `gemini/request.py` and `gemini/response.py`
  - **Streaming Support**: Added streaming translation support in `gemini/streaming.py`
  - **Unit Tests**: Added `test_gemini_translator_phase8.py` to verify translator behavior against the facade

### Refactored

- **Cross-API Translation Specs**: Updated refactoring specifications in `.kiro/specs/cross-api-translation-refactoring/` with refined design, requirements, and tasks.
- **Translation Domain**: Extracted translation utilities into `src/core/domain/translation_utils/` and refactored `Translation` class to use them.
- **Translation Infrastructure**: Implemented `TranslatorRegistry`, `TranslatorProtocol`, and dedicated `OpenAITranslator` / `AnthropicTranslator` classes to decouple translation logic from the core service.
- **Backend Service Specs**: Updated refactoring specifications in `.kiro/specs/backend-service-refactoring/` with detailed design, requirements, and tasks.
- **Gemini Connector Architecture**: Major refactoring of the Gemini connector to improve maintainability and extensibility
  - **Modular Components**: Split monolithic logic into focused modules: `orchestrator.py` for request orchestration, `policies.py` for retry/error policies, and `backend_compatibility.py` for API compatibility handling
  - **Streaming Executor**: Enhanced `StreamingExecutor` for more robust stream handling and error recovery
  - **Thought Signature Management**: Improved `ThoughtSignatureManager` and `ThoughtSignatureService` for better persistence and retrieval of thought signatures

### Changed

- **Documentation Structure**: Moved `GOD_OBJECTS_REPORT.md` to `docs/development_guide/god-objects-report.md`.
- **Usage Tracking Metrics**: Expanded usage tracking with granular performance and traffic metrics
  - **New Metrics**: Added `stream_tps` (tokens per second), `backend_wait_ms`, and split tool call counts (`native` vs `vtc`)
  - **Instance Tracking**: Added `backend_instance_id` to usage records for tracking specific backend instances
  - **Database Optimization**: Added new indexes for backend instance and model performance analysis

- **Spec Cleanup**: Removed obsolete test suite fix specifications from `.kiro/specs/test-suite-fixes/`
- **Test Suite Updates**: Updated property tests and unit tests to align with new architecture and services

## [2025-12-11]

### Added

- **Detailed Usage Tracking System**: Replaced legacy implementation with a comprehensive tracking system
  - **4-Leg Traffic Tracking**: Records token metrics at four distinct points (client-proxy request, proxy-backend request, backend-proxy response, proxy-client response)
  - **Verbatim vs Mutated**: Tracks both original (verbatim) and modified (mutated) token counts to measure proxy impact
  - **SQLModel Persistence**: Replaced in-memory repository with SQLModel-based `UsageRecordRepository` for reliable persistence
  - **Hot Path Integration**: Deeply integrated into `BackendService` to capture metrics during request processing and streaming
  - **API Updates**: Updated `UsageController` to return granular `UsageRecord` and `AggregatedStats` domain objects
  - **Legacy Cleanup**: Removed outdated `UsageData` model and `InMemoryUsageRepository`

- **401 Authentication Retry with Token Refresh**: Transparent recovery from expired OAuth tokens in Gemini OAuth connectors
  - **Automatic Retry**: When a 401 Unauthorized is received from the Gemini backend, the proxy now automatically attempts to refresh the OAuth token and retries the request
  - **Timeout Protection**: Token refresh has a 30-second timeout to prevent indefinite client waiting
  - **Single Retry**: Uses `_auth_retry_attempted` flag to prevent infinite retry loops
  - **Both Paths Covered**: Implemented for both streaming and non-streaming requests
  - **Comprehensive Logging**: INFO-level logs for retry attempts and outcomes
  - **Unit Tests**: 18 new unit tests in `test_gemini_oauth_auth_retry.py`
  - **Behavioral Tests**: 12 new behavioral tests in `test_gemini_oauth_auth_retry_behavior.py`

- **CBOR Documentation**: Comprehensive guide for CBOR wire capture in `docs/user_guide/debugging/cbor-capture.md`

- New Gemini connector modules: `generation_config_builder.py`, `model_validation.py`, `response_accumulator.py`, `response_text_extractor.py`, `retry_delay_parser.py`, `thought_signature_manager.py`, `user_prompt_id_generator.py`
- Database schema and usage tracking documentation in `docs/database-*.md`

### Fixed

- **Gemini Streaming**: Fixed retry logic syntax in `streaming_executor.py` to correctly check sleep time.
- **Gemini Auth Retry**: Force credential reload on 401 retry to ensure fresh tokens are used
- **Gemini Rate Limits**: Implemented automatic retry for rate limit errors with `retry-after` header support in `GeminiOAuthBaseConnector`
- **Thought Signatures**: Added secondary index by tool call ID to `ThoughtSignatureManager` to persist signatures across session ID changes
- Extensive fixes in debugging scripts for streaming, tool calls, CBOR, and Gemini issues
- Gemini connector refactoring for improved reliability and error handling
- Core services enhancements for backend request management, response processing, tool call reactor middleware, and translation
- Tool call buffering and XML parsing fixes

### Changed

- Updated user guide features documentation
- Refactored Anthropic converters and other core components

## [2025-12-10]

### Added: Request Deduplication Service

- **Request Deduplication**: Universal request deduplication to prevent rate limit exhaustion from client retries
  - **Core Service**: Thread-safe `RequestDeduplicationService` with TTL-based caching and efficient garbage collection
  - **Hot Path Integration**: Integrated into `BackendRequestManager` to deduplicate requests before backend processing
  - **Configuration**: Configurable dedup window via CLI (`--request-dedup-window`), Env (`LLM_REQUEST_DEDUP_WINDOW`), and YAML
  - **Performance**: Optimized cleanup logic (10% buffer) to avoid O(N log N) sorting on every request
  - **Observability**: Debug-level logging for swallowed duplicates to avoid log spam during high-throughput retries

### Fixed: Anthropic and Gemini Connector Resilience

- **Anthropic Converter Improvements**:
  - **Error Handling**: Improved mapping of OpenAI error responses to Anthropic error format
  - **Empty Choices**: Defensive handling of empty choice lists to prevent crashes and provide clear error messages
  - **Generator Cleanup**: Added `GeneratorExit` handling in streaming responses to ensure proper resource cleanup

- **Gemini Connector Improvements**:
  - **Stream Cleanup**: Added `GeneratorExit` handling in `continue_from_prefetch` to ensure upstream generators are closed properly
  - **Empty Message Handling**: Allowed empty assistant messages in translation validation (needed for error scenarios) and updated message conversion to skip empty text parts

## [2025-12-09]

### Fixed: Anthropic Tool Validation and DI Improvements

- **Anthropic Tool Validation**: Enhanced robustness for Anthropic tool definition parsing
  - Added support for both flat and nested tool definition formats
  - Implemented fallback logic to handle ambiguous tool structures
  - Improved error handling for validation failures

- **Core Services Improvements**:
  - **Dependency Injection**: Fixed `ToolCallReactorFeature` detection in `_ensure_tool_call_reactor_services` to correctly identify the feature in `MiddlewareApplicationManager`
  - **Deprecation Warnings**: Downgraded `ToolCallReactorMiddleware` deprecation log from ERROR to WARNING to reduce noise during migration
  - **Timezone Handling**: Improved ISO date parsing in `ClineAuthMixin` to robustly handle 'Z' suffix

## [2025-12-08]

### Enhanced: OpenCode Zen Connector and Droid Support

- **OpenCode Zen Debugging Safeguards**: Added mandatory debugging flag `enable_opencode_zen_backend_debugging_override`
  - Prevents accidental usage of the development-only backend in production
  - Raises 403 Forbidden if flag is not set

- **Model Name Handling**: Improved normalization and denormalization for OpenCode Zen models
  - Robust handling of vendor prefixes (e.g., `anthropic/claude-3-opus`)
  - Fixes for specific model mappings and separator handling

- **Droid Agent Support**: Generalized relative path fixing for all Droid agents
  - Updated `ToolCallReactorFeature` to apply path fixes based on "droid" substring in agent name
  - Ensures compatibility with various Droid clients beyond specific backends

- **Middleware Metadata**: Enhanced `MiddlewareApplicationProcessor` context extraction
  - Extracts `calling_agent`, `backend_name`, and `model_name` from request metadata
  - Improves observability and context availability for downstream middleware

## [2025-12-07]

### Added: Feature Parity Architecture for Streaming/Non-Streaming Pipelines

- **Core Architecture**: New `IResponseFeature` interface enforces dual-path implementation
  - **Template Method Pattern**: Abstract `process_streaming()` and `process_non_streaming()` methods ensure explicit handling for both code paths
  - **FeatureCapability Enum**: Declares feature support (STREAMING, NON_STREAMING, BOTH)
  - **FeatureParityRegistry**: Tracks and verifies parity of all registered features at runtime

- **Adapter Pattern**: Seamless migration between legacy and new architectures
  - **MiddlewareToFeatureAdapter**: Wraps existing `IResponseMiddleware` for use with new pipeline
  - **FeatureToMiddlewareAdapter**: Exposes `IResponseFeature` as legacy middleware interface

- **Middleware Migration**: All response middleware migrated to `IResponseFeature`
  - `EmptyResponseFeature`: Handles empty response detection for both streaming/non-streaming
  - `StructuredOutputFeature`: JSON schema validation with streaming accumulation
  - `JsonRepairFeature`: Malformed JSON repair with streaming support
  - `ResponseLoggingFeature`, `ContentFilterFeature`, `LoopDetectionFeature`: Core utilities
  - `EditPrecisionFeature`: Edit failure detection for both paths
  - `ThinkTagsFixFeature`: Thinking tag normalization with streaming buffer
  - `ToolCallReactorFeature`: Tool call reaction handling
  - `ToolCallLoopDetectionFeature`: Loop detection with streaming support

- **Production Integration**: `MiddlewareApplicationManager` updated to use `IResponseFeature`
  - DI factory (`_middleware_application_manager_factory`) now instantiates Feature classes
  - Legacy `*Middleware` constructors log ERROR to detect accidental usage
- **CI Enforcement**: New test suite ensures architectural compliance
  - `test_feature_parity_ci.py`: Verifies all middleware have Feature versions
  - Automatic detection of parity violations at build time

### Added: SQLModel Database Migration and Deterministic Tool Event Tracking

- **Database Migration**: Migrated memory system from SQLite to SQLModel/Alembic for improved persistence and scalability
  - **SQLModel Integration**: New `SQLModelMemoryRepository` using SQLAlchemy models for type-safe database operations
  - **Alembic Migrations**: Added database migration support with automatic schema versioning
  - **Dependency Injection**: Updated DI container to register SQLModel repositories and database engine
  - **Backward Compatibility**: Legacy `MemoryRepository` preserved during transition period

- **Deterministic Tool Event Tracking**: Added capture and recording of deterministic file edits and git commits from proxy tool calls
  - **Tool Event Models**: New `FileEditEvent` and `GitCommitEvent` models for structured event data
  - **Event Collector**: `DeterministicToolEventCollector` captures events with session isolation and path normalization
  - **Memory Service Integration**: Enhanced `MemoryService` to record and retrieve tool events for session summaries
  - **Summary Generation**: Updated summary generator to include deterministic file edits and git commits in session transcripts
  - **Prompt Enhancement**: Memory summary prompts now incorporate tool event data for more accurate context

- **Gemini Connector Enhancements**: Improved model handling and public alias mapping
  - **Model Mapping**: Added `_public_to_internal_model_map` for aliasing public model names (e.g., `gemini-3-pro` → `gemini-3-pro-preview`)
  - **Dynamic Model Exposure**: Updated `get_available_models()` to expose public aliases while maintaining internal compatibility

- **SSO Token Service Optimization**: Enhanced token hashing parameters for testing performance
  - **Testing Parameters**: Reduced memory cost and iterations for faster test execution while maintaining security
  - **Production Safety**: Preserved secure parameters for production environments

### Added: Memory Feature (ProxyMem)

- **Core Functionality**: Intelligent memory retention for long-term sessions.
  - **Summary Generation**: Automatically generates session summaries after inactivity or completion.
  - **Context Injection**: Injects relevant historical context into new sessions based on semantic relevance.
  - **CLI Parameters**: Added comprehensive CLI support (`--memory-available`, `--memory-default-enabled`, `--memory-summary-model`, etc.).
  - **Documentation**: Updated `cli-parameters.md` and integration test snapshots.
  - **Fixes**: Resolved strict typing issues and DI registration for Memory components.

### Added: History Compaction Service

- **Context Optimization**: Automated history compaction to manage context window usage
  - **Core Logic**: New `HistoryCompactionService` for intelligent message history reduction
  - **Strategies**: Support for message summarization and removal of redundant content
  - **Integration**: Deep integration with `BackendRequestManager` to apply compaction before requests
  - **Testing**: Comprehensive integration tests covering full compaction flow

### Enhanced: Command Prefix and Configuration

- **CLI Robustness**: Improved validation and error reporting
  - **Prefix Validation**: Detailed error messages for invalid command prefixes (e.g. `'Invalid command prefix '!': ...'`)
  - **Memory Configuration**: Added environment variable support for `MEMORY_MAX_CONTEXT_TOKENS` and `MEMORY_CONTEXT_RELEVANCE_THRESHOLD`

### Enhanced: SSO Startup Validation

- **Safe Configuration**: Enhanced startup checks prevents invalid security states
  - **Legacy Auth Conflict**: Automatically rejects startup if legacy API keys are present when SSO is enabled
  - **Provider Checks**: Ensures at least one identity provider is enabled when SSO is active
  - **Binding Safety**: Prevents binding to non-loopback interfaces without authentication

## [2025-12-05]

### Added: Factory Droid Support and Enhanced Activity Monitoring

- **Factory Droid Support**: Seamless integration for Factory Droid clients
  - **Client Detection**: Automatic detection via User-Agent, system prompts, and tool signatures
  - **Tool Translation**: Intelligent translation of Droid's PascalCase tools to Codex-compatible formats
  - **Session Adaptation**: Droid-specific session handling and tool response formatting
  - **Proxy-Side Tools**: Support for client-specific tools like TodoWrite and WebSearch

- **Connection Activity Monitoring**: Real-time visibility into proxy traffic
  - **CLI Tool**: New `inspect_activity.py` script for live monitoring of active connections
  - **Documentation**: Comprehensive guide at `docs/user_guide/features/activity-monitoring.md`
  - **Performance**: Optimized lock-free tracking with minimal overhead
  - **Visualizations**: Rich terminal UI for monitoring connection states, RX/TX rates, and session details

### Added: Health Checks and Advanced Routing

- **Backend Health Monitoring**: Comprehensive system for detecting and managing unhealthy backends
  - **Multi-Layer Checks**: ICMP ping for network reachability and HTTP probes for application health
  - **Circuit Breaker**: Automatic exclusion of unhealthy backends from routing logic to prevent failures
  - **Real-time Notifications**: Event-driven system to notify backend instances of health state changes
  - **Health API**: REST endpoint (`/internal/health`) for monitoring system status
  - **Configurable Thresholds**: Custom settings for check intervals, timeouts, and failure thresholds

- **Advanced Routing Policies**: Enhanced control over request routing and load balancing
  - **Round Robin Load Balancing**: Automatic distribution of traffic across multiple instances of the same backend
  - **Routing Policies**: granular control to enable/disable routing by backend ID, backend name, or model name
  - **Model-Based Discovery**: Dynamic resolution of suitable backends based on requested model capabilitie... [truncated]
