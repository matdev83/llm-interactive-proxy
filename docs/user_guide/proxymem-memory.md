# ProxyMem: Cross-Session Memory

ProxyMem is a proxy-based memory layer that provides cross-session context persistence for LLM agents. By operating at the proxy layer, ProxyMem captures session data, generates structured summaries via LLM analysis, and enriches future requests with relevant historical context.

## Overview

ProxyMem operates through three main mechanisms:

1. **Session Capture**: Records session interactions as they pass through the proxy
2. **Session Analysis**: Uses a designated LLM to generate structured summaries after session completion
3. **Context Injection**: Enriches new session requests with relevant historical context from the database

### Benefits

- **Persistent Context**: Maintain awareness of prior work across sessions
- **Project-Scoped**: Memory is isolated per user and project
- **Automatic Summaries**: LLM-generated summaries capture goals, decisions, modified files, and remaining tasks
- **Privacy Controls**: Configurable redaction patterns and user/client deny lists

## Quick Start

### Enable Memory Feature

To use ProxyMem, you must first enable it globally:

```bash
# Enable memory feature
python -m src.core.cli --memory-available

# Enable with default memory on for all sessions
python -m src.core.cli --memory-available --memory-default-enabled
```

### Interactive Commands

Once memory is globally available, users can control it per-session:

| Command | Description |
|---------|-------------|
| `!/memory-on` | Enable memory capture for the current session |
| `!/memory-off` | Disable memory capture for the current session |
| `!/memory-status` | Show current memory state for the session |

## Configuration

### CLI Arguments

| Flag | Description | Default |
|------|-------------|---------|
| `--memory-available` | Enable the ProxyMem feature globally | `false` |
| `--memory-default-enabled` | Enable memory by default for new sessions | `false` |
| `--memory-summary-model` | Model for generating summaries (`backend:model`) | None |
| `--memory-context-model` | Model for context retrieval (`backend:model`) | None |
| `--memory-database-path` | Path to SQLite database | `./var/memory.sqlite3` |
| `--memory-session-timeout` | Minutes of inactivity before session completion | `30` |
| `--memory-retention-days` | Days to retain session summaries | `90` |
| `--memory-max-context-tokens` | Maximum tokens for injected context | `2000` |
| `--memory-single-user-mode` | Use a fixed user ID for all sessions | `false` |
| `--memory-fixed-user-id` | Fixed user ID (required when single-user-mode) | None |

### Environment Variables

All CLI flags can be set via environment variables with the `MEMORY_` prefix:

```bash
export MEMORY_AVAILABLE=true
export MEMORY_DEFAULT_ENABLED=true
export MEMORY_SUMMARY_MODEL=openai:gpt-4o-mini
export MEMORY_CONTEXT_MODEL=openai:gpt-4o-mini
export MEMORY_DATABASE_PATH=./var/memory.sqlite3
export MEMORY_SESSION_TIMEOUT=30
export MEMORY_RETENTION_DAYS=90
```

### Configuration File

Add memory settings to your `config.yaml`:

```yaml
memory:
  available: true
  default_enabled: false
  summary_model: "openai:gpt-4o-mini"
  context_model: "openai:gpt-4o-mini"
  database_path: "./var/memory.sqlite3"
  session_timeout_minutes: 30
  retention_days: 90
  max_context_tokens: 2000
  max_sessions_to_consider: 10
  context_relevance_threshold: 0.5
```

### Configuration Precedence

Configuration values are resolved in the following order (highest priority first):

1. CLI arguments
2. Environment variables
3. Configuration file
4. Default values

## How It Works

### Session Capture

When memory is enabled for a session:

1. User prompts are captured as they pass through the proxy
2. Assistant responses are captured after receiving from the backend
3. Interactions are buffered in memory (up to configurable limit)
4. Metadata (model, tokens, timestamps) is recorded with each interaction

### Session Completion

Sessions are marked complete when:

- **Timeout**: No activity for the configured timeout period (default: 30 minutes)
- **Explicit Close**: The client closes the connection

Upon completion, the session is queued for background analysis.

### Summary Generation

The summary generator:

1. Builds a transcript from captured interactions
2. Applies redaction patterns to remove sensitive data
3. Chunks large transcripts if they exceed limits
4. Calls the configured summary model with an XML-structured prompt
5. Validates the XML response against the schema
6. Parses and persists the summary to the database

Generated summaries include:

