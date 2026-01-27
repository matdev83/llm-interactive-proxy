# CLI Parameters and Configuration Reference

This guide documents all available CLI parameters, environment variables, and configuration options for the LLM Interactive Proxy.

## Configuration Precedence

Configuration is resolved in the following order (highest to lowest priority):

1. **CLI Arguments** - Command-line flags override everything
2. **Environment Variables** - Environment variables override config files
3. **YAML Configuration File** - Config file provides defaults
4. **Built-in Defaults** - Hardcoded defaults if nothing else is specified

---

## General

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--help`, `-h` | N/A | Show help message and exit. |
| `--config FILE` | `CONFIG_FILE` | Path to persistent configuration file (YAML). |

---

## Backend Selection

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--default-backend BACKEND` | `LLM_BACKEND` | Default backend to use (e.g., `openai`, `anthropic`, `gemini`). |
| `--static-route BACKEND:MODEL` | `STATIC_ROUTE` | Force all requests to use this backend:model combination. |
| `--disable-gemini-oauth-fallback` | `DISABLE_GEMINI_OAUTH_FALLBACK=1` | Disable automatic Gemini OAuth fallback to `gemini-2.5-flash`. |
| `--disable-hybrid-backend` | `DISABLE_HYBRID_BACKEND=1` | Disable the hybrid backend (enabled by default). |
| `--hybrid-backend-repeat-messages` | `HYBRID_BACKEND_REPEAT_MESSAGES=1` | Repeat reasoning output as an artificial message in the session. |
| `--reasoning-injection-probability FLOAT` (or `--reasoning_injection_probability`) | `REASONING_INJECTION_PROBABILITY` | Probability of using the reasoning model in the hybrid backend (0.0 to 1.0). |
| `--hybrid-reasoning-model-timeout SECONDS` | `HYBRID_REASONING_MODEL_TIMEOUT` | Timeout for the reasoning model call in hybrid scenarios (default: 60). |
| `--hybrid-reasoning-force-initial-turns N` | `HYBRID_REASONING_FORCE_INITIAL_TURNS` | Number of turns at start of session to force reasoning model usage (default: 4). |
| `--model-alias PATTERN=REPLACEMENT` | `MODEL_ALIASES` (JSON string) | Add a model name rewrite rule (regex pattern and replacement). Can be used multiple times. |

---

## Server Configuration

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--host HOST` | `APP_HOST` | Bind host (default: `127.0.0.1`). |
| `--port PORT` | `APP_PORT` | Bind port (default: `8000`). |
| `--anthropic-port PORT` | `ANTHROPIC_PORT` | Port for Anthropic-compatible endpoints (default: disabled/derived). |
| `--timeout SECONDS` | `PROXY_TIMEOUT` | Global request timeout in seconds (default: 120). |
| `--command-prefix PREFIX` | `COMMAND_PREFIX` | Command prefix for in-chat commands (default: `!/`). |
| `--force-context-window TOKENS` | `FORCE_CONTEXT_WINDOW` | Override context window size for all models. |
| `--thinking-budget TOKENS` | `THINKING_BUDGET` | Set max reasoning tokens for all requests. |

---

## Authentication & Security

### API Keys & Tokens

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--disable-auth` | `DISABLE_AUTH=1` | Disable client authentication (forces localhost binding). |
| `--disable-sso-captcha` | `SSO_CAPTCHA_ENABLED=false` | Disable SSO Captcha verification (overrides config). |
| `--disable-redact-api-keys-in-prompts` | `REDACT_API_KEYS_IN_PROMPTS=false` | Disable redaction of API keys in prompts. |
| `--openrouter-api-key KEY` | `OPENROUTER_API_KEY` | OpenRouter API Key. |
| `--openrouter-api-base-url URL` | `OPENROUTER_API_BASE_URL` | OpenRouter API Base URL. |
| `--gemini-api-key KEY` | `GEMINI_API_KEY` | Google Gemini API Key. |
| `--gemini-api-base-url URL` | `GEMINI_API_BASE_URL` | Google Gemini API Base URL. |
| `--zai-api-key KEY` | `ZAI_API_KEY` | ZAI API Key. |
| `--zenmux-api-base-url URL` | `ZENMUX_API_BASE_URL` | ZenMux API Base URL. |
| N/A | `ANTHROPIC_API_KEY` | Anthropic API Key. |
| N/A | `ANTHROPIC_API_BASE_URL` | Anthropic API Base URL. |
| N/A | `AUTH_TOKEN` | Shared secret token for client authentication. |

