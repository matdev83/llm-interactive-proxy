# Dynamic Tool Output Compression

Intelligently compress verbose tool outputs during request preparation to conserve context window space while preserving essential information for LLM reasoning.

## Overview

Dynamic Tool Output Compression is an advanced feature that applies strategy-based compression to `role="tool"` outputs during backend request preparation. Unlike simple truncation, it uses content-aware strategies to reduce token usage while maintaining the semantic information the LLM needs for effective reasoning.

The compression pipeline runs **after** history compaction and **before** backend translation, ensuring:
1. Stale content is already removed by compaction
2. Remaining tool outputs are optimized for the specific backend
3. Token savings are maximized without information loss

**Key Characteristics:**
- **Disabled by default** - Must be explicitly enabled
- **Deterministic precedence** - CLI > Environment > YAML > Defaults
- **Content-aware strategies** - Different compression for different output types
- **Observable and recoverable** - Full telemetry and optional artifact recovery
- **Extensible** - Supports declarative rule customization

## When to Use Dynamic Compression

Use dynamic compression when:

- **Working with large codebases** - File reads, directory listings, and searches generate verbose output
- **Running extensive test suites** - Pytest and build outputs can consume thousands of tokens
- **Processing structured data** - JSON logs, XML configs, and similar formats are often repetitive
- **Debugging complex issues** - Diagnostic outputs from multiple tools accumulate quickly
- **Managing long sessions** - Conversations spanning many turns with repeated tool usage

**Comparison with Related Features:**

| Feature | Stage | Scope | Purpose |
|---------|-------|-------|---------|
| **Context Compaction** | Before request prep | Entire history | Remove stale tool results |
| **Dynamic Compression** | During request prep | Individual tool outputs | Compress content while preserving meaning |
| **Backend Truncation** | Backend-specific | Per-backend | Legacy truncation (deprecated) |

## Configuration

### Configuration Precedence

Configuration is resolved in the following order (highest to lowest priority):

1. **CLI Arguments** - Command-line flags override everything
2. **Environment Variables** - Shell environment variables
3. **YAML Configuration** - Config file settings
4. **Built-in Defaults** - Conservative defaults if nothing else is specified

### Quick Start

Enable with minimal configuration:

```yaml
dynamic_compression:
  enabled: true
```

Or via CLI:

```bash
python -m src.core.cli --enable-dynamic-compression
```

### Complete Configuration Reference

```yaml
dynamic_compression:
  # Master switch
  enabled: false

  # Compression levels
  level: "conservative"         # Base level: conservative | balanced | aggressive
  max_level: "aggressive"       # Escalation ceiling during budget pressure

  # Size thresholds
  min_bytes: 1024               # Skip outputs smaller than this (bytes)

  # Telemetry and observability
  telemetry_include_content_hashes: true  # Include correlation-safe hashes (no raw content)

  # Alerting on compression issues
  alerts:
    enabled: true
    failure_threshold: 5        # Warn after N method failures within window
    fallback_threshold: 8       # Warn after N fallback/skips within window
    window_seconds: 300         # Observation window for alerts
    cooldown_seconds: 300       # Rate-limit alert emissions

  # Recovery artifacts for debugging
  recovery:
    mode: "never"               # When to save originals: never | failures | always
    min_original_bytes: 4096    # Minimum original size to qualify for recovery
    min_saved_bytes: 2048       # Minimum bytes saved to qualify for recovery
    max_artifact_bytes: 262144  # Maximum artifact size (256 KB)
    max_artifacts: 128          # Maximum artifacts to retain
    retention_seconds: 86400    # Artifact retention (24 hours)
    storage_dir: "var/compression_recovery"
    hint_in_text: false         # Append recovery handle hint to plain text

  # Tool category exclusions (skip compression for these categories)
  disable_categories: []        # e.g., ["search", "command_execution"]

  # Compression method exclusions
  disable_methods: []           # e.g., ["line_dedupe", "ansi_normalization"]

  # Specific tool exclusions
  disable_tools: []             # e.g., ["shell", "bash", "run_command"]

  # Command prefix exclusions
  disable_command_prefixes: []  # e.g., ["git diff --stat", "pytest -v"]

  # Listing/search/read strategy tuning
  noise_directories: ["node_modules", ".git", "target", "__pycache__", ".venv", "vendor"]
  search_context_lines: 2
  search_max_matches_per_file: 8
  search_max_total_groups: 100
  search_max_line_length: 240

  # File detail mode configuration
  file_detail_mode: "auto"             # auto | full | structure | signatures
  file_detail_fallback_mode: "full"    # full | structure | signatures
  file_detail_auto_full_max_lines: 120
  file_detail_auto_structure_max_lines: 280
  file_detail_include_line_numbers: false
  file_detail_max_lines: null          # Head-like cap when set
  file_detail_last_n_lines: null       # Tail-like cap when set

  # Pattern-based rules (8-stage text pipeline)
  output_pattern_rules: []
  output_pattern_regex_timeout_ms: 25

  # Declarative operator-defined rules
  declarative_rules: []
  declarative_rule_files: []        # Extra YAML/JSON files with rules
  declarative_regex_timeout_ms: 25  # Guard timeout for regex evaluation

  # Diff output controls
  diff_max_lines_per_hunk: 100
  diff_max_total_lines: 500
```

