# Changelog

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

## [2025-11-21]

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