### Brute Force Protection

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--enable-brute-force-protection` | `BRUTE_FORCE_PROTECTION_ENABLED=true` | Enable API key brute-force protection. |
| `--disable-brute-force-protection` | `BRUTE_FORCE_PROTECTION_ENABLED=false` | Disable API key brute-force protection. |
| `--auth-max-failed-attempts N` | `BRUTE_FORCE_MAX_FAILED_ATTEMPTS` | Max failed attempts before blocking (default: 5). |
| `--auth-brute-force-ttl SECONDS` | `BRUTE_FORCE_TTL_SECONDS` | Time window for tracking failed attempts (default: 900). |
| `--auth-brute-force-initial-block SECONDS` | `BRUTE_FORCE_INITIAL_BLOCK_SECONDS` | Initial block duration (default: 30). |
| `--auth-brute-force-multiplier FLOAT` | `BRUTE_FORCE_BLOCK_MULTIPLIER` | Multiplier for subsequent blocks (default: 2.0). |
| `--auth-brute-force-max-block SECONDS` | `BRUTE_FORCE_MAX_BLOCK_SECONDS` | Max block duration (default: 3600). |

### Access Control

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--trusted-ip IP` | N/A | IP address to trust for bypassing authorization. |
| `--allow-admin` | N/A | Allow running with administrative privileges. |

---

## Advanced Backend Settings

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--hybrid-execution-model-timeout SECONDS` | `HYBRID_EXECUTION_MODEL_TIMEOUT` | Timeout for execution model in hybrid scenarios. |
| N/A | `HYBRID_REASONING_LATENCY_THRESHOLD` | Latency threshold for adaptive reasoning backoff. |
| N/A | `HYBRID_REASONING_BACKOFF_TURNS` | Turns to skip reasoning after latency threshold exceeded. |

## Backend Timeouts

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| N/A | `OPENROUTER_TIMEOUT` | Timeout for OpenRouter requests. |
| N/A | `GEMINI_TIMEOUT` | Timeout for Gemini requests. |
| N/A | `ANTHROPIC_TIMEOUT` | Timeout for Anthropic requests. |
| N/A | `ZAI_TIMEOUT` | Timeout for ZAI requests. |
| N/A | `ZENMUX_TIMEOUT` | Timeout for ZenMux requests. |
| N/A | `OPENAI_TIMEOUT` | Timeout for OpenAI requests. |
| N/A | `MINIMAX_TIMEOUT` | Timeout for Minimax requests. |

## Logging & Capture

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--log-level LEVEL` | `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL). |
| `--log FILE` | `LOG_FILE` | Path to log file. |
| `--log-colors` | `LOG_COLORS=true` | Enable colored log output. |
| `--no-log-colors` | `LOG_COLORS=false` | Disable colored log output. |
| `--capture-file FILE` | `CAPTURE_FILE` | Write raw LLM requests/replies to this file (JSON). |
| `--capture-max-bytes N` | `CAPTURE_MAX_BYTES` | Max size of capture file before rotation. |
| `--capture-truncate-bytes N` | `CAPTURE_TRUNCATE_BYTES` | Truncate captures to N bytes per entry. |
| `--capture-max-files N` | `CAPTURE_MAX_FILES` | Max number of capture files to retain. |
| `--capture-rotate-interval SECONDS` | `CAPTURE_ROTATE_INTERVAL_SECONDS` | Time-based rotation period. |
| `--capture-total-max-bytes N` | `CAPTURE_TOTAL_MAX_BYTES` | Total disk cap across capture files. |
| `--cbor-capture-dir DIR` | N/A | Directory for CBOR byte-precise capture files. |
| `--cbor-capture-session ID` | N/A | Fixed session ID for CBOR capture. |
| N/A | `REQUEST_LOGGING` | Enable detailed request logging (boolean). |
| N/A | `RESPONSE_LOGGING` | Enable detailed response logging (boolean). |
| N/A | `CAPTURE_BUFFER_SIZE` | Buffer size for wire capture writes (bytes). |
| N/A | `CAPTURE_FLUSH_INTERVAL` | Flush interval for wire capture (seconds). |
| N/A | `CAPTURE_MAX_ENTRIES_PER_FLUSH` | Max entries buffered before forced flush. |

---

## Session Management

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--disable-interactive-mode` | `DEFAULT_INTERACTIVE_MODE=false` | Disable interactive mode by default. |
| `--force-set-project` | `FORCE_SET_PROJECT=true` | Require project name to be set before sending prompts. |
| `--project-dir-resolution-model BACKEND:MODEL` | `PROJECT_DIR_RESOLUTION_MODEL` | Model used to detect absolute project directory. |
| `--project-dir-resolution-mode MODE` | `PROJECT_DIR_RESOLUTION_MODE` | Strategy: 'deterministic', 'llm', or 'hybrid'. |
| `--disable-interactive-commands` | N/A | Disable all in-chat command processing. |
| `--disable-accounting` | `DISABLE_ACCOUNTING=true` | Disable LLM usage tracking. |
| `--no-accounting` | `DISABLE_ACCOUNTING=true` | Disable LLM usage tracking (alias for --disable-accounting). |
| `--strict-command-detection` | `STRICT_COMMAND_DETECTION` | Require commands to be at the start of messages. |
| `--enable-sandboxing` | `ENABLE_SANDBOXING=true` | Restrict file operations to the project directory. |
| `--daemon` | N/A | Run server as a daemon (background process). |
| `--enable-end-of-session` | N/A | Enable end-of-session detection and event emission. |
| `--disable-end-of-session` | N/A | Disable end-of-session detection and event emission. |
| `--end-of-session-emit-events` | N/A | Enable event emission (default when EoS is enabled). |
| `--end-of-session-detect-only` | N/A | Enable detect-only mode (no events emitted). |
| `--end-of-session-dispatch-timeout SECONDS` | N/A | Maximum time to wait for event dispatch (default: 5.0, 0 for fire-and-forget). |
| N/A | `SESSION_CLEANUP_ENABLED` | Enable session cleanup (boolean). |
| N/A | `SESSION_CLEANUP_INTERVAL` | Cleanup interval in seconds. |
| N/A | `SESSION_MAX_AGE` | Max session age in seconds. |
| N/A | `SANDBOXING_STRICT_MODE` | Enable strict mode for sandboxing. |
| N/A | `SANDBOXING_ALLOW_PARENT_ACCESS` | Allow access to parent directories in sandbox. |