### CLI Flags

| Flag | Description |
|------|-------------|
| `--enable-dynamic-compression` | Enable dynamic compression |
| `--dynamic-compression-level LEVEL` | Set base level: `conservative`, `balanced`, `aggressive` |
| `--dynamic-compression-max-level LEVEL` | Set escalation ceiling |
| `--dynamic-compression-min-bytes BYTES` | Minimum output size for compression |
| `--dynamic-compression-file-detail-include-line-numbers` | Include line numbers in file detail output |
| `--dynamic-compression-file-detail-exclude-line-numbers` | Exclude line numbers |
| `--dynamic-compression-disable-categories CSV` | Comma-separated categories to bypass |
| `--dynamic-compression-disable-methods CSV` | Comma-separated methods to disable |
| `--dynamic-compression-disable-tools CSV` | Comma-separated tool names to bypass |
| `--dynamic-compression-disable-command-prefixes CSV` | Comma-separated command prefixes to bypass |

### Compression Levels

The `level` setting controls compression aggressiveness:

| Level | Description | Best For |
|-------|-------------|----------|
| `conservative` | Minimal compression, maximum preservation | Debugging, critical outputs |
| `balanced` | Moderate compression, good token savings | General development work |
| `aggressive` | Maximum compression, may reduce detail | Large outputs, routine operations |

The `max_level` setting allows escalation during budget pressure. When context limits are tight, the system can temporarily increase compression up to `max_level`.

## Compression Strategies

Dynamic compression applies different strategies based on content type:

### 1. ANSI Normalization

Converts ANSI color codes to a normalized form, reducing variation while preserving visual structure.

**Applies to:** Terminal output with color codes

### 2. Line Deduplication

Removes adjacent duplicate lines while preserving count information.

**Before:**
```
Running test_foo...
PASS
Running test_bar...
PASS
Running test_baz...
PASS
```

**After:**
```
Running test_foo... PASS
Running test_bar... PASS
Running test_baz... PASS
[3 similar results grouped]
```

### 3. Unified Diff Compaction

Compresses git-style diff output by:
- Removing context lines beyond configured limits
- Summarizing large hunks
- Preserving all actual changes

### 4. Directory/Listing Summaries

Converts verbose directory listings to structured summaries:

**Before:**
```
drwxr-xr-x  5 user group  4096 Jan 15 10:23 src
drwxr-xr-x  3 user group  4096 Jan 15 10:23 tests
-rw-r--r--  1 user group  2341 Jan 15 10:23 README.md
-rw-r--r--  1 user group   892 Jan 15 10:23 setup.py
```

**After:**
```
Directories: src/, tests/
Files: README.md (2.3K), setup.py (892B)
```

### 5. Search Result Grouping

Groups search results by file and limits matches per file:

**Configuration:**
- `search_max_matches_per_file: 8` - Max matches shown per file
- `search_max_total_groups: 100` - Max file groups overall
- `search_context_lines: 2` - Context lines per match

### 6. File Read Detail Reduction

Compresses file content based on `file_detail_mode`:

| Mode | Behavior |
|------|----------|
| `full` | Entire file content (respects max_lines) |
| `structure` | Class/function signatures only |
| `signatures` | Function signatures only |
| `auto` | Chooses based on file size and context |

### 7. Failure-Focused Test Reduction

For pytest/build output, keeps only failures and errors:

**Before:**
```
test_example.py::test_one PASSED
test_example.py::test_two PASSED
... 50 more PASSED ...
test_example.py::test_fail FAILED
AssertionError: expected 5, got 3
test_example.py::test_error ERROR
NameError: name 'undefined' is not defined
```

**After:**
```
[50 passed tests omitted]
test_example.py::test_fail FAILED
AssertionError: expected 5, got 3
test_example.py::test_error ERROR
NameError: name 'undefined' is not defined
```

### 8. JSON/NDJSON Structural Summarization

Compresses JSON/NDJSON by:
- Truncating large arrays (showing first/last N items)
- Summarizing repetitive structures
- Preserving all keys and unique values

### 9. XML Safeguards

Parseability-preserving compression for XML:
- Maintains valid XML structure
- Truncates large text nodes
- Preserves attribute values

### 10. Noisy Log Dedupe

For log output with volatile fields (timestamps, PIDs):
- Normalizes variable fields
- Deduplicates similar log lines
- Preserves unique messages

### 11. Sensitive Field Projection

