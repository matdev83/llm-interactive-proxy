# Context Compaction

Intelligent context compaction reduces prompt size by replacing stale tool outputs with explicit stubs, helping stay within token limits while preserving conversation integrity.

## Overview

Context compaction is an automatic feature that identifies and removes superseded tool outputs from message histories before they are sent to LLM backends. When the LLM reads the same file multiple times, runs the same command, or performs repeated searches, compaction replaces older outputs with concise stubs that explain what was removed. This reduces token usage and helps prevent context window overflow while maintaining full transparency about what content was compacted.

The feature is particularly useful for:

- **Long-running agent conversations** that repeatedly access the same files
- **Code editing workflows** where the agent views the same file across multiple iterations
- **Debugging sessions** with repeated command executions
- **Large codebases** with frequent file reads

## How It Works

The compaction mechanism follows these steps:

1. **Detect Stale Tool Results**: Analyzes message history to identify tool outputs that have been superseded by newer results for the same resource. A "resource" is typically a file path, command signature, or search query.

2. **Track Resource Identity**: Correlates tool results across the conversation using normalized identifiers (file paths, command signatures, etc.). For file reading tools, pagination parameters (offset/limit) are included to distinguish reads of different file portions.

3. **Preserve Latest Results**: Always keeps the most recent tool result for each resource intact, ensuring the LLM has the latest state.

4. **Replace With Stubs**: Replaces older, stale outputs with explicit stub messages that clearly state what was removed and why:

   ```text
   [COMPACTED] Previous output for /path/to/file.py (2500 bytes) was removed because a newer result for this resource exists later in the conversation.
   ```

5. **Transparent to LLM**: Stub messages are visible to the LLM and explicitly explain the compaction, maintaining conversation context while reducing token count.

6. **Fail-Open**: If compaction encounters any error, the original message history is forwarded unchanged with appropriate logging.

## Session scope and the openai-codex backend

History context compaction (this feature: stale tool-output stubs in the message history) is evaluated **per proxy session**, not only per request.

- **Default**: For a new session, compaction follows global settings (`compaction.enabled`, `--enable-context-compaction`, and related options).
- **After Codex is used**: The first time a request in that session is routed to the **openai-codex** backend (including multi-instance names such as `openai-codex.1`), the proxy **turns off history context compaction for the rest of that session** and persists that in session state. A **single** `WARNING` is logged on that transition (not on every later request).
- **Later requests**: Even if you switch to another backend in the same session, history compaction **stays off** for that session once it has been disabled for Codex.
- **Not affected**: **Dynamic tool-output compression** (`dynamic_compression` in config) is a separate pipeline step and is **not** disabled by this rule.