### Tool Call & JSON Repair

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| N/A | `TOOL_CALL_REPAIR_ENABLED` | Enable tool call repair. |
| N/A | `TOOL_CALL_REPAIR_BUFFER_CAP_BYTES` | Buffer cap for tool call repair. |
| N/A | `JSON_REPAIR_ENABLED` | Enable JSON repair. |
| N/A | `JSON_REPAIR_BUFFER_CAP_BYTES` | Buffer cap for JSON repair. |
| N/A | `JSON_REPAIR_SCHEMA` | JSON schema for repair. |
| N/A | `FORCE_REPROCESS_TOOL_CALLS` | Force reprocessing of tool calls. |
| N/A | `LOG_SKIPPED_TOOL_CALLS` | Log skipped tool calls. |

### Streaming Sampler

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| N/A | `STREAMING_SAMPLER_ENABLED` | Enable streaming sampler. |
| N/A | `STREAMING_SAMPLER_RATE` | Sampling rate (0.0 to 1.0). |
| N/A | `STREAMING_SAMPLER_MAX_SAMPLES` | Max samples to retain. |

### History Compaction

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--enable-context-compaction` | `ENABLE_CONTEXT_COMPACTION=true` | Enable history compaction to reduce stale tool outputs. (Default: Disabled) |
| `--compaction-min-tokens N` | `COMPACTION_MIN_TOKENS` | Minimum tokens required to trigger compaction. (Default: 100,000) |

---

## Features

### Memory (ProxyMem)

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--memory-available` | `MEMORY_AVAILABLE=true` | Enable the Memory feature globally. |
| `--memory-default-enabled` | `MEMORY_DEFAULT_ENABLED=true` | Enable Memory by default for new sessions. |
| `--memory-summary-model BACKEND:MODEL` | `MEMORY_SUMMARY_MODEL` | Model to use for generating session summaries. |
| `--memory-context-model BACKEND:MODEL` | `MEMORY_CONTEXT_MODEL` | Model to use for retrieving context. |
| `--memory-summary-prompt FILE` | `MEMORY_SUMMARY_PROMPT` | Path to custom summary prompt file. |
| `--memory-context-prompt FILE` | `MEMORY_CONTEXT_PROMPT` | Path to custom context prompt file. |
| `--memory-database-path FILE` | `MEMORY_DATABASE_PATH` | Path to SQLite database for memory storage. |
| `--memory-session-timeout MINUTES` | `MEMORY_SESSION_TIMEOUT_MINUTES` | Timeout in minutes for session inactivity. |
| `--memory-summarization-delay SECONDS` | `MEMORY_SUMMARIZATION_DELAY_SECONDS` | Delay before summarizing completed sessions. |
| `--memory-max-sessions-to-consider N` | `MEMORY_MAX_SESSIONS_TO_CONSIDER` | Max recent sessions to consider for context. |
| `--memory-retention-days DAYS` | `MEMORY_RETENTION_DAYS` | Days to retain memory data. |
| `--memory-max-context-tokens N` | `MEMORY_MAX_CONTEXT_TOKENS` | Max tokens for injected context. |
| `--memory-max-summary-tokens N` | `MEMORY_MAX_SUMMARY_TOKENS` | Max tokens for summary prompt context. |
| `--memory-max-transcript-chars N` | `MEMORY_MAX_TRANSCRIPT_CHARS` | Max transcript length before chunking. |
| `--memory-summary-completion-tokens N` | `MEMORY_SUMMARY_COMPLETION_TOKENS` | Max completion tokens for summary generation. |
| `--memory-context-relevance-threshold FLOAT` | `MEMORY_CONTEXT_RELEVANCE_THRESHOLD` | Minimum relevance score for context retrieval. |
| `--memory-max-buffer-size-bytes N` | `MEMORY_MAX_BUFFER_SIZE_BYTES` | Max capture buffer size per session. |
| `--memory-analysis-queue-maxsize N` | `MEMORY_ANALYSIS_QUEUE_MAXSIZE` | Max size of analysis queue. |
| `--memory-analysis-timeout SECONDS` | `MEMORY_ANALYSIS_TIMEOUT_SECONDS` | Timeout per summary generation. |
| `--memory-max-concurrent-analyses N` | `MEMORY_MAX_CONCURRENT_ANALYSES` | Max concurrent analyses. |
| `--memory-context-template TEMPLATE` | `MEMORY_CONTEXT_TEMPLATE` | Template for injected context (use `{context}`). |
| `--memory-single-user-mode` | `MEMORY_SINGLE_USER_MODE=true` | Enable single-user mode (ignores user IDs). |
| `--memory-fixed-user-id ID` | `MEMORY_FIXED_USER_ID` | Fixed user ID to use in single-user mode. |
| `--memory-persist-transcript` | `MEMORY_PERSIST_TRANSCRIPT=true` | Persist transcripts for summaries. |
| `--memory-redaction-pattern PATTERN` | `MEMORY_REDACTION_PATTERNS` | Add a regex pattern for redaction. Can be used multiple times. |
| `--memory-disable-user ID` | `MEMORY_DISABLED_USERS` | Disable memory for specific user ID. Can be used multiple times. |
| `--memory-disable-client ID` | `MEMORY_DISABLED_CLIENTS` | Disable memory for specific client ID. Can be used multiple times. |
| `--memory-summary-prompt-version VERSION` | `MEMORY_SUMMARY_PROMPT_VERSION` | Summary prompt version identifier. |
| `--memory-summary-schema-version VERSION` | `MEMORY_SUMMARY_SCHEMA_VERSION` | Summary schema version identifier. |
| `--memory-require-project-discovery` | `MEMORY_REQUIRE_PROJECT_DISCOVERY=true` | Require project discovery before context injection. |
| `--memory-allow-missing-project` | `MEMORY_REQUIRE_PROJECT_DISCOVERY=false` | Allow context injection without project discovery. |
| `--memory-project-discovery-mode MODE` | `MEMORY_PROJECT_DISCOVERY_MODE` | Project discovery mode. |

