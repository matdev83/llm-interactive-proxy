# Token Saving Guide

Token usage in long-running agent sessions usually grows for two distinct reasons:

1. **History bloat**: older tool results remain in the conversation even after newer results supersede them.
2. **Output verbosity**: current tool outputs (tests, logs, search, file reads, diffs) are often much larger than what the model needs.

LLM Interactive Proxy addresses both with separate, complementary features.

## Two Complementary Mechanisms

### 1) Context Compaction (history-level)

Context Compaction scans message history and replaces stale tool outputs with explicit stubs when newer results for the same resource exist later in the conversation.

- Runs before backend request translation
- Preserves transparency by keeping clear replacement stubs
- Reduces repeated historical payload in long sessions

Read more: [Context Compaction](context-compaction.md)

### 2) Dynamic Tool Output Compression (output-level)

Dynamic Tool Output Compression reduces the size of the remaining tool outputs during request preparation using strategy-based, content-aware compression.

- Runs after compaction
- Targets verbosity in active tool outputs
- Preserves useful signal while reducing token footprint

Read more: [Dynamic Tool Output Compression](dynamic-tool-output-compression.md)

## Recommended Mental Model

- **Compaction** decides what old content is no longer needed.
- **Dynamic compression** optimizes the content that is still needed.

In short: compaction handles stale history; dynamic compression handles verbose current outputs.

## Configuration

Token-saving behavior is controlled by the underlying features, not a single switch:

- **Context Compaction** — enable and tune via [Context Compaction](context-compaction.md) (YAML, env, or CLI as documented there).
- **Dynamic Tool Output Compression** — enable via `dynamic_compression` and related settings in [Dynamic Tool Output Compression](dynamic-tool-output-compression.md).

## Usage Examples

- **Compaction only:** Turn on context compaction when the same tools or files appear often across turns; see the compaction guide for exact flags and config keys.
- **Dynamic compression only:** Set `dynamic_compression.enabled: true` (or the matching CLI flags) when individual tool outputs are large; see the dynamic compression guide for levels and exclusions.
- **Both:** Enable compaction and dynamic compression together for long agent sessions with repeated tool use and heavy outputs.

## Which One Should I Enable?

- Enable **Context Compaction** when sessions revisit the same files, commands, or searches repeatedly.
- Enable **Dynamic Compression** when current tool outputs are large (tests, logs, grep/search, file listings, structured data).
- Enable **both** for the strongest token-control behavior in long coding/debugging workflows.

## Related Documentation

- [Context Compaction](context-compaction.md)
- [Dynamic Tool Output Compression](dynamic-tool-output-compression.md)
- [Context Window Enforcement](context-window-enforcement.md)
