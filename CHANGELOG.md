# Changelog

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
  - **Model-Based Discovery**: Dynamic resolution of suitable backends based on requested model capabilities
  - **Policy Enforcement**: strict validation of routing requests against configured policies

- **Internal Event Bus**: Decoupled communication infrastructure
  - **Event-Driven Architecture**: Pub/sub pattern for internal system events (e.g., `EndpointHealthChanged`)
  - **Activity Tracking**: Centralized monitoring of connection activity and health events

### Added: Multi-Instance Backend Support and Multimodal Input Types

- **Multimodal Input Types**: New domain model for handling diverse input types
  - **Input Type Enum**: `MultimodalInputType` with support for image, PDF, audio, video, and text
  - **MIME Type Registry**: Comprehensive mapping of supported MIME types for each input type
  - **Validation**: Backend configuration validation against known multimodal types

- **Multi-Instance Backend Architecture**: Support for multiple backend instances of the same type
  - **Instance Naming**: Structured naming convention `<connector-name>.<instance-name>` with validation
  - **Backend Discovery**: Registry-based discovery of available backend instances
  - **Routing Logic**: Enhanced backend factory with instance-aware routing capabilities

- **Enhanced Backend Configuration**:
  - **Concurrent Use Control**: `allow_concurrent_use` flag for backend instances
  - **Credentials Path**: Configurable credentials storage location
  - **Input Type Declaration**: `supported_input_types` for backend capability declaration
  - **Connector Specification**: Explicit `connector` field for backend type identification

- **Backend Factory Refactoring**: Major overhaul of backend creation and management
  - **Instance Registry**: Dynamic tracking of backend instances with refresh capabilities
  - **Factory Methods**: Enhanced `create_backend()` and `ensure_backend()` methods
  - **Configuration Integration**: Deep integration with app configuration system

- **Testing Infrastructure**: Comprehensive test coverage for new features
  - **Backend Discovery Tests**: Validation of instance naming and discovery logic
  - **Backend Routing Tests**: Multi-instance routing behavior verification
  - **Configuration Tests**: Input type validation and backend settings

## [2025-12-04]

### Added: Anthropic Multimodal and Thinking Support