> **See Also:** [ProxyMem: Cross-Session Memory](proxymem-memory.md) for detailed documentation on the memory feature.

### Planning Phase

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--enable-planning-phase` | `PLANNING_PHASE_ENABLED=true` | Enable planning phase model routing. |
| `--planning-phase-strong-model BACKEND:MODEL` | `PLANNING_PHASE_STRONG_MODEL` | Strong model for planning phase. |
| `--planning-phase-max-turns N` | `PLANNING_PHASE_MAX_TURNS` | Max turns before switching from strong model. |
| `--planning-phase-max-file-writes N` | `PLANNING_PHASE_MAX_FILE_WRITES` | Max file writes before switching. |
| `--planning-phase-temperature FLOAT` | `PLANNING_PHASE_TEMPERATURE` | Temperature override for planning. |
| `--planning-phase-top-p FLOAT` | `PLANNING_PHASE_TOP_P` | Top-p override for planning. |
| `--planning-phase-reasoning-effort EFFORT` | `PLANNING_PHASE_REASONING_EFFORT` | Reasoning effort override for planning. |
| `--planning-phase-thinking-budget TOKENS` | `PLANNING_PHASE_THINKING_BUDGET` | Thinking budget override for planning. |

### Edit Precision Tuning

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--enable-edit-precision` | `EDIT_PRECISION_ENABLED=true` | Enable automated edit-precision tuning. |
| `--disable-edit-precision` | `EDIT_PRECISION_ENABLED=false` | Disable automated edit-precision tuning. |
| `--edit-precision-temperature FLOAT` | `EDIT_PRECISION_TEMPERATURE` | Target temperature (default: 0.1). |
| `--edit-precision-min-top-p FLOAT` | `EDIT_PRECISION_MIN_TOP_P` | Minimum top_p (default: 0.3). |
| `--edit-precision-override-top-p` | `EDIT_PRECISION_OVERRIDE_TOP_P` | Enable top_p override. |
| `--edit-precision-target-top-k N` | `EDIT_PRECISION_TARGET_TOP_K` | Target top_k value. |
| `--edit-precision-override-top-k` | `EDIT_PRECISION_OVERRIDE_TOP_K` | Enable top_k override. |
| `--edit-precision-exclude-agents REGEX` | `EDIT_PRECISION_EXCLUDE_AGENTS_REGEX` | Exclude agents matching regex. |