For backend-specific notes, see [OpenAI Codex Backend](../backends/openai-codex.md#history-context-compaction).

## Configuration

### Basic Setup

Enable compaction with minimal configuration in `config.yaml`:

```yaml
compaction:
  enabled: true
  token_threshold: 100000  # Start compacting at 100K tokens
```

### Configuration Options

#### Required Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Master switch for compaction |
| `token_threshold` | int | `100000` | Estimated token count that triggers compaction |

#### Token Budgets

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `token_threshold` | int | `100000` | Threshold that triggers compaction. When the estimated token count exceeds this value, compaction is performed. |
| `max_tokens` | int | `150000` | Hard limit. If compaction cannot reduce the token count below this value, a warning is logged. |

**Token Budget Example:**

```yaml
compaction:
  enabled: true
  token_threshold: 80000   # Start compacting at 80K tokens
  max_tokens: 120000       # Warn if can't reduce below 120K
```

#### Per-Tool Policies

Control which tool types are eligible for compaction using categories and allow/deny lists.

**Available Tool Categories:**

- `file_read`: File reading operations (read_file, cat, file_read, etc.)
- `file_write`: File writing operations (write_file, edit_file, apply_diff, etc.)
- `view_file`: File viewing operations (view_file, view_file_outline, etc.)
- `command_execution`: Command execution (run_command, execute_command, bash, terminal, etc.)
- `search`: Search operations (grep_search, codebase_search, ripgrep, find, etc.)
- `list_directory`: Directory listing (list_dir, ls, etc.)
- `test_execution`: Test execution (run_pytest, run_tests, pytest, etc.)
- `other`: Any other tool type

**Policy Fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `allowed_tool_categories` | list[str] | `[]` | Categories eligible for compaction. Empty list = all categories allowed (except those in denied list). |
| `denied_tool_categories` | list[str] | `[]` | Categories never compacted. Takes precedence over allowed list. |

**Examples:**

Compact only file reads and searches:

```yaml
compaction:
  enabled: true
  token_threshold: 100000
  allowed_tool_categories:
    - file_read
    - view_file
    - search
```

Compact everything except file writes and command execution:

```yaml
compaction:
  enabled: true
  token_threshold: 100000
  denied_tool_categories:
    - file_write
    - command_execution
```

#### Additional Configuration Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_stubs_per_resource` | int | `1` | Maximum stub messages to keep per resource (future use) |
| `preserve_last_n_results` | int | `1` | Always keep this many recent results per resource |
| `stub_template` | string | Default template | Template for generating stub messages |
| `redact_resource_identifiers` | bool | `false` | Redact file paths/commands in stubs (see below) |

#### Redaction (Security vs Debuggability Trade-off)

The `redact_resource_identifiers` option controls whether sensitive information appears in compaction stubs.

**Default (recommended for most cases):**

```yaml
compaction:
  enabled: true
  redact_resource_identifiers: false  # Keep paths visible for debugging
```

**Security-sensitive environments:**

```yaml
compaction:
  enabled: true
  redact_resource_identifiers: true  # Redact paths containing secrets
```

**Trade-off Summary:**

| Setting | Security | Debuggability | Best For |
|---------|----------|----------------|----------|
| `false` (default) | Medium | High | Development, debugging, non-sensitive environments |
| `true` | High | Medium | Production with sensitive file paths or API keys |

**What gets redacted:**

When enabled, stubs apply the project's `redact_text()` function to resource identifiers, which redacts:
- API keys matching patterns like `ak-ant...`, `sk-...`, `ak-proj...`
- Sensitive strings detected by the redaction rules
- File paths containing these patterns

**Example outputs:**

With `redact_resource_identifiers: false`:

```text
[COMPACTED] Previous output for /home/user/project/config.py (2500 bytes) was removed because a newer result for this resource exists later in the conversation.
```

With `redact_resource_identifiers: true`:

```text
[COMPACTED] Previous output for /home/user/***/***.py (2500 bytes) was removed because a newer result for this resource exists later in the conversation.
```

### CLI Overrides

Enable or disable compaction via command line:

```bash
# Enable compaction regardless of config
./.venv/Scripts/python.exe -m src.core.cli --enable-context-compaction

# Override doesn't exist for disabling; use config instead
```

**Note:** CLI override currently only supports enabling the feature. Use `config.yaml` to disable compaction.

### Environment Variables

Currently, no environment variables are supported for compaction configuration. All settings must be specified in `config.yaml`.

## Observability

### Metrics (via Structured Logs)

When compaction occurs, metrics are included in structured logs:

```json
{
  "compacted_messages": 5,
  "bytes_saved": 2500,
  "tokens_saved_estimate": 625,
  "original_messages": 12,
  "was_compacted": true,
  "failed_open": false,
  "stale_resources": "view_file:/a.py,view_file:/b.py"
}
```

**Available Metrics:**

| Metric | Type | Description |
|--------|------|-------------|
| `compaction_messages_compacted` | int | Number of messages replaced with stubs |
| `compaction_bytes_saved` | int | Approximate bytes reduced by compaction |
| `compaction_tokens_saved_estimate` | int | Estimated tokens saved (roughly bytes / 4) |
| `compaction_original_count` | int | Number of messages before compaction |
| `compaction_stale_resources_count` | int | Number of unique resources detected as stale |
| `compaction_failed_open` | int | `1` if compaction failed and returned original messages, `0` otherwise |

**Example Log Output:**

```text
2025-12-28 23:40:39 [INFO] Compacted conversation history (5 messages, 2500 bytes saved, ~625 tokens saved)
```

**Structured Log Fields:**

```python
{
    "compacted_count": 5,
    "bytes_saved": 2500,
    "tokens_saved_estimate": 625,
    "original_message_count": 12,
    "was_compacted": true,
    "failed_open": false,
    "stale_resources": "view_file:/a.py,view_file:/b.py"
}
```

### Overflow Warnings

If compaction cannot reduce the token count below `max_tokens`, a warning is logged:

```text
2025-12-28 23:40:39 [WARNING] Context compaction completed but token estimate (125000) still exceeds max_tokens (120000)
```

**What the warning means:**

- Compaction ran and removed all possible stale tool outputs
- The resulting token count is still above the `max_tokens` limit
- The request will proceed, but may risk context window overflow at the backend

**Actions to take when warnings appear:**

1. **Increase `max_tokens`**: Allow a higher threshold if the backend supports it
2. **Decrease `token_threshold`**: Trigger compaction earlier to allow more aggressive reduction
3. **Add tools to `allowed_tool_categories`**: Enable compaction for more tool types
4. **Review conversation size**: Consider session management or manual history pruning
5. **Check backend context limits**: Ensure `max_tokens` matches the backend's actual limits

**Example configuration to address warnings:**

```yaml
compaction:
  enabled: true
  token_threshold: 60000   # Start compacting earlier
  max_tokens: 140000        # Higher limit if backend supports it
```

### CBOR Wire Captures

Compaction is transparent in wire captures:

- Wire captures record the **post-compaction** request exactly as sent to the backend
- Stubs are visible in the captured messages
- Original content is not recorded (it was already replaced)
- Use wire captures to verify what the backend actually received

**Inspecting compaction in wire captures:**

```bash
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py var/wire_captures_cbor/<capture-file>
```

Look for stub messages like:

```text
role: tool
content: "[COMPACTED] Previous output for /path/file.py (2500 bytes) was removed..."
```

## Troubleshooting

### "Overflow risk" Warnings

**Symptom:** You see warnings about token estimates exceeding `max_tokens` after compaction.

**Cause:** Compaction removed all stale tool outputs, but the remaining messages still exceed the hard limit.

**Solutions:**

1. **Increase `max_tokens` limit** (if backend supports it):

   ```yaml
   compaction:
     enabled: true
     token_threshold: 100000
     max_tokens: 180000  # Increased from 150000
   ```

2. **Decrease `token_threshold`** to start compacting earlier:

   ```yaml
   compaction:
     enabled: true
     token_threshold: 70000  # Decreased from 100000
     max_tokens: 150000
   ```

3. **Add more tools to `allowed_tool_categories`**:

   ```yaml
   compaction:
     enabled: true
     allowed_tool_categories:
       - file_read
       - view_file
       - search
       - test_execution  # Add this
       - list_directory  # Add this
   ```

4. **Review and reduce conversation size**:
   - Implement session management limits
   - Consider manually summarizing long conversations
   - Use tools that avoid repeated large file reads

5. **Verify backend context limits**: Ensure `max_tokens` matches your backend's actual context window size.

### Performance Considerations

**Typical Performance Impact:**

- **Latency**: Compaction adds <10ms p95 latency (typically 1-5ms)
- **Token estimation**: Uses character count / 4 approximation (fast, no blocking operations)
- **Resource tracking**: O(n) where n is the number of tool messages
- **Memory**: Minimal overhead; only tracks resource identities, not content

**Why it's fast:**

- Token estimation uses simple string length division
- Resource identity extraction uses cached lookups
- No external API calls or blocking I/O
- Early exit if no stale outputs detected

**When to disable compaction:**

- If every millisecond matters and compaction overhead is unacceptable
- If you never exceed token thresholds
- If your conversations never have repeated tool operations

### Debugging Compaction Decisions

**Check logs for compaction events:**

```bash
# Enable DEBUG logging to see detailed compaction information
# In config.yaml:
logging:
  level: "DEBUG"

# Then look for messages like:
# "History compaction triggered: token_estimate=110000 > threshold=100000"
# "Detected 3 stale resources: view_file:/a.py, read_file:/b.py, grep_search:pattern"
```

```yaml

**Verify which resources are being compacted:**

Review structured log output for the `stale_resources` field:
```json
{
  "stale_resources": "view_file:/src/main.py,view_file:/src/util.py,read_file:config.json"
}
```

**Use `redact_resource_identifiers: false` for debugging:**

```yaml
compaction:
  enabled: true
  redact_resource_identifiers: false  # Ensure full paths are visible
```

**Example debug session:**

1. Enable DEBUG logging
2. Set `redact_resource_identifiers: false`
3. Run your conversation
4. Look for log messages showing:
   - Which resources were detected as stale
   - How many bytes/tokens were saved
   - Which tool results were compacted

**Verify stub content:**

Inspect wire captures or logs to see stub messages:

```bash
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py <capture-file>
```

Look for tool result messages with `[COMPACTED]` prefix.

### Compaction Not Running

**Symptom:** Compaction appears enabled but no compaction occurs.

**Check list:**

1. **Verify enabled flag:**

   ```yaml
   compaction:
     enabled: true  # Must be explicitly true
   ```

2. **Check token threshold:**

   ```bash
   # Look for log messages like:
   # "History compaction skipped: token_estimate=50000 < threshold=100000"
   ```

   If you're under the threshold, compaction won't run. Try lowering `token_threshold` for testing.

3. **Verify stale outputs exist:**
   - Compaction only replaces superseded tool outputs
   - If each resource appears only once, there's nothing to compact
   - Check for repeated file reads, searches, or commands

4. **Check allow/deny policies:**

   ```yaml
   compaction:
     allowed_tool_categories: []  # Empty = allow all (except denied)
     denied_tool_categories: []   # Empty = deny none
   ```

   If tools are in `denied_tool_categories`, they won't be compacted.

5. **Look for error logs:**

   ```bash
   # Search for:
   # "History compaction failed"
   ```

   If compaction fails, it fails-open and continues with original messages.

## Usage Examples

### Example 1: Basic Setup

Minimal configuration to enable compaction with default settings:

```yaml
# config.yaml
compaction:
  enabled: true
  token_threshold: 100000  # Start compacting at 100K tokens
```

**Behavior:**
- Compacts all tool categories except file writes and command execution (default `CompactionConfig.default()` policy)
- Shows full file paths in stubs (`redact_resource_identifiers: false`)
- Warns if can't reduce below 150K tokens

### Example 2: Production Security Setup

Configuration for production environments with sensitive file paths:

```yaml
# config.yaml
compaction:
  enabled: true
  token_threshold: 100000
  max_tokens: 150000
  redact_resource_identifiers: true  # Redact sensitive paths

  # Compact only safe operations
  allowed_tool_categories:
    - file_read
    - view_file
    - search
    - test_execution

  # Never compact writes or commands
  denied_tool_categories:
    - file_write
    - command_execution
```

**Behavior:**
- Only compacts file reads, views, searches, and test execution
- Never compacts file writes or command execution
- Redacts API keys and sensitive strings in stubs
- Suitable for environments with secrets in file paths

### Example 3: Aggressive Compaction

Configuration for large codebases with frequent repeated operations:

```yaml
# config.yaml
compaction:
  enabled: true
  token_threshold: 50000   # Start compacting earlier (50K)
  max_tokens: 100000       # Warn at 100K instead of 150K

  # Compact nearly everything except writes
  allowed_tool_categories:
    - file_read
    - view_file
    - search
    - list_directory
    - test_execution

  denied_tool_categories:
    - file_write
    # command_execution not in denied list, so it will be compacted
```

**Behavior:**
- Compacts most tool types, including command execution
- Starts compacting at 50K tokens (more aggressive)
- Warns earlier if compaction can't reduce size
- Good for large codebases with many repeated reads

### Example 4: Selective Tool Compaction

Configuration targeting specific tool categories only:

```yaml
# config.yaml
compaction:
  enabled: true
  token_threshold: 100000

  # Only compact file reading operations
  allowed_tool_categories:
    - file_read
    - view_file

  # Everything else is preserved
  denied_tool_categories:
    - command_execution
    - test_execution
    - search
    - list_directory
```

**Behavior:**
- Only compacts file read operations (most common case)
- Preserves all command execution, tests, searches, and directory listings
- Useful when you want to reduce file read duplication but preserve command history

### Example 5: Custom Stub Template

Customize stub message format (advanced):

```yaml
# config.yaml
compaction:
  enabled: true
  token_threshold: 100000
  stub_template: |
    [COMPACTED: {resource}] Removed {size} bytes of previous output.
    A more recent result for this resource is available later in the conversation.
```

**Behavior:**
- Uses custom stub template with formatted output
- Shows resource identifier and byte size
- Explains that a newer result exists

## Use Cases

### Long-Running Agent Conversations

When agents work on complex tasks over multiple turns, they often read the same files repeatedly. Context compaction automatically removes older file reads, keeping only the most recent version:

```yaml
compaction:
  enabled: true
  token_threshold: 100000
```

**Benefits:**
- Reduces token usage by 20-40% in long conversations
- Prevents context window overflow
- Maintains conversation continuity

### Code Editing Workflows

During code editing sessions, agents frequently view the same files across iterations. Compaction ensures only the latest file state is sent:

```yaml
compaction:
  enabled: true
  token_threshold: 80000
  allowed_tool_categories:
    - file_read
    - view_file
```

**Benefits:**
- Keeps context focused on current file state
- Reduces redundant file content
- Improves agent decision-making with fresher data

### Debugging Sessions

Debugging often involves repeated command executions and file reads. Compaction preserves command outputs while removing duplicate file reads:

```yaml
compaction:
  enabled: true
  token_threshold: 100000
  denied_tool_categories:
    - command_execution  # Preserve all command outputs
```

**Benefits:**
- Preserves command execution history
- Removes duplicate file reads
- Maintains debugging context

### Large Codebase Exploration

When exploring large codebases, agents read many files. Compaction helps manage context size:

```yaml
compaction:
  enabled: true
  token_threshold: 50000  # Start compacting earlier
  max_tokens: 100000
```

**Benefits:**
- Allows exploration of larger codebases
- Prevents context overflow
- Maintains exploration context

## Best Practices

1. **Start with conservative thresholds**: Begin with `token_threshold: 100000` and `max_tokens: 150000`, then adjust based on your needs.

2. **Monitor overflow warnings**: Review logs regularly for overflow warnings and adjust thresholds accordingly.

3. **Keep redaction OFF for debugging**: Use `redact_resource_identifiers: false` (default) during development to easily identify which resources are being compacted.

4. **Enable redaction in production**: If your file paths contain sensitive information (API keys, secrets), enable `redact_resource_identifiers: true` in production.

5. **Review metrics regularly**: Check `compaction_bytes_saved` and `compaction_tokens_saved_estimate` metrics to measure effectiveness.

6. **Test before deploying**: Enable DEBUG logging and verify compaction behavior in a non-production environment first.

7. **Combine with session management**: For very long conversations, use session management alongside compaction to effectively manage context size.

8. **Align `max_tokens` with backend limits**: Ensure your `max_tokens` setting matches or is slightly below your backend's actual context window size.

9. **Don't compact writes by default**: File write operations should typically be preserved (included in default `denied_tool_categories`).

10. **Monitor performance impact**: While compaction is fast (<10ms), verify that it doesn't impact your specific use case's latency requirements.

## FAQ

### Q: Will compaction remove important context?

A: No. Only older, superseded tool outputs are compacted. The most recent result for each resource is always preserved. User messages, assistant messages, system prompts, and unique tool results are never compacted.

### Q: Can the LLM still see what was compacted?

A: Yes. Stubs explicitly state what was removed and why. For example:

```text
[COMPACTED] Previous output for /path/file.py (2500 bytes) was removed because a newer result for this resource exists later in the conversation.
```

The LLM can understand that a previous version existed and was superseded.

### Q: Does compaction affect wire captures?

A: Wire captures record the post-compaction request exactly as sent to the backend. Stubs are visible in captures, but the original compacted content is not (since it was replaced before the request was sent). This gives you an accurate record of what the backend received.

### Q: What happens if compaction fails?

A: Fail-open: Original messages are forwarded unchanged, and an error is logged. This ensures that compaction errors never block legitimate requests.

### Q: How accurate is the token estimate?

A: Token estimation uses character count / 4 as an approximation. This is fast and reasonably accurate for most text (typically within 20% of actual token count). The estimate is sufficient for triggering compaction and warning about overflow, but not precise enough for cost calculations.

### Q: Can I compact command execution results?

A: By default, no. Command execution is in the `denied_tool_categories` list because command outputs often contain unique information that shouldn't be discarded. However, you can remove it from the denied list if you're sure you want to compact command results.

### Q: How are file reads distinguished?

A: File reads are tracked by their normalized file path. For pagination-aware tools (like `view_file` with `StartLine`/`EndLine`), pagination parameters are included as secondary keys to distinguish reads of different file portions.

### Q: What if two files have the same name but different paths?

A: File paths are fully normalized (forward slashes, no trailing slashes, lowercase drive letters on Windows). Different paths are treated as different resources. Only reads of the exact same path are considered duplicates.

### Q: Can I see which resources were compacted?

A: Yes. Check structured logs for the `stale_resources` field, which lists the resources that were detected as stale and compacted. You can also inspect wire captures to see stub messages with `[COMPACTED]` prefixes.

### Q: Will compaction work with my custom tools?

A: Yes. Compaction works with any tool that produces result messages with `role="tool"` and a `tool_call_id`. Tools are categorized by name patterns, and unknown tools fall into the `other` category.

### Q: How does compaction interact with context window enforcement?

A: These are complementary features. Context window enforcement blocks requests that exceed model limits, while compaction actively reduces token usage by removing stale content. Use both together for robust context management.

### Q: Can I disable compaction for specific backends?

A: Not directly. Compaction applies globally based on the `enabled` flag in `config.yaml`. If you need backend-specific behavior, consider using separate proxy instances with different configurations.

### Q: What happens if I have both `allowed_tool_categories` and `denied_tool_categories`?

A: The denied list takes precedence. If a category is in both lists, it will not be compacted. This provides a safety mechanism: denied categories are never compacted, regardless of the allowed list.

### Q: Is compaction safe for production use?

A: Yes. Compaction is designed with fail-open behavior: if anything goes wrong, the original messages are used. However, test thoroughly in your environment first and monitor metrics to ensure it's effective for your use case.

## Related Features

- [Context Window Enforcement](context-window-enforcement.md) - Enforce per-model context window limits
- [Session Management](session-management.md) - Intelligent session continuity and history management
- [Wire Captures](../debugging/cbor-capture.md) - Inspect requests and responses with CBOR captures
- [Monitoring Overview](monitoring-overview.md) - Track compaction metrics and performance