For env/cloud-style outputs:
- Redacts sensitive values (API keys, passwords)
- Preserves key names and structure
- Maintains non-sensitive values

## Use Cases and Examples

### Use Case 1: Large Codebase Navigation

**Scenario:** Agent is exploring a large codebase with many file reads.

**Configuration:**
```yaml
dynamic_compression:
  enabled: true
  level: "balanced"
  file_detail_mode: "auto"
  file_detail_auto_full_max_lines: 120
  file_detail_auto_structure_max_lines: 280
```

**Result:** File reads automatically adapt - small files shown in full, large files show structure/skeleton.

### Use Case 2: Test-Driven Development

**Scenario:** Running large test suites frequently during development.

**Configuration:**
```yaml
dynamic_compression:
  enabled: true
  level: "aggressive"
  disable_command_prefixes: []  # Allow compression on all test commands
```

**Result:** Only failing tests and errors are shown, saving thousands of tokens per run.

### Use Case 3: Log Analysis

**Scenario:** Analyzing application logs with repetitive patterns.

**Configuration:**
```yaml
dynamic_compression:
  enabled: true
  level: "aggressive"
  disable_categories: []  # Allow on all outputs
```

**Result:** Log deduplication and volatile-field normalization dramatically reduce log volume.

### Use Case 4: Selective Compression

**Scenario:** Compress most outputs but preserve full search results.

**Configuration:**
```yaml
dynamic_compression:
  enabled: true
  level: "balanced"
  disable_categories:
    - "search"  # Skip compression for search outputs
```

**Result:** Search results remain complete; other outputs are compressed.

### Use Case 5: Debugging with Recovery

**Scenario:** Need to debug compression behavior without losing original data.

**Configuration:**
```yaml
dynamic_compression:
  enabled: true
  level: "balanced"
  recovery:
    mode: "always"
    storage_dir: "var/compression_debug"
    hint_in_text: true
```

**Result:** All compressed outputs have recovery handles; originals stored for inspection.

## Declarative Rules (Advanced)

For advanced use cases, you can define custom compression rules:

```yaml
dynamic_compression:
  declarative_rules:
    - name: "custom_log_compression"
      priority: 100
      when:
        tool_name: "shell"
        command_prefix: "tail -f"
        min_bytes: 2048
      pipeline:
        - "ansi_normalize"
        - "line_dedupe"
        - "volatile_field_normalize"
    
    - name: "preserve_important_json"
      priority: 50
      when:
        content_types: ["application/json"]
        command_prefix: "cat config.json"
      pipeline:
        - "identity"  # No compression
```

Rules support an 8-stage filter pipeline and precedence override.

## Observability

### Telemetry Records

Each compression produces a telemetry record with:

- Original and compressed sizes
- Compression ratio
- Methods applied
- Content type
- Tool/command information

### Alerts

The system can alert on:
- **Method failures** - When a compression method repeatedly fails
- **Fallbacks** - When compression falls back to less effective methods

Configure thresholds and windows in the `alerts` section.

### Recovery Artifacts

When `recovery.mode` is not `never`, original outputs are stored as artifacts:

```bash
# List recovery artifacts
ls var/compression_recovery/

# Inspect a specific artifact
cat var/compression_recovery/abc123.original.json
```

## Troubleshooting

### Compression Not Working

1. Verify feature is enabled: check `dynamic_compression.enabled`
2. Check size thresholds: output may be below `min_bytes`
3. Review exclusions: tool may be in `disable_tools` or `disable_categories`
4. Check logs for compression telemetry

### Too Much Information Lost

1. Reduce compression level: `level: "conservative"`
2. Exclude specific tools: add to `disable_tools`
3. Enable recovery: `recovery.mode: "always"`
4. Review and adjust `file_detail_mode` settings

### Performance Concerns

1. Compression adds minimal overhead (<10ms per output)
2. Disable for specific high-frequency tools
3. Adjust `min_bytes` to skip small outputs
4. Use `disable_methods` to skip expensive methods

### Legacy Compatibility

Legacy Gemini connector truncation controls (`GEMINI_TOOL_OUTPUT_TRUNCATE_*` and backend `tool_output_truncate_*` extras) are deprecated but still functional:

## Related Features

- [Context Compaction](context-compaction.md) - Remove stale tool results before compression
- [Pytest Context Saving](pytest-context-saving.md) - Rewrite pytest commands at the tool-call level to inject `-r fE` and `-q` flags for compact output (complementary, works *before* request preparation)
- [Token Saving](token-saving.md) - How compaction and dynamic compression combine for lower context usage
- [Context Window Enforcement](context-window-enforcement.md) - Enforce per-model context limits
- [Session Management](session-management.md) - Session handling with compression awareness

## See Also

- [CLI Parameters Reference](../cli-parameters.md) - Complete CLI flag documentation
- [Configuration Guide](../configuration.md) - General configuration patterns