### Activity Tracking

Real-time connection activity tracking for debugging and monitoring. Disabled by default for performance.

| CLI Argument | Environment Variable | Config File | Description |
| :--- | :--- | :--- | :--- |
| `--enable-activity-tracking` | `ENABLE_ACTIVITY_TRACKING=1` | `enable_activity_tracking: true` | Enable connection activity tracking (RX/TX counters per session). |

### LLM Assessment

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--enable-llm-assessment` | `LLM_ASSESSMENT_ENABLED=true` | Enable conversation assessment. |
| `--disable-llm-loop-assessment` | `LLM_ASSESSMENT_ENABLED=false` | Disable conversation assessment. |
| `--llm-assessment-turn-threshold N` | `LLM_ASSESSMENT_TURN_THRESHOLD` | Turns before assessment activates. |
| `--llm-assessment-confidence-threshold FLOAT` | `LLM_ASSESSMENT_CONFIDENCE_THRESHOLD` | Confidence threshold for intervention. |
| `--llm-assessment-model BACKEND:MODEL` | `LLM_ASSESSMENT_MODEL` | Backend and model for assessment. |
| `--llm-assessment-history-window N` | `LLM_ASSESSMENT_HISTORY_WINDOW` | History window size. |
| N/A | `LLM_ASSESSMENT_BACKEND` | Backend for assessment. |

### Angel Verification

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--use-angel-model BACKEND:MODEL` | `ANGEL_MODEL` | Enable Angel verification with model. |
| `--angel-frequency N` | `ANGEL_FREQUENCY` | Run verification every N user turns (default: 1). |
| `--angel-max-history N` | `ANGEL_MAX_HISTORY` | Truncate history for Angel verification to last N messages (optional). |

### Tool Access Control

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--allowed-tools PATTERNS` | N/A | Comma-separated regex for allowed tools. |
| `--blocked-tools PATTERNS` | N/A | Comma-separated regex for blocked tools. |
| `--default-policy POLICY` | N/A | Default policy: 'allow' or 'deny'. |

### Routing Control

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--disable-routing-with-backend-ids` | `DISABLE_ROUTING_WITH_BACKEND_IDS=true` | Disable routing using explicit backend instance IDs (e.g. `openai.1:gpt-4`). |
| `--disable-routing-with-backend-names` | `DISABLE_ROUTING_WITH_BACKEND_NAMES=true` | Disable routing using backend names (e.g. `openai:gpt-4`). Implies disabling IDs. |
| `--disable-routing-with-only-model-names` | `DISABLE_ROUTING_WITH_ONLY_MODEL_NAMES=true` | Disable routing using only model names (e.g. `gpt-4`). |