- **Multimodal Support**: Enhanced Anthropic-to-OpenAI conversion to support image and document blocks
  - **Images**: Converts Anthropic image blocks to OpenAI `image_url` format (supporting both base64 and url sources)
  - **Documents**: Converts Anthropic document blocks to text representation (as OpenAI doesn't natively support documents) with context preservation
  - **Multimodal Content**: Robustly handles mixed text, image, and document content in requests

- **Extended Thinking Support**: Added support for Claude's extended thinking feature
  - **Configuration**: Support for `thinking` parameter in `extra_body` with `type` and `budget_tokens`
  - **Service Tier**: Support for `service_tier` parameter (e.g., `auto` or `balanced`)
  - **Thinking Config Model**: New `ThinkingConfig` Pydantic model for validation

- **Response Improvements**:
  - **Stop Reasons**: Improved mapping of Anthropic `finish_reason` to OpenAI format
  - **Stop Sequences**: Proper extraction and passing of stop sequences

### Enhanced: VTC Streaming and SSO

- **VTC Response Wrapper**: Major improvements to Virtual Tool Call (VTC) streaming wrapper
  - **Async Support**: Added async `wrap()` method and async reactor invocation
  - **Tool Call Extraction**: Robust XML parsing for tool call extraction without modifying content for VTC clients
  - **Reactor Integration**: Properly invokes registered tool call reactors for detected tools in streaming chunks
  - **Helper**: Added `wrap_processed_response_stream_with_vtc` convenience function

- **SSO Enhancements**:
  - **Provider Selection**: UI and logic for selecting identity providers
  - **Re-authentication**: Support for re-authenticating existing tokens to extend sessions
  - **Token Linking**: Ability to link new authentication sessions to existing agent tokens

- **Translation Service**:
  - **Logprobs**: Added support for preserving `logprobs` in streaming chunks for OpenAI API parity

## [2025-12-02]

### Added: Comprehensive Usage Tracking and Statistics System

- **Multi-Point Token Tracking**: Track tokens at four measurement points for complete visibility
  - **Verbatim Tokens**: Original token counts before proxy modifications (CTP, BTP)
  - **Mutated Tokens**: Token counts after proxy transformations (PTB, PTC)
  - **Backend-Reported Tokens**: Provider-reported tokens for billing reconciliation
  - **Extended Token Details**: Reasoning tokens, cached tokens, audio tokens, costs

- **Performance Metrics**: Comprehensive timing and throughput monitoring
  - **Time to First Token (TTFT)**: Latency measurement for streaming responses
  - **Proxy Processing Time**: Overhead measurement for proxy operations
  - **Total Duration**: End-to-end request timing
  - **Statistical Aggregations**: Min, max, average, p50, p95, p99 percentiles

- **Request Monitoring**: Detailed tracking of all proxy traffic
  - **Request/Response Counts**: Per backend, model, frontend, and session
  - **HTTP Status Codes**: Error rate monitoring and status code breakdowns
  - **Tool Call Tracking**: Tool names, counts, and usage patterns
  - **Session Analysis**: Turn tracking and conversation flow analysis

- **Multi-Dimensional Filtering**: Query statistics by multiple dimensions
  - **Backend/Model**: Filter by provider and model name
  - **Frontend Type**: Filter by API interface (OpenAI, Anthropic, etc.)
  - **Traffic Leg**: Filter by direction (CTP, PTB, BTP, PTC)
  - **User Context**: Filter by user agent, proxy user, session ID
  - **Time Dimensions**: Filter by date range, hour of day, day of week

- **REST API Endpoints**: Query usage data via HTTP
  - `GET /v1/usage/stats`: Aggregated statistics with filtering
  - `GET /v1/usage/recent`: Recent usage records with pagination
  - `GET /v1/usage/export`: Export usage data as JSON

- **Persistent Storage**: Thread-safe in-memory storage with disk persistence
  - **In-Memory Store**: Fast access with threading.RLock for concurrency
  - **Periodic Persistence**: Configurable flush interval (default: 30s)
  - **Startup Recovery**: Load persisted data on proxy startup
  - **Graceful Shutdown**: Persist data on clean shutdown

- **Configuration Options**:
  - `usage_tracking.enabled`: Enable/disable tracking (default: true)
  - `usage_tracking.persistence_path`: Storage file path (default: "./var/usage_data.json")
  - `usage_tracking.flush_interval_seconds`: Persistence interval (default: 30.0)
  - `usage_tracking.max_records_in_memory`: Memory limit (default: 100000)

- **Documentation**:
  - **User Guide**: Complete feature guide at `docs/user_guide/features/usage-tracking.md`
  - **Integration Guide**: Developer integration guide at `docs/usage-tracking-integration.md`
  - **README Update**: Added usage tracking to key features list

- **Testing**: Comprehensive property-based testing with Hypothesis
  - **21 Correctness Properties**: All requirements validated with PBT
  - **86 Tests Total**: Property tests, unit tests, integration tests
  - **100% Test Pass Rate**: All tests passing

### Added: WebSocket Server for Codebuff Protocol

- **Codebuff Backend Support**: Full WebSocket server implementation for Codebuff coding agent protocol
  - **WebSocket Server**: Accepts connections on configurable endpoint (default: `/ws`)
  - **Connection Management**: Session tracking, heartbeat monitoring, and automatic cleanup
  - **Message Routing**: JSON message parsing, validation, and routing to action handlers
  - **Streaming Responses**: Real-time LLM response streaming via response-chunk actions
  - **Session Initialization**: File context storage and management via init actions
  - **Topic Subscriptions**: Subscribe/unsubscribe to message topics
  - **Backend Integration**: Seamless integration with all existing proxy backends

- **Configuration Options**:
  - `codebuff.enabled`: Enable/disable WebSocket server (default: false)
  - `codebuff.websocket_path`: WebSocket endpoint path (default: "/ws")
  - `codebuff.heartbeat_timeout_seconds`: Client heartbeat timeout (default: 60)
  - `codebuff.session_cleanup_hours`: Inactive session cleanup interval (default: 1)
  - `codebuff.max_connections`: Maximum concurrent connections (default: 1000)
  - `codebuff.max_message_size_bytes`: Maximum message size (default: 1MB)

- **Protocol Support**:
  - **Client Messages**: identify, ping, subscribe, unsubscribe, action (prompt, init)
  - **Server Messages**: ack, response-chunk, prompt-response, prompt-error, init-response
  - **Format Conversion**: Automatic conversion between Codebuff and OpenAI formats
  - **Error Handling**: Comprehensive error responses for all failure scenarios

- **Documentation**:
  - **Feature Guide**: Complete usage guide at `docs/user_guide/features/codebuff-backend.md`
  - **Protocol Reference**: Full protocol specification at `docs/user_guide/codebuff-protocol-reference.md`
  - **Example Configuration**: Codebuff-specific config at `config/codebuff.example.yaml`
  - **README Update**: Added Codebuff to key features list

- **Testing**: Comprehensive test coverage
  - **34 Property-Based Tests**: All correctness properties verified with Hypothesis
  - **Unit Tests**: Complete coverage of all components
  - **Integration Tests**: End-to-end WebSocket flow testing
  - **100% Test Pass Rate**: All tests passing

- **MVP Scope**: Current implementation includes core functionality
  - **Included**: WebSocket server, session management, prompt handling, streaming, init actions, subscriptions
  - **Future**: Tool calls, file access, MCP support, real authentication, usage tracking

## [2025-12-02] - Test Execution Reminder Phase 2: Improved Completion Detection

### Enhancement: Reliable Completion Detection Based on Actual Agent Behavior

- **Replaced Unreliable Pattern Matching**: Removed speculative text pattern matching in favor of evidence-based detection
  - **Old Approach**: Used regex patterns to match completion phrases in model output (prone to false positives)
  - **New Approach**: Uses actual tool names from real coding agents and API finish_reason markers

- **Primary Detection: Actual Completion Tool Names**: Based on source code analysis of popular coding agents
  - **`attempt_completion`**: Used by Cline and Roo-Code (Kilo Code) - most common completion tool
  - **`finish`**: Used by OpenHands (formerly OpenDevin)
  - **Generic Tools**: `finish_task`, `task_complete`, `mark_complete`, `complete`, `done`
  - **Evidence-Based**: Tool names extracted from actual agent source code, not speculation

- **Secondary Detection: Streaming finish_reason Markers**: Uses standard API values from OpenAI/Anthropic
  - **`stop`**: Normal completion
  - **`tool_calls`**: Completed with tool calls
  - **`length`**: Maximum token limit reached
  - **`end_turn`**: Anthropic's completion marker
  - **API-Compliant**: Based on official LLM API specifications

- **Benefits of New Approach**:
  - **No False Positives**: Only triggers on explicit completion signals, not ambiguous text
  - **Streaming Support**: Works with streaming responses via finish_reason extraction
  - **Agent-Specific**: Detects actual completion tools used by real coding agents
  - **Maintainable**: Easy to add new agent tool names as discovered
  - **Reliable**: Based on actual behavior, not speculation about what models might say

- **Implementation Changes**:
  - **CompletionSignalDetector**: Removed `COMPLETION_PATTERNS` and `_contains_completion_pattern()` method
  - **CompletionSignalDetector**: Added `FINISH_REASONS` set and `_is_finish_reason()` method
  - **CompletionSignalDetector**: Updated `is_completion_signal()` to accept `finish_reason` and `metadata` parameters
  - **TestExecutionReminderHandler**: Added `_extract_finish_reason()` and `_extract_metadata()` methods
  - **TestExecutionReminderHandler**: Updated logging to show finish_reason instead of pattern matching

- **Agent Compatibility**:
  - **Cline**: Automatically detected via `attempt_completion` tool
  - **Roo-Code (Kilo Code)**: Automatically detected via `attempt_completion` tool
  - **OpenHands**: Automatically detected via `finish` tool
  - **Generic Agents**: Detected via streaming finish_reason markers
  - **Custom Agents**: Extensible - new tool names can be added easily

- **Testing**: All tests updated and passing
  - **17 Unit Tests Rewritten**: Replaced pattern matching tests with tool name and finish_reason tests
  - **Property Tests Updated**: All property-based tests now use new detection methods
  - **Integration Tests Updated**: End-to-end tests verify new detection approach
  - **100% Coverage Maintained**: All new code fully tested
  - **No Regressions**: All existing tests remain green

- **Documentation**: Complete documentation of Phase 2 improvements
  - **User Guide Updated**: Added "Completion Detection Methods" section with detailed explanation
  - **Agent Compatibility Table**: Documents which agents use which completion tools
  - **Migration Notes**: Explains why the change was made and benefits of new approach
  - **PHASE2_IMPROVEMENTS.md**: Technical documentation of implementation changes

## [2025-12-01] - Random Model Replacement

### New Feature: Probabilistic Model Replacement for Session Resilience

- **Random Model Replacement**: Enables probabilistic swapping of user-specified backend:model pairs with alternative models during a session
  - **Resilience**: Automatically falls back to alternative models when primary models might struggle
  - **Diversity**: Introduces variety in model responses for testing and development
  - **Cost Optimization**: Probabilistically routes to more cost-effective models
  - **Transparent Operation**: Works seamlessly with existing features (tool filtering, wire capture, usage accounting)

- **Configuration Options**:
  - `replacement.enabled`: Enable/disable the feature (default: false)
  - `replacement.probability`: Probability (0.0-1.0) of triggering replacement
  - `replacement.backend_model`: Replacement backend:model pair (e.g., "qwen-oauth:qwen3-coder-plus")
  - `replacement.turn_count`: Number of turns to stay on replacement (default: 1)

- **Key Capabilities**:
  - **Multi-Turn Persistence**: Replacement remains active for a configurable number of turns
  - **Per-Session State**: Independent replacement state for each concurrent session
  - **Opt-Out Mechanisms**: Header-based (`X-Disable-Replacement`) and session-level opt-out
  - **Streaming Support**: Full support for streaming responses with replacement models
  - **Metrics Tracking**: Comprehensive metrics for activation rates and turn counts

- **Integration**:
  - **CLI Support**: New flags `--enable-replacement`, `--replacement-probability`, etc.
  - **Environment Variables**: `REPLACEMENT_ENABLED`, `REPLACEMENT_PROBABILITY`, etc.
  - **Documentation**: Complete user guide at `docs/user_guide/features/random-model-replacement.md`

## [2025-12-01] - Test Execution Reminder System

### New Feature: Intelligent Test Execution Steering for Agentic Workflows

- **Automated Test Enforcement**: Prevents agents from completing tasks without running tests after code modifications
  - **Dirty State Tracking**: Monitors file modifications and test executions per session
  - **Completion Signal Detection**: Identifies when agents attempt to signal task completion
  - **Steering Message Injection**: Automatically reminds agents to run tests before finalizing work
  - **Context Preservation**: Maintains full conversation history during steering interventions

- **Multi-Language Test Runner Support**: Recognizes test execution across 14+ programming languages
  - **Python**: pytest, unittest, py.test, python -m pytest
  - **JavaScript/TypeScript**: jest, vitest, mocha, ava, npm test, yarn test
  - **Rust**: cargo test
  - **Go**: go test
  - **Java**: mvn test, gradle test, ./gradlew test
  - **C#**: dotnet test
  - **Ruby**: rspec, rake test, bundle exec rspec
  - **PHP**: phpunit, composer test
  - **C/C++**: ctest, make test, cmake --build . --target test
  - **Swift**: swift test
  - **Kotlin**: gradle test (Kotlin projects)
  - **Scala**: sbt test
  - **Elixir**: mix test
  - **Dart/Flutter**: flutter test, dart test

- **File Modification Detection**: Tracks all file-modifying tool calls
  - Supports: write_file, str_replace, apply_diff, apply_patch, patch_file, multiedit, fs/write_text_file, insert_content, and variations
  - Case-insensitive matching with normalization for tool name variations

- **Extensible Pattern Registry**: Easy addition of new test runners without code changes
  - Pattern-based command matching with regex support
  - Priority-based pattern selection for specificity
  - Framework and language identification

- **Configuration Options**: Multiple configuration methods with proper precedence
  - **CLI Flags**: `--test-execution-reminder-enabled` / `--no-test-execution-reminder-enabled`
  - **Environment Variables**: `TEST_EXECUTION_REMINDER_ENABLED`, `TEST_EXECUTION_REMINDER_MESSAGE`
  - **Config File**: `test_execution_reminder_enabled`, `test_execution_reminder_message`
  - **Precedence**: CLI > Environment > Config file
  - **Custom Messages**: Configurable steering message text

- **Session Management**: Robust session isolation and cleanup
  - Independent state tracking per agent session
  - TTL-based cleanup (default: 30 minutes)
  - Memory guardrails with max session limits (default: 1024)
  - Concurrent session support

- **Error Handling**: Production-grade reliability
  - Fail-open strategy (allows requests through on errors)
  - Never crashes the proxy pipeline
  - Graceful degradation when disabled
  - Comprehensive logging at appropriate levels

- **Integration**: Seamless integration with existing infrastructure
  - Implements `IToolCallHandler` interface (priority: 90)
  - Works alongside existing handlers without interference
  - Tool Call Reactor pattern for event-driven steering
  - Swallow-and-replace pattern for steering injection

- **Testing**: Comprehensive test coverage ensuring correctness
  - **100% Code Coverage**: All new code fully tested
  - **15 Property-Based Tests**: Using Hypothesis library (100+ iterations each)
  - **184 Unit Tests**: Covering all components and edge cases
  - **14 Integration Tests**: End-to-end flow verification
  - **No Regressions**: All existing tests pass (5398 tests green)

- **Industry Best Practices**: Enforces quality standards for agentic workflows
  - Prevents incomplete work from being marked as done
  - Enforces test-driven development practices
  - Maintains conversation context during interventions
  - Provides clear, actionable feedback to agents
  - Supports multi-language development environments

- **Files Added**:
  - `src/services/test_execution_reminder/` - Core implementation package
    - `test_execution_reminder_handler.py` - Main handler with state management
    - `file_modification_detector.py` - File modification tool detection
    - `test_runner_registry.py` - Extensible test runner pattern registry
    - `completion_signal_detector.py` - Completion signal detection
    - `session_state.py` - Session state tracking dataclass
  - `tests/unit/services/test_execution_reminder/` - Comprehensive unit tests
  - `tests/property/` - 15 property-based tests for correctness verification
  - `tests/integration/test_test_execution_reminder_integration.py` - Integration tests
  - `.kiro/specs/test-execution-reminder/` - Complete specification documents

- **Configuration Files Updated**:
  - `config/config.example.yaml` - Added test execution reminder configuration
  - `config/sample.env` - Added environment variable examples
  - `src/core/config/app_config.py` - Extended with new configuration fields
  - `src/core/cli.py` - Added CLI arguments for feature control

- **Documentation**: Complete feature documentation
  - Requirements document with EARS-compliant acceptance criteria
  - Design document with correctness properties and testing strategy
  - Implementation tasks with property-based testing requirements
  - Verification document confirming all requirements met

## [2024-12-20] - Enhanced CBOR Inspection Script

### inspect_cbor_capture.py Improvements

- **New Command-Line Flags**:
  - `--session-id SID`: Filter entries by specific session ID for isolated analysis
  - `--hex`: Display raw hex dumps instead of text previews for binary protocol debugging
  - `--max-data N`: Control maximum data bytes shown per entry (default: 200)
- **Advanced Filtering Combinations**: Full support for combining `--session-id`, `--backend`, `--direction`, `--verbose` with all analysis modes (`--detect-issues`, `--timeline`, `--track-request`, `--analyze-streaming`)
- **Enhanced Verbose Output** (`--verbose`): Detailed metadata display including nanosecond timestamps, backend/model info, session details, and streaming chunk information
- **Filtered JSON Exports**: Export filtered subsets (e.g., `--backend gemini --session-id abc123 --json > filtered.json`) for external processing and automation
- **Improved Documentation**: Updated docs/user_guide/debugging/cbor-capture.md and docs/development_guide/debugging.md with comprehensive examples and use cases

## [2025-11-27] - CBOR Wire Capture and Simulation Engine

### New Feature: Byte-Precise Wire Capture with CBOR

- **CBOR Binary Format**: Introduced a new wire capture format using CBOR (Concise Binary Object Representation) for byte-level precision capture of all proxy traffic
  - **Nanosecond Timestamps**: Uses CBOR Tag 1 for precise timing information, enabling accurate replay of streaming responses
  - **Raw Byte Capture**: Captures exact bytes without JSON serialization overhead or escaping issues
  - **Streaming Chunk Tracking**: Each SSE chunk captured individually with sequence numbers and timing metadata
  - **Direction Tracking**: Distinguishes between client->proxy, proxy->client, proxy->backend, and backend->proxy traffic

- **Domain Models**: New `src/core/domain/cbor_capture.py` with:
  - `CaptureDirection` enum for traffic direction
  - `CaptureMetadata` for session, backend, model, and streaming metadata
  - `CaptureEntry` for individual capture entries with timestamps and raw bytes
  - `CaptureFileHeader` for file metadata and validation
  - `CaptureSession` for complete session representation with filtering methods

- **CBOR Wire Capture Service**: New `src/core/services/cbor_wire_capture_service.py` implementing `IWireCapture`:
  - Async buffered I/O with background flushing for minimal performance impact
  - Automatic session file creation and management
  - Stream wrapping for capturing SSE chunks with timing
  - Graceful shutdown with final buffer flush

- **CLI Integration**: New command-line arguments:
  - `--cbor-capture-dir DIR`: Enable CBOR capture to specified directory
  - `--cbor-capture-session ID`: Set specific session ID for capture file naming

- **Configuration**: New `LoggingConfig` options:
  - `cbor_capture_dir`: Directory for CBOR capture files
  - `cbor_capture_session`: Optional fixed session ID

### New Feature: Traffic Simulation Engine

- **Simulation Module**: New `src/core/simulation/` package for replay-based regression testing:
  - `CaptureReader`: Loads and parses CBOR capture files with filtering and statistics
  - `TimingController`: Manages timing delays for accurate replay
  - `BackendSimulator`: Mock backend server that replays captured responses with timing
  - `ClientSimulator`: Replays client requests and validates responses
  - `SimulationRunner`: Orchestrates full session replay with comprehensive validation

- **Simulation CLI**: New command-line tool (`python -m src.core.simulation.cli`):
  - `inspect`: View capture file summary and statistics
  - `list`: List all capture files in a directory
  - `replay`: Replay captured session against a running proxy with validation

- **Validation Results**: Comprehensive validation including:
  - Content mismatch detection with byte-level comparison
  - Timing deviation tracking with configurable tolerance
  - Detailed reports with summaries and failure details

### Test Infrastructure

- **Pytest Fixtures**: New `tests/simulation/conftest.py` with:
  - `temp_capture_dir`: Temporary directory for test captures
  - `capture_reader`, `timing_controller`, `simulation_runner`: Pre-configured instances
  - `simple_capture_file`, `streaming_capture_file`: Ready-to-use test captures
  - Helper functions: `create_capture_file`, `create_simple_request_response`, `create_streaming_response`

- **Unit Tests**: Comprehensive test coverage in `tests/unit/core/services/test_cbor_wire_capture_service.py`:
  - Domain model serialization and deserialization
  - Capture service initialization and configuration
  - Request/response capture for all directions
  - Streaming capture with timing preservation
  - Shutdown and buffer flushing

### Architecture

- **Conditional Registration**: `CoreServicesStage` now conditionally registers either `BufferedWireCapture` (JSON format) or `CborWireCaptureService` based on `cbor_capture_dir` configuration
- **Interface Compliance**: New CBOR service implements existing `IWireCapture` interface for seamless integration
- **Backward Compatible**: JSON wire capture remains the default; CBOR capture is opt-in via configuration

### Use Cases

- **Regression Testing**: Capture known-good sessions and replay to detect behavioral changes
- **Streaming Debugging**: Inspect exact byte sequences and timing for SSE issues
- **CI/CD Integration**: Automated replay tests in continuous integration pipelines
- **Performance Analysis**: Analyze timing patterns and identify bottlenecks

### Files Added

- `src/core/domain/cbor_capture.py` - Domain models for CBOR capture
- `src/core/services/cbor_wire_capture_service.py` - CBOR wire capture implementation
- `src/core/simulation/__init__.py` - Simulation module exports
- `src/core/simulation/capture_reader.py` - CBOR file parser
- `src/core/simulation/timing_controller.py` - Timing management for replay
- `src/core/simulation/backend_simulator.py` - Mock backend server
- `src/core/simulation/client_simulator.py` - Client request replayer
- `src/core/simulation/simulation_runner.py` - Orchestration and validation
- `src/core/simulation/cli.py` - Simulation CLI tool
- `tests/simulation/__init__.py` - Test package marker
- `tests/simulation/conftest.py` - Pytest fixtures
- `tests/unit/core/services/test_cbor_wire_capture_service.py` - Unit tests

### Dependencies

- Added `cbor2` library for CBOR encoding/decoding

## [2025-11-25] - Unified Streaming Pipeline & Tool Call Reliability

### Major Refactoring: Unified Response Pipeline

- **Single Code Path for All Responses**: Merged streaming and non-streaming response processing into a unified pipeline (`UnifiedResponsePipeline`). Non-streaming responses are now wrapped as single-chunk streams via `NonStreamingAdapter`, processed through all middleware, then unwrapped back to `ProcessedResponse`.
- **Eliminated Code Duplication**: Removed duplicate middleware application logic between streaming and non-streaming paths, following DRY principles.
- **Consistent Middleware Application**: All `IResponseMiddleware` implementations (tool call repair, loop detection, content filtering, redaction) are now applied consistently regardless of response type.
- **Simplified `ResponseProcessor`**: Now delegates to `UnifiedResponsePipeline` for all response types.
- **Deprecated `MiddlewareApplicationManager`**: No longer processes responses directly; retained only as a configuration holder for the middleware list.

### Tool Call Reliability Improvements

- **Fixed Session ID Propagation**: Resolved critical bug where `session_id` was not being propagated to streaming chunks, causing tool call buffering to fail when chunks were split across multiple SSE events.
- **Robust Stream Correlation**: Added `_resolve_stream_session_id` method in `BackendService` that resolves stable identifiers from multiple sources (context, request, extra_body, request_id, or generates UUID as fallback).
- **Consistent `stream_id` Injection**: Both wire-capture and non-wire-capture paths now consistently include `session_id` and `stream_id` in chunk metadata.
- **Improved XML Tool Buffering**: Tool calls split across multiple chunks are now correctly reassembled regardless of varying chunk IDs.
- **Fixed Truncated XML Tool Parsing**: Resolved critical bug where truncated XML tool calls (e.g., `<execute_command>` without closing tag) caused the parser to incorrectly extract inner tags (e.g., `<command>`) as the tool name. Now the `ToolCallRepairProcessor` waits for complete XML before parsing, and inner tags like `<command>`, `<file>`, `<question>`, etc. are explicitly skipped.
- **Expanded Tool Tag Buffering**: Added all known XML tool tags (`execute_command`, `read_file`, `write_to_file`, `ask_followup_question`, `attempt_completion`, `list_files`, `search_files`, `codebase_search`, `access_mcp_resource`) to the synthetic closing tag list and flush prevention markers.

### Streaming Pipeline Completion

- **All P0 Blockers Resolved**: Tool-call lifecycle unified, buffers centralized via `StreamingContextRegistry`, legacy paths removed, property tests implemented, strict DI enforced.
- **All P1 Items Resolved**: Loop detection deduplication, metrics consistency, error handling, streaming sampler configuration.
- **All P2 Items Resolved**: Filesystem watcher debouncing, generalized XML tool buffering, content accumulation with reasoning metadata, documentation updates.

### Testing

- **5398 tests passing** (8 skipped)
- Property-based tests with Hypothesis for streaming contracts
- Regression tests for XML tool call buffering
- Integration tests for unified pipeline

### Documentation

- Updated `docs/streaming_pipeline_migration.md` with unified pipeline architecture
- Updated `.kiro/specs/streaming-pipeline-refactor/remaining-gaps.md` to reflect 100% completion

## ["2025-11-21"]

- **Features**:
  - Add usage recalculation feature and development documentation.
  - Enhance Gemini connectors with usage tracking.
  - Add Cline and ZenMux backend connectors.
- **Fixes**:
  - Enhance loop detection and cancellation logic for streaming.
  - Address streaming regression and improve hybrid backend.
- **Refactoring**:
  - Improve core services and streaming infrastructure.
- **Testing**:
  - Add comprehensive streaming regression testing infrastructure.
- **Documentation**:
  - Add usage tracking documentation and configuration.

## [2025-11-04]

- **Hybrid Backend Repeat Messages Feature**: New configuration option to repeat reasoning output as an artificial message in the session
  - **New Configuration Option**: `--hybrid-backend-repeat-messages` CLI flag and `HYBRID_BACKEND_REPEAT_MESSAGES` environment variable to enable the feature
  - **Artificial Message Injection**: When enabled, reasoning output is added as an artificial assistant message in the conversation history
  - **Enhanced Context**: Provides better context continuity by making reasoning visible to the execution model as a separate message
  - **Configuration**: Can be enabled/disabled via `backends.hybrid_backend_repeat_messages` in config files
  - **Testing**: Comprehensive unit tests added to verify the message repetition functionality

- **OpenAI Codex Connector Improvements**: Enhanced tool schema handling and Kilo tool translation capabilities
  - **Tool Schema Registry**: Added comprehensive schemas for `read_file`, `list_dir`, and `grep_files` tools with proper parameter validation
  - **Enhanced Tool Translation**: Improved Kilo tool translation with tool call ID generation and argument JSON serialization
  - **Command Parsing**: Enhanced shell command parsing using `shlex.split()` for better argument handling and cross-platform compatibility
  - **Parameter Aliases**: Added legacy parameter aliases (`file_path`, `dir_path`) for backward compatibility with existing tool schemas
  - **Tool Call Metadata**: Added proper tool call metadata injection for assistant messages containing XML tool invocations
  - **Schema Validation**: Improved tool schema validation and duplicate prevention in payload construction
  - **Working Directory Handling**: Fixed working directory parameter mapping with both `workdir` and `working_dir` aliases
  - **Testing**: Updated unit tests to cover new tool schema and translation functionality

## [2025-10-31]

- **XML Tool Call Format Support**: Added support for XML tool call format in ToolCallRepairService
  - XML pattern detection and parsing for Kilo MCP tools
  - Support for both direct XML tool format and use_mcp_tool wrapper format
  - XML element to dictionary conversion for argument parsing
  - Comprehensive tests for XML tool call repair functionality

## [2025-10-30]

- **Think Tags Fix Feature**: Added `--fix-think-tags` CLI flag and `FIX_THINK_TAGS_ENABLED` environment variable to correct improperly formatted `think` tags in model responses
  - Detects and fixes models that expose reasoning content as `<think>reasoning</think>response` instead of using proper reasoning/thinking token separation
  - Preserves reasoning content in appropriate fields (OpenAI-style `reasoning` field, metadata, etc.) instead of discarding it
  - Full streaming support with session-based buffering for think tags split across multiple chunks
  - Universal backend compatibility - works with all connectors (OpenAI, Anthropic, Gemini, custom, etc.)
  - Multiple response format support: OpenAI-style responses, dict responses, ProcessedResponse objects
  - Configurable streaming buffer size via `FIX_THINK_TAGS_STREAMING_BUFFER_SIZE` environment variable
  - Opt-in feature (disabled by default) with comprehensive logging and debugging metadata
  - Standards-compliant reasoning separation following established LLM API patterns

## [2025-10-23]

- **Intelligent Session Management**: Autonomous session continuity detection via message history fingerprinting
  - **Context Loss Prevention**: Eliminates session loss for stateless clients (e.g., Kilo Code, Cursor) that don't send session IDs
  - **Message History Fingerprinting**: Computes stable hashes from conversation sequences to detect continuity
  - **Fuzzy Matching**: Identifies conversation continuations even when exact fingerprints don't match (e.g., extended conversations)
  - **Client Identification**: Generates stable client keys from IP + User-Agent for session association
  - **Zero Client Changes Required**: Fully autonomous - works without any modifications to LLM clients or agents
  - **Wire Capture Enhancement**: Added `inbound_request` direction to capture client→proxy requests for debugging
  - **Configuration Options**:
    - `session.session_continuity.enabled` (default: true)
    - `session.session_continuity.fuzzy_matching` (default: true)
    - `session.session_continuity.max_session_age_seconds` (default: 604800 - 7 days)
    - `session.session_continuity.fingerprint_message_count` (default: 5)
    - `session.session_continuity.client_key_includes_ip` (default: true)
  - **Backward Compatible**: Explicit session IDs via `x-session-id` header still take priority
  - **Testing**: Comprehensive unit and integration tests for fingerprinting and session resolution
  - **Documentation**: Full feature documentation added to README.md

## [2025-01-21]

- **LLM Assessment System**: Intelligent conversation quality monitoring inspired by Google's gemini-cli
  - Automatically detects unproductive patterns like repetitive tool calls and cognitive loops
  - Event-driven assessment triggers after configurable turn thresholds (default: 30 turns)
  - Confidence-based intervention system (default: 0.9 threshold) with steering message injection
  - Dynamic frequency adjustment based on assessment confidence levels
  - Multi-backend support - works with OpenAI, Anthropic, Gemini, and other configured backends
  - Comprehensive configuration via CLI arguments, environment variables, and YAML
  - Graceful degradation - assessment failures never break main conversation flow
  - Complete documentation in README.md with configuration examples and use cases

## 2025-10-17 - Gemini OAuth Backend Refactoring

- **Refactor**: Split `gemini-oauth-personal` backend into two specialized backends for different use cases
  - **New Backend**: `gemini-oauth-free` for free-tier Gemini API usage with appropriate quotas and limits
  - **New Backend**: `gemini-oauth-plan` for paid Gemini API usage with enterprise features and higher quotas
  - **Improved Separation**: Clear distinction between free and paid tiers eliminates confusion about feature availability
  - **Migration**: Existing configurations automatically redirect to appropriate backend based on authentication type
  - **Testing**: Comprehensive test suites created for both new backends with full coverage of OAuth flows and API interactions

## 2025-10-16 - Command Pipeline Policy & Regression Coverage

- **Dependency Injection**: Command services now require explicit `ICommandPolicyService`
  and `ICommandStateService` instances. `CommandStage` wires the policy/state helpers,
  tail extractor, and match filter, eliminating the legacy registry auto-population.
- **Policy Abstraction**: Added `CommandPolicyService` that centralises static-route,
  interactive-disable, strict-detection, and prefix resolution decisions with environment
  fallbacks and app-state overrides.
- **State Adapter**: Introduced `CommandStateService` to expose secure session state
  access/mutation without duplicating repository logic.
- **Handler Alignment**: Interactive handlers (`set`, `model`, `unset`) and domain
  commands pull policy inputs via DI, ensuring static routing and alias normalisation
  behave consistently across adapters.
- **Regression Coverage**: Expanded unit/integration suites covering tail-only parsing,
  whitespace-tolerant detection, multi-command lines, multimodal tails, and reasoning
  parameter enforcement. New builder utilities let tests provision fully wired command
  services.
- **Housekeeping**: Documented progress in `dev/command-refactor-plan.md` and updated
  fixtures to rely on the shared command-service builder.

## 2025-10-06 - Various Improvements

- **Feature**: Added Model Name Rewrites system for dynamic model name transformation
  - **Powerful Regex Engine**: Transform model names using Python regular expressions with capture group support
  - **Multiple Configuration Sources**: Support for CLI parameters, environment variables, and config files with proper precedence (CLI > ENV > Config)
  - **CLI Parameters**: `--model-alias PATTERN=REPLACEMENT` (repeatable) with real-time regex validation
  - **Environment Variables**: `MODEL_ALIASES` JSON array with graceful error handling for malformed data
  - **Config File**: `model_aliases` YAML section with schema validation and detailed error messages
  - **First-Match-Wins Processing**: Rules processed in order with the first matching pattern applied
  - **Seamless Integration**: Works with static routes, planning phase, failover, and in-chat commands
  - **Common Use Cases**: Backend abstraction, cost optimization, environment-specific routing, and fallback strategies
  - **Robust Error Handling**: Invalid regex patterns caught early, malformed JSON logged as warnings, graceful fallback for invalid rules
  - **Comprehensive Testing**: 18 unit tests covering all configuration sources, precedence order, validation, and error scenarios
  - **Production Ready**: Enterprise-grade configuration support with validation and error recovery
  - **Examples**: Route all GPT models to OpenRouter (`^gpt-(.*)=openrouter:openai/gpt-\\1`), replace expensive models with cheaper alternatives, create catch-all fallbacks
  - **Documentation**: Complete user documentation in README.md with usage examples and integration guidance

- **Feature**: Added configurable strict command detection to reduce false positives when commands are mentioned in conversation
  - **Default Mode**: Commands are processed anywhere in the last user message (backward compatible)
  - **Strict Mode**: Commands are only processed if they appear on the last non-blank line of the message
  - **Configuration Options**: CLI flag (`--strict-command-detection`), environment variable (`STRICT_COMMAND_DETECTION`), and config file (`strict_command_detection`)
  - **CLI Override Priority**: CLI flags override environment variables and config file settings
  - **Security Enhancement**: Updated emergency command filter with separate warning messages for strict vs default modes
  - **Command Processing**: Enhanced CommandService with line-based command extraction for strict mode
  - **Comprehensive Testing**: Added 13 unit tests covering all command detection scenarios and edge cases
  - **Documentation**: Updated README with detailed usage examples and behavior comparisons

- **Feature**: Automatic project directory detection driven by a dedicated helper model
  - **One-Time Analysis**: On the first user prompt the proxy can call a configured backend:model to infer an absolute project directory
  - **Strict Output Contract**: Helper model must respond with XML describing the directory or an error; the proxy validates paths for Windows and Linux formats before applying them
  - **Configuration Options**: CLI flag (`--project-dir-resolution-model BACKEND:MODEL`), environment variable (`PROJECT_DIR_RESOLUTION_MODEL`), and config entry (`session.project_dir_resolution_model`)
  - **Isolated Execution**: The helper model response stays out of the user session, and results are surfaced via INFO-level diagnostics only
  - **Testing**: Added unit tests for successful resolution, invalid responses, and disabled configuration paths

- **Feature**: Added pytest execution agent steering to prevent agents from running entire test suites inadvertently
  - **Intelligent Detection**: Automatically detects when agents attempt to run full pytest suites without specific file, directory, or node selectors
  - **Steering Behavior**: First matching command in a session is intercepted and replaced with a helpful steering message encouraging selective test execution
  - **User Override**: If the agent re-issues the same command after the warning, the handler allows it to pass through
  - **Session-Based Logic**: Warning state is tracked per session, allowing different behavior for separate sessions
  - **Command Recognition**: Supports various pytest invocation patterns including `pytest`, `python -m pytest`, and `py.test`
  - **Comprehensive Pattern Matching**: Distinguishes between full-suite runs (e.g., `pytest`, `pytest -q`) and targeted execution (e.g., `pytest tests/unit/`, `pytest specific_file.py::test_case`)
  - **Configuration**: Opt-in feature controlled by `pytest_full_suite_steering_enabled` (default: `false`) with custom steering message support via `pytest_full_suite_steering_message`
  - **Environment Variable**: `PYTEST_FULL_SUITE_STEERING_ENABLED` for runtime control
  - **Integration**: Implemented as Tool Call Reactor handler with priority 95, positioned between dangerous command handling and generic steering
  - **Testing**: Comprehensive unit test suite covering detection logic, session behavior, enabled/disabled states, and various pytest command patterns
  - **Files Created**:
    - `src/core/services/tool_call_handlers/pytest_full_suite_handler.py` (233 lines) - Main handler implementation
    - `tests/unit/core/services/tool_call_handlers/test_pytest_full_suite_handler.py` (97 lines) - Comprehensive unit tests

- **Cleanup**: Removed the archived `src/core/cli_old.py` module. The modern
  CLI implementation in `src/core/cli.py` has fully replaced it and all
  dependencies now point to the new entry point. Keeping the unused module in
  the tree caused confusion during maintenance and risked duplicated updates.

## 2025-10-05 – Planning-Phase Strong Model Overrides

- **Feature**: Optional planning-phase model switch with parameter overrides for the strong model
  - Route early session turns to a configured strong model to improve initial planning quality
  - Automatically switch back to the default model after a max number of turns or after the first file-writing tool call
  - Reuses existing Tool Call Reactor to detect file-touching tools (e.g., `write_file`, `edit_file`, `apply_diff`, `patch_file`, `edit_notebook`)
  - Parameter overrides (applied only during planning-phase): `temperature`, `top_p`, `reasoning_effort`, `thinking_budget`
- **Configuration**:
  - YAML (`session.planning_phase`): `enabled`, `strong_model`, `max_turns`, `max_file_writes`, and `overrides.{temperature, top_p, reasoning_effort, thinking_budget}`
  - Env: `PLANNING_PHASE_ENABLED`, `PLANNING_PHASE_STRONG_MODEL`, `PLANNING_PHASE_MAX_TURNS`, `PLANNING_PHASE_MAX_FILE_WRITES`, `PLANNING_PHASE_TEMPERATURE`, `PLANNING_PHASE_TOP_P`, `PLANNING_PHASE_REASONING_EFFORT`, `PLANNING_PHASE_THINKING_BUDGET`
  - CLI: `--enable-planning-phase`, `--planning-phase-strong-model`, `--planning-phase-max-turns`, `--planning-phase-max-file-writes`, `--planning-phase-temperature`, `--planning-phase-top-p`, `--planning-phase-reasoning-effort`, `--planning-phase-thinking-budget`
- **Notes**:
  - Skips override if current model already equals the strong model
  - After switching back, routing reverts to the normal/default model resolution
  - Tests added/updated; full suite green

## 2025-10-04 - Gemini CLI ACP Backend with Full Project Directory Control

- **New Backend**: Added `gemini-cli-acp` backend that uses Google's `gemini-cli` as an AI agent via the Agent Control Protocol (ACP)
  - **Agent Integration**: Spawns and manages `gemini-cli` subprocess with JSON-RPC communication over stdin/stdout
  - **Project Directory Awareness**: Full access to project files, enabling code analysis, refactoring, and multi-file editing
  - **Tool Usage**: Agent can execute commands, use tools, and perform complex operations within the project
  - **Streaming Support**: Real-time streaming responses from the agent with proper SSE formatting
  - **Process Management**: Robust subprocess lifecycle handling with automatic restart on configuration changes

- **Full Project Directory Control**: Implemented 4 different mechanisms for controlling project directory
  - **1. Runtime Slash Command** (highest priority): `!/project-dir(/path/to/project)` - leverages existing command infrastructure
  - **2. Config File**: Set `project_dir` in `config/backends/gemini-cli-acp/backend.yaml`
  - **3. Environment Variable**: `GEMINI_CLI_WORKSPACE=/path/to/project`
  - **4. Current Working Directory**: Automatic fallback to `cwd`
  - **Dynamic Switching**: Project directory changes automatically restart the agent process with new context
  - **Path Validation**: All paths validated, expanded (`~`, env vars), and converted to absolute paths

- **Existing Command Integration**: Uses existing `!/project-dir(path)` command from `ProjectDirCommandHandler`
  - Query current project directory: `!/project-dir()`
  - Change project directory: `!/project-dir(/new/path)`
  - Path validation and user-friendly error messages
  - Integrated with session state (`project_dir`)

- **Configuration**: Complete backend configuration system
  - Backend config file: `config/backends/gemini-cli-acp/backend.yaml`
  - Customizable parameters: `model`, `auto_accept`, `process_timeout`, `gemini_cli_executable`
  - Comprehensive documentation with usage examples and priority order

- **Error Handling**: Production-grade error handling with custom exceptions
  - Configuration errors for missing/invalid project directories
  - API connection errors for subprocess communication failures
  - Timeout errors with configurable thresholds
  - Service unavailability handling when agent is not initialized

- **Testing**: Comprehensive test suite with 100% pass rate
  - **Unit Tests**: 22 tests covering initialization, process management, communication, project directory control, and streaming
  - Tests for all 4 project directory control mechanisms
  - Process lifecycle tests (spawn, kill, restart)
  - JSON-RPC communication tests
  - Streaming response processing tests
  - All tests passing: `tests/unit/connectors/test_gemini_cli_acp.py`

- **Files Created**:
  - `src/connectors/gemini_cli_acp.py` (598 lines) - Core connector implementation
  - `config/backends/gemini-cli-acp/backend.yaml` - Backend configuration with full documentation
  - `tests/unit/connectors/test_gemini_cli_acp.py` (399 lines) - Comprehensive unit tests

- **Code Quality**: All quality checks passing
  - ✅ ruff: All checks passed
  - ✅ black: Code formatted
  - ✅ mypy: Type checking passed
  - Leverages existing command infrastructure (ProjectDirCommandHandler) instead of creating duplicate functionality

- **Documentation**: Complete user-facing documentation
  - README updated with backend table entry, Gemini Backends Overview, Quick Start section, and Popular Scenarios
  - Configuration examples for all 4 project directory control methods
  - Usage examples with feature descriptions
  - Integration requirements (npm package, authentication)

## 2025-10-03 - Security: API Key Brute-Force Protection

- **Feature**: Added per-IP brute-force protection to the API key middleware with exponential back-off blocking and automatic cache cleanup to prevent unbounded memory usage.
- **Configuration**: Introduced CLI flags, environment variables, and YAML configuration (`auth.brute_force_protection`) to tune attempt thresholds, time windows, and block durations.
- **Testing**: Added dedicated unit coverage for the new blocking flow, including retry-after escalation and reset on successful authentication.
- **Documentation**: Updated README, config examples, and sample environment variables to explain the new security controls and usage patterns.

## 2025-10-03 - OAuth Credential Auto-Refresh Improvements and Streaming Bug Fixes

- **Enhancement**: Improved OAuth credential auto-refresh functionality across Anthropic, Gemini, and OpenAI backends
  - **Force Reload**: Added `force_reload` parameter to credential loading methods to bypass timestamp cache when file changes are detected
- **Cross-Platform Path Handling**: Fixed file system watcher path comparison logic using Path objects to handle Windows/Unix differences correctly
- **Robust File Watching**: Enhanced error handling in file modification events to prevent crashes during path comparison operations
- **Immediate Reload**: File watcher now schedules immediate credential reloads when OAuth credential files change, ensuring fresh tokens are loaded without restart

- **Bug Fix**: Fixed ContentAccumulationProcessor to preserve metadata and usage information for empty streaming chunks
  - **Streaming Continuity**: Empty chunks now maintain their metadata/usage data so downstream processors (e.g., usage accounting) continue to receive updated values
- **Improved Streaming**: Fixed issue where empty chunks were losing important context information during processing

- **Bug Fix**: Corrected tuple syntax in ToolCallLoopDetectionMiddleware type checking from `str | bytes | bytearray` to `(str, bytes, bytearray)` for proper isinstance() usage

- **Testing**: Added comprehensive test coverage for OAuth credential reloading functionality
  - **File Watching Tests**: New tests verify correct path comparison and file change detection
  - **Force Reload Tests**: Tests confirm that force_reload bypasses timestamp caching as expected
  - **Cross-Platform Tests**: Tests validate proper handling of different file path formats

- **OAuth Backends**: Enhanced credential management for `anthropic-oauth`, `gemini-oauth-personal`, and `openai-codex` backends with improved reliability and automatic refresh

## 2025-10-01 - Code Quality and Type Hinting Improvements

- **Enhancement**: Added comprehensive type hints across the codebase to improve code quality, maintainability, and developer experience
  - Applied type hints to architectural linter (`scripts/architectural_linter.py`) with proper union types (`str | None`, `dict[str, str]`, `set[str]`)
  - Updated pre-commit hook script with proper type annotations
  - Enhanced test files with comprehensive type hints for better test reliability
  - Improved session service tests with proper DI patterns and type annotations

- **Configuration**: Updated mypy configuration in `pyproject.toml` for better type checking
  - Added specific overrides for `google.genai` and `setuptools` modules to handle third-party import issues
  - Configured `disallow_untyped_defs = true` to enforce strict type checking
  - Updated exclude patterns from single string to list format

- **Code Quality**: Improved architectural patterns and SOLID compliance
  - Fixed comparison operators in SOLID violation detector (`"Exception" not in node.name` instead of `not "Exception" in node.name`)
  - Enhanced architectural linter with better type safety and clearer variable declarations
  - Updated test fixtures to remove unnecessary imports and improve clarity

- **Testing**: Enhanced test infrastructure with better DI patterns
  - Added comprehensive tests for session service using proper dependency injection
  - Improved test isolation and clarity across multiple test files
  - Removed redundant imports and cleaned up test code structure

- **Maintenance**: Various code quality improvements including import organization, unused import removal, and code formatting consistency

## 2025-10-01 - Refactor: Translation Service and Gemini Request Counting

- **Refactor**: Centralized all request/response translation logic into a new `TranslationService` (`src/core/services/translation_service.py`). This improves modularity, simplifies maintenance, and makes it easier to add new API formats.
- **Feature**: Added a daily request counter to the `GeminiOAuthPersonalConnector` (`src/connectors/utils/gemini_request_counter.py`). This helps monitor API usage and prevent exceeding rate limits. The counter persists its state to `data/gemini_oauth_request_count.json`.
- **Feature**: Added support for the OpenAI `/v1/responses` endpoint, which enables structured output generation with JSON schema validation.
- **Dependencies**: Added `pytz`, `freezegun`, and `types-pytz` to support the new features and improve testing capabilities.

## 2025-09-30 – Major Enhancement: Hybrid Loop Detection Algorithm

- **Enhancement**: Implemented hybrid loop detection algorithm combining Google's gemini-cli approach with efficient long pattern detection
  - **Background**: The original bug pattern (200+ chars with no internal repetition) could not be detected by any single hash-chunk algorithm, including gemini-cli's approach
  - **Solution**: Created hybrid detector that uses:
    - **Short patterns (<=50 chars)**: Google's proven gemini-cli algorithm with sliding window hash comparison
    - **Long patterns (>50 chars)**: Custom rolling hash algorithm (Rabin-Karp style) for efficient pattern matching
  - **Performance**: Optimized for production use - lightweight rolling hash with configurable limits to avoid performance impact
  - **Detection Capabilities**:
    - [OK] Short repetitive patterns: `"Loading... "` repeated 15+ times
    - [OK] Long repetitive patterns: 200+ char blocks repeated 3+ times (including original bug pattern)
    - [OK] Context-aware: Resets only on code fences/dividers, not on markdown lists/headings that might be part of the loop
  - **Files Added**:
    - `src/loop_detection/hybrid_detector.py` - Main hybrid implementation
    - `src/loop_detection/gemini_cli_detector.py` - Ported gemini-cli algorithm
    - `tests/unit/test_hybrid_loop_detector.py` - Comprehensive test suite (15 tests)
    - `tests/unit/test_gemini_cli_loop_detector.py` - Gemini-cli specific tests
  - **Files Modified**:
    - `src/core/app/stages/infrastructure.py` - Updated DI registration to use HybridLoopDetector
  - **Algorithm Details**:
    - Rolling hash uses base-31 arithmetic with 2^32-1 modulus for collision resistance
    - Configurable pattern length limits (60-500 chars) and repetition thresholds (3+ occurrences)
    - Memory-efficient with content truncation (2000 char max history for long patterns)
    - Hash collision verification through actual content comparison
  - **Testing**: Successfully detects the original bug pattern that triggered this investigation

## 2025-09-30 – Critical Fix: Loop Detection Was Disabled Due to DI Configuration Errors

- **Bug Fix**: Fixed critical dependency injection configuration errors that completely disabled loop detection in production
  - **Root Cause #1**: Incorrect import path in `src/core/app/stages/infrastructure.py` - imported from `src.core.interfaces.loop_detector` instead of `src.core.interfaces.loop_detector_interface`, causing silent registration failure
  - **Root Cause #2**: Missing factory function for `LoopDetectionProcessor` in `src/core/di/services.py` - the processor requires an `ILoopDetector` dependency in its constructor, but no factory was provided to inject it
  - **Impact**: Loop detection was completely non-functional despite being enabled by default. Repetitive LLM responses (13+ identical paragraphs) were not detected or mitigated
  - **Solution**:
    - Fixed import path to use correct interface: `src.core.interfaces.loop_detector_interface`
    - Added proper factory function to inject `ILoopDetector` into `LoopDetectionProcessor`
    - Increased `content_chunk_size` from 50 to 100 characters for better detection of longer patterns
    - Added comprehensive DI integrity tests to prevent similar issues in the future
  - **Files Modified**:
    - `src/core/app/stages/infrastructure.py` - Fixed ILoopDetector import and registration
    - `src/core/di/services.py` - Added factory for LoopDetectionProcessor with dependency injection
    - `src/loop_detection/config.py` - Increased content_chunk_size to 100
    - `tests/unit/test_loop_detection_regression.py` - New regression tests for DI wiring
    - `tests/integration/test_di_container_integrity.py` - New comprehensive DI integrity tests (8 tests)
  - **Documentation**: Detailed analysis in `LOOP_DETECTION_BUG_ANALYSIS.md`
  - **Testing**: 5 passing tests specifically verify that ILoopDetector and LoopDetectionProcessor are properly registered and wired

## 2025-09-30 – Fix: 502 Timeout Error in Gemini OAuth Streaming

- **Bug Fix**: Resolved 502 Bad Gateway errors during long streaming responses
  - **Root Cause**: Hardcoded 60-second timeout was insufficient for large file reads and complex responses
  - **Solution**: Implemented separate connection and read timeouts using tuple format `(connect_timeout, read_timeout)`
  - **Configuration**: Connection timeout: 60s (unchanged), Read timeout: 300s (5 minutes)
  - **Impact**: Large file reads, complex analyses, and long-running requests now complete successfully without premature disconnections
  - **Files Modified**: `src/connectors/gemini_oauth_personal.py`, `src/connectors/gemini_cloud_project.py`
  - **Documentation**: Added detailed analysis in `docs/dev/502_timeout_fix.md`

## 2025-10-02 – Gemini Personal OAuth Auto-Refresh

- **Startup Validation**: The `gemini-oauth-plan` and `gemini-oauth-free` backends now confirm the stored OAuth token is still valid during initialization, failing fast when credentials are stale instead of deferring to the first request.
- **Live Credential Watching**: Introduced a filesystem watcher for the Gemini CLI `oauth_creds.json` file so refreshed tokens are loaded into memory immediately without restarting the proxy.
- **Proactive Refresh Flow**: Every request now checks remaining token lifetime; when the token is expired or inside a two-minute window the proxy launches the Gemini CLI refresh command in the background and polls for the updated token, eliminating manual intervention after Google's expiry change.

## 2025-10-01 – CLI v2 Migration

- **Default CLI Updated**: Promoted the staged `cli_v2` implementation to the primary entrypoint (`src/core/cli.py`) for running the proxy.
  - Feature parity verified by the existing CLI-focused unit suite and the full project test run.
  - Removed the unused Colorama dependency while keeping Windows startup behavior unchanged.
- **Legacy CLI Preservation**: Archived the previous implementation as `src/core/cli_old.py` for quick rollback and historical reference.
  - The codebase no longer imports the legacy module; it can be deleted safely once the fallback is no longer required.

## 2025-09-30 – Auto-Discovery Architecture for Backends and Commands

- **Architecture Improvement**: Implemented true SOLID/DIP-compliant auto-discovery mechanisms
  - **Backend Auto-Discovery**:
    - Backends are automatically discovered using `pkgutil.iter_modules()` - no hardcoded imports required
    - Simply drop a new backend file in `src/connectors/` with `backend_registry.register_backend()` call
    - Follows Open/Closed Principle - system is open for extension but closed for modification
    - Failed backend imports don't break other backends - errors are logged as warnings
    - All backend classes are still exported for existing imports to work (backward compatible)
    - Full test coverage in `tests/unit/test_backend_autodiscovery.py`
    - Documentation in `docs/dev/backend_auto_discovery.md`
  - **Command Auto-Discovery**:
    - Domain commands are automatically discovered using `pkgutil.iter_modules()` - no hardcoded registrations
    - Created `DomainCommandRegistry` for centralized command registration
    - Simply add `domain_command_registry.register_command()` calls at module level
    - Command stage now uses auto-discovery instead of hardcoded command instantiation
    - Failover commands and all domain commands benefit from auto-discovery
    - Full test coverage in `tests/unit/test_command_autodiscovery.py`
  - **Benefits**:
    - Zero maintenance overhead when adding new backends or commands
    - Reduced coupling between implementations and discovery system
    - Plugin-ready architecture for future extensibility
    - Resilient error handling for failed imports
- **Bug Fix**: Fixed Gemini OAuth Personal backend integration
  - Implemented proper authentication flow using `google.auth.transport.requests.AuthorizedSession`
  - Fixed Code Assist API request/response format wrapping
  - Made health checks non-blocking to prevent startup failures
  - Added automatic managed project ID discovery for free-tier users

## 2025-09-13 – Automated Pytest Output Compression

- **New Feature**: Added automated pytest tool call output compression to preserve context window space
  - **Automatic Detection**: Recognizes pytest commands using regex patterns (`pytest`, `python -m pytest`, `py.test`, etc.)
  - **Smart Filtering**: Removes verbose output while preserving error information
    - Filters out timing information (`s setup`, `s call`, `s teardown`)
    - Removes `PASSED` test results (keeps only failures and errors)
    - Preserves all `FAILED` tests and error messages
  - **Configuration**: Configurable via `session.pytest_compression_enabled` (default: `true`)
    - Global configuration in `config.yaml`
    - Environment variable: `PYTEST_COMPRESSION_ENABLED`
    - Per-session control via session state
  - **Monitoring**: Logs compression statistics showing line reduction percentages
  - **Integration**: Seamlessly integrated into response manager for both Cline and non-Cline agents
  - **Testing**: Comprehensive unit test coverage with edge case handling
  - **Schema Support**: Full Pydantic validation and YAML schema definition
  - **Backward Compatibility**: Feature is enabled by default but can be disabled without affecting existing functionality

## 2025-09-12 – Reasoning Aliases Feature

- **New Feature**: Added reasoning aliases system for dynamic model parameter control during sessions
  - **Interactive Commands**: New chat commands to switch between reasoning modes
    - `!/max`: Activate high reasoning mode with configured parameters (temperature, reasoning_effort, max_reasoning_tokens, prompt prefixes/suffixes)
    - `!/medium`: Activate medium reasoning mode for balanced approach
    - `!/low`: Activate low reasoning mode for faster responses
    - `!/no-think` (aliases: `!/no-thinking`, `!/no-reasoning`, `!/disable-thinking`, `!/disable-reasoning`): Disable reasoning for direct responses
  - **Configuration**: External YAML-based configuration in `config/reasoning_aliases.yaml`
    - Per-model settings with wildcard support (e.g., `claude-sonnet-4*`)
    - Configurable parameters: `temperature`, `top_p`, `reasoning_effort`, `thinking_budget`, `max_reasoning_tokens`
    - User prompt engineering: `user_prompt_prefix` and `user_prompt_suffix`
  - **Session Integration**: Reasoning settings persist across the session until changed
  - **Backend Integration**: Automatic application of reasoning configuration to outbound requests via `_apply_reasoning_config` method
  - **Error Handling**: Clear error messages when models have no configured reasoning settings
  - **Command Architecture**: New `ReasoningAliasCommandHandler` base class with per-mode implementations
  - **Schema Validation**: Full Pydantic-based validation for configuration structure
  - **Testing**: Comprehensive unit and integration test coverage (reasoning alias end-to-end tests, integration tests)
  - **Version 1.0**: Initial implementation complete with all core functionality

## 2025-09-11 – Enhanced Authentication Reliability with Stale Token Handling

- **Major Enhancement**: Implemented comprehensive stale authentication token handling pattern across all file-backed OAuth backends
  - **Affected Backends**: `gemini-cli-cloud-project`, `gemini-oauth-plan`, `gemini-oauth-free`, `anthropic-oauth`, and `openai-codex`
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

## 2025-09-30 - CLI Context Window Override Feature

- **New Feature**: Added `--force-context-window` CLI argument for static context window overrides across all models.
  - **CLI Argument**: `--force-context-window TOKENS` sets a static context window size that overrides all model-specific configurations.
  - **Front-end Enforcement**: Enforces token limits before requests reach backend providers, preventing unnecessary API calls and costs.
  - **Structured Error Responses**: Returns detailed 400 Bad Request responses with measured vs. limit token counts and error codes.
  - **Configuration Integration**: CLI override takes precedence over config file settings while maintaining compatibility with existing configurations.
  - **Environment Variable Support**: Sets `FORCE_CONTEXT_WINDOW` environment variable for downstream processes.

## 2025-10-31 - ZAI Coding Plan GLM 4.6 Support

- **Model Updates**: ZAI coding plan now preserves the client-provided model and defaults to `glm-4.6`, keeping `claude-sonnet-4-20250514` available as a legacy option.
  - **Anthropic Routing**: Chat controller now forwards the resolved model name to the Anthropic compatibility path instead of forcing `claude-sonnet-4-20250514`.
  - **API Headers**: ZAI connector overrides `get_headers` to include the current KiloCode metadata required by the upstream service.
  - **Capabilities**: Model capability registry exposes entries for `glm-4.6`, `zai-coding-plan`, and the legacy Claude variant with updated metadata.
  - **Testing & Docs**: Unit/integration tests and documentation refreshed to reflect GLM 4.6, with new coverage ensuring headers and payload models are preserved.
  - **Schema Validation**: Updated YAML schema to support the new `context_window_override` field.
  - **Comprehensive Testing**: Full test coverage for CLI argument parsing, enforcement logic, and edge cases.
  - **Documentation**: Enhanced README with detailed examples, use cases, and troubleshooting guidance.
  - **Use Cases**: Cost control, testing compatibility, performance optimization, and multi-tier service configurations.

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

## 2025-08-31 – OpenAI Codex Backend

- New backend: `openai-codex` for using OpenAI without storing API keys in proxy config.
  - Reads Codex CLI `auth.json` (ChatGPT login) and uses `tokens.access_token` as bearer; falls back to `OPENAI_API_KEY` if present.
  - Default search paths: `~/.codex/auth.json` and on Windows `%USERPROFILE%/.codex/auth.json`.
  - Optional `openai_codex_path` to point at a specific directory containing `auth.json`.
  - Optional `openai_api_base_url` to override the default `https://api.openai.com/v1` (env `OPENAI_BASE_URL` can also be used in some environments).
  - Can be selected via `LLM_BACKEND=openai-codex` or per-request model prefix `openai-codex:<model>`.
  - Documentation added under README “OpenAI Codex Backend”.

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
  - JSON repair -> text loop detection -> tool-call repair -> middleware -> accumulation.
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

- **New Feature**: Added `gemini-oauth-plan` and `gemini-oauth-free` backends for seamless integration with Google's Gemini API using OAuth 2.0 credentials
  - **OAuth Integration**: Reads OAuth credentials from `~/.gemini/oauth_creds.json` (created by Gemini CLI tool)
  - **Automatic Token Refresh**: Handles OAuth token expiration automatically using Google's token refresh endpoint
  - **Health Checks**: Performs lightweight connectivity and authentication validation on first use
  - **Cross-Platform Support**: Works on Windows, Linux, and macOS with proper path handling
  - **Error Handling**: Comprehensive error handling for authentication failures, connectivity issues, and token refresh problems
  - **Testing**: Complete test suite with 28 tests covering all functionality including health checks, token refresh, and error scenarios
  - **Configuration**: Simple backend configuration requiring only `gemini_api_base_url` parameter
  - **Usage**: Supports all standard proxy features including interactive commands (`!/backend(gemini-oauth-plan)`, `!/oneoff(gemini-oauth-plan:gemini-pro)`, `!/backend(gemini-oauth-free)`, `!/oneoff(gemini-oauth-free:gemini-pro)`)

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