- **Title**: One-sentence description
- **Scope**: High-level area/component description
- **Goals**: Main objectives of the session
- **Key Decisions**: Important architectural or design decisions
- **Modified Files**: Files created, modified, or deleted
- **Git Operations**: Commits, branches, merges, etc.
- **Tests Run**: Test executions with pass/fail status
- **Errors**: Significant errors encountered
- **Remaining Tasks**: Open or blocked tasks
- **Completion Status**: `completed`, `partial`, or `abandoned`

### Context Injection

For new sessions with memory enabled:

1. Recent session summaries are retrieved for the user and project
2. Summaries are scored by relevance to the current prompt
3. High-relevance context is formatted and injected
4. Context appears as a virtual message before the first user message

Context injection only occurs once per session (on the first request).

## Privacy and Security

### Multi-User Isolation

- All memory operations require an authenticated `user_id`
- Summaries are scoped to `user_id` (and optionally `tenant_id`)
- Context retrieval only returns summaries for the requesting user
- Project scoping ensures cross-project isolation

### Redaction Patterns

Configure regex patterns to redact sensitive data:

```yaml
memory:
  redaction_patterns:
    - "(?i)(api[_-]?key|password|secret|token)\\s*[=:]\\s*['\"]?[^\\s'\"]*"
    - "Bearer\\s+[A-Za-z0-9_-]+"
```

Redaction is applied:
- Before calling the summary model
- Before persisting summaries
- Before logging any content

### User and Client Deny Lists

Block specific users or clients from memory:

```bash
# Via CLI
--memory-disable-user user123 --memory-disable-user user456
--memory-disable-client "Roo Cline"

# Via config file
memory:
  disabled_users:
    - "user123"
    - "user456"
  disabled_clients:
    - "Roo Cline"
```

### Single-User Mode

For personal deployments, bypass user authentication:

```bash
python -m src.core.cli --memory-available --memory-single-user-mode --memory-fixed-user-id "personal"
```

## Database Schema

ProxyMem uses SQLite for storage. The schema includes:

**session_summaries**: Stores all session summary data
- Indexed by `user_id`, `session_start`, `project_id`
- Full XML analysis preserved for debugging

**user_project_dirs**: Maps user+project_root pairs to stable project IDs

The database is automatically created on first use.

### Retention and Maintenance

- Sessions older than `retention_days` are automatically deleted
- Cleanup runs periodically (default: daily)
- No full transcripts are persisted—only structured summaries

## Custom Prompts

### Summary Prompt

Override the default summary prompt:

```bash
--memory-summary-prompt ./config/prompts/custom_summary.md
```

Available template variables:
- `{session_transcript}` - Full session transcript
- `{session_id}`, `{user_id}`, `{tenant_id}`
- `{project_id}`, `{project_root}`
- `{model}`, `{branch}`, `{head_sha}`
- `{analysis_timestamp}`
- `{summary_schema_version}`, `{summary_prompt_version}`
- `{max_tokens}`

### Context Prompt

Override the default context prompt:

```bash
--memory-context-prompt ./config/prompts/custom_context.md
```

Available template variables:
- `{user_prompt}` - Current user message
- `{session_summaries}` - Formatted historical summaries
- `{user_id}`, `{tenant_id}`
- `{project_id}`, `{project_root}`
- `{max_tokens}`

## Troubleshooting

### Memory Not Enabling

Check that:
1. `--memory-available` is set
2. User is not in `disabled_users` list
3. Client is not in `disabled_clients` list
4. Project root is discovered (if `require_project_discovery` is true)
5. User ID is present (unless in single-user mode)

### No Context Injected

Context may be skipped when:
- No historical sessions exist for the user/project
- No summaries meet the relevance threshold
- Project root is required but not discovered
- Context retrieval times out

Use `!/memory-status` to check the current state.

### Database Issues

If the database becomes corrupted:
1. Stop the proxy
2. Backup or remove `./var/memory.sqlite3`
3. Restart—schema will be recreated automatically

## Performance Considerations

### Buffer Limits

The capture buffer has a configurable maximum size (default: 10MB per session). If exceeded, the session is marked as partial and remaining interactions are dropped.

### Analysis Queue

Summary generation runs in a background queue with:
- Configurable queue size (default: 100)
- Per-job timeout (default: 30 seconds)
- Maximum concurrent analyses (default: 4)

Backpressure is applied when the queue is full—sessions may be dropped.

### Context Injection Overhead

Context retrieval adds latency to the first request of each session. To minimize impact:
- Keep `max_sessions_to_consider` reasonable (default: 10)
- Use a fast model for context generation
- Set appropriate `context_relevance_threshold`

## Related Documentation

- [CLI Parameters](cli-parameters.md) - Full CLI reference
- [Configuration](configuration.md) - Configuration file format
- [SSO Authentication](sso-authentication.md) - User identity integration