### Auxiliary Request Routing

Routes auxiliary requests (title/summary generation) to alternative backends to reduce rate limiting pressure on the primary backend.

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--enable-auxiliary-routing` | `AUXILIARY_ROUTING_ENABLED=true` | Enable routing of auxiliary requests (title/summary generation) to an alternative backend. |
| `--auxiliary-routing-model MODEL` | `AUXILIARY_ROUTING_MODEL` | Model to use for auxiliary requests. Can be specified as `model` or fully qualified `backend:model` (e.g. `openrouter:gemini-1.5-flash`). |
| `--auxiliary-routing-max-messages N` | `AUXILIARY_ROUTING_MAX_MESSAGES` | Maximum message count for a request to be considered auxiliary (default: 3). |

### Pytest Integration

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--enable-pytest-compression` | `PYTEST_COMPRESSION_ENABLED=true` | Enable pytest output compression. |
| `--disable-pytest-compression` | `PYTEST_COMPRESSION_ENABLED=false` | Disable pytest output compression. |
| `--enable-pytest-full-suite-steering` | `PYTEST_FULL_SUITE_STEERING_ENABLED=true` | Enable steering for full pytest suite. |
| `--disable-pytest-full-suite-steering` | `PYTEST_FULL_SUITE_STEERING_ENABLED=false` | Disable steering for full pytest suite. |
| `--enable-pytest-context-saving` | N/A | Enable context saving rewrites. |
| `--test-execution-reminder-enabled` | `TEST_EXECUTION_REMINDER_ENABLED=true` | Enable test execution reminder. |
| `--no-test-execution-reminder-enabled` | `TEST_EXECUTION_REMINDER_ENABLED=false` | Disable test execution reminder. |
| N/A | `PYTEST_COMPRESSION_MIN_LINES` | Min lines for compression. |
| N/A | `PYTEST_FULL_SUITE_STEERING_MESSAGE` | Custom steering message. |
| N/A | `TEST_EXECUTION_REMINDER_MESSAGE` | Custom reminder message. |

### Empty Response Handling

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| N/A | `EMPTY_RESPONSE_HANDLING_ENABLED` | Enable empty response handling. |
| N/A | `EMPTY_RESPONSE_MAX_RETRIES` | Max retries for empty responses. |

### Rewriting

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| N/A | `REWRITING_ENABLED` | Enable content rewriting. |
| N/A | `REWRITING_CONFIG_PATH` | Path to rewriting configuration. |

### Random Model Replacement

See [Random Model Replacement Feature Guide](features/random-model-replacement.md) for detailed documentation.

 | CLI Argument | Environment Variable | Description |
 | :--- | :--- | :--- |
 | `--enable-replacement` | `REPLACEMENT_ENABLED=true` | Enable random model replacement. |
 | `--disable-replacement` | `REPLACEMENT_ENABLED=false` | Disable random model replacement. |
 | `--replacement-probability FLOAT` | `REPLACEMENT_PROBABILITY` | Probability of replacement (0.0 to 1.0). |
 | `--random-model-replacement-from-to FROM=TO` | `REPLACEMENT_RULES` | Conditional replacement rule. Can be specified multiple times. Format: `<from-model-name>=<to-model-name>`. `<from-model-name>` can be `*` (wildcard), `model-name` (partial match), or `backend:model` (exact match). `<to-model-name>` must be `backend:model`. |
 | `--replacement-backend-model BACKEND:MODEL` | `REPLACEMENT_BACKEND_MODEL` | **Deprecated**: Use `--random-model-replacement-from-to` instead. Backend and model to use for replacement (converted to wildcard rule). |
 | `--replacement-turn-count N` | `REPLACEMENT_TURN_COUNT` | Number of turns to stay on replacement. |

### Failure Handling

Configure automatic retry and failover behavior for backend errors. See [Failure Handling](features/failure-handling.md) for detailed documentation.

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--disable-failure-handling` | `DISABLE_FAILURE_HANDLING=1` | Disable automatic failure handling (retry/failover). |
| `--max-silent-wait SECONDS` | `FAILURE_HANDLING_MAX_SILENT_WAIT` | Max seconds to wait before failover (default: 30). |
| `--total-timeout-budget SECONDS` | `FAILURE_HANDLING_TOTAL_TIMEOUT_BUDGET` | Total timeout budget across failover attempts (default: 90). |
| `--keepalive-interval SECONDS` | `FAILURE_HANDLING_KEEPALIVE_INTERVAL` | SSE keepalive interval during waits (default: 8). |
| `--max-failover-hops N` | `FAILURE_HANDLING_MAX_FAILOVER_HOPS` | Max backend instances to try (default: 5). |
| `--min-retry-wait SECONDS` | `FAILURE_HANDLING_MIN_RETRY_WAIT` | Minimum retry wait time (default: 1). |

### Resilience Scoping

Control whether rate-limit and cooldown state is shared or isolated per client. See [Resilience Scoping](features/resilience-scoping.md) for detailed documentation.

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--resilience-personal-backends BACKEND[,BACKEND...]` | `RESILIENCE_PERSONAL_BACKEND_TYPES` | Force personal scoping for listed backend types (comma-separated or repeat the flag). |
| `--resilience-shared-backends BACKEND[,BACKEND...]` | `RESILIENCE_SHARED_BACKEND_TYPES` | Force shared scoping for listed backend types (comma-separated or repeat the flag). |

### Request Deduplication

Prevent duplicate requests from exhausting rate limits. See [Request Deduplication](features/request-deduplication.md) for detailed documentation.

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--request-dedup-window SECONDS` | `LLM_REQUEST_DEDUP_WINDOW` | Time window for duplicate detection (default: 3.0, set to 0 to disable). |
| `--disable-request-dedup` | N/A | Disable request deduplication entirely. |

### Other Features

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--fix-think-tags` | `FIX_THINK_TAGS_ENABLED=true` | Enable correction of `<think>` tags. |
| `--disable-binary-file-edit-steering` | N/A | Disable binary file edit steering (overrides config). |
| `--disable-dangerous-git-commands-protection` | `DANGEROUS_COMMAND_PREVENTION_ENABLED=false` | Disable dangerous command protection. |
| N/A | `DANGEROUS_COMMAND_STEERING_MESSAGE` | Custom message for dangerous commands. |
| N/A | `FIX_THINK_TAGS_STREAMING_BUFFER_SIZE` | Buffer size for think tag fix. |
| N/A | `GCP_PROJECT_ID` | Google Cloud Project ID (`GOOGLE_CLOUD_PROJECT`). |
| N/A | `GEMINI_CREDENTIALS_PATH` | Path to Gemini credentials JSON. |
| N/A | `DISABLE_HEALTH_CHECKS` | Disable health check endpoints. |
| N/A | `API_KEYS` | Comma-separated list of allowed API keys. |

### Single Sign-On (SSO)

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--enable-sso` | `SSO_ENABLED=true` | Enable SSO authentication. |
| `--sso-config PATH` | `SSO_CONFIG_FILE` | Path to SSO configuration file. |
| `--sso-provider NAME` | `SSO_PROVIDER` | Provider name (google, microsoft, github, linkedin, aws). |
| `--sso-auth-mode MODE` | `SSO_AUTH_MODE` | Authorization mode (single_user, enterprise). |
| `--disable-sso-captcha` | `SSO_CAPTCHA_ENABLED=false` | Disable SSO captcha protection. |

---

## Client Identity Override

| CLI Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--identity-user-agent VALUE` | `APP_USER_AGENT` | Override User-Agent header. |
| `--identity-url URL` | `APP_URL` | Override HTTP-Referer header. |
| `--identity-title TITLE` | `APP_TITLE` | Override X-Title header. |
| N/A | `APP_USER_AGENT_MODE` | Mode for User-Agent override. |
| N/A | `APP_URL_MODE` | Mode for URL override. |
| N/A | `APP_TITLE_MODE` | Mode for Title override. |

---

## Backend Debugging Overrides

*Restricted for internal development.*

| CLI Argument | Description |
| :--- | :--- |
| `--enable-cline-backend-debugging-override` | Enable Cline backend debugging. |
| `--enable-antigravity-backend-debugging-override` | Enable Antigravity backend debugging. |
| `--enable-gemini-oauth-free-backend-debugging-override` | Enable Gemini OAuth Free debugging. |
| `--enable-gemini-oauth-plan-backend-debugging-override` | Enable Gemini OAuth Plan debugging. |
| `--enable-qwen-oauth-backend-debugging-override` | Enable Qwen OAuth debugging. |
| `--enable-droid-path-fix` | Enable automatic path fixing for Droid agent with Antigravity OAuth backend. |
