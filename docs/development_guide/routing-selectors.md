# Technical Reference: Routing Selectors

This document provides detailed technical specifications for the proxy's routing selector syntax.

## Selector Formats

### Basic Selectors

- `backend:model` - Selects an explicit backend family (e.g., `openai:gpt-4o`)
- `backend-instance:model` - Targets a concrete backend instance (e.g., `openai.1:gpt-4o`)
- `model` - Model-only selector (uses default backend)
- `vendor/model` - Vendor-prefixed model selector
- `vendor/model:variant` - Model variant selector (remains model-only)

### URI-style Parameters

Selectors can include URI-style parameters that are parsed and propagated through routing metadata:

```
model?temperature=0.5&max_tokens=1000
openai:gpt-4o?temperature=0.7
```

### Composite Selectors

#### Failover Routing (Ordered)

Uses `|` to specify fallback backends when pre-output failures occur:

```
selectorA|selectorB|selectorC
```

Examples:
- `openai:gpt-4o|anthropic:claude-3-5-sonnet|openrouter:openai/gpt-4o`
- `gemini:gemini-1.5-pro|openai:gpt-4o`

The proxy advances left-to-right through the chain when failures occur, sharing one bounded attempt budget with existing retry/failover safety controls.

#### Weighted Routing

Uses `^` with optional `[weight=N]` and `[max_context=N]` prefixes for weighted distribution:

```
[weight=3]openai:gpt-4^[weight=1]anthropic:claude-3-5-sonnet
```

This distributes traffic 75% to OpenAI and 25% to Anthropic.

`[max_context=N]` excludes a branch when the current request context size exceeds `N` tokens.
Token counting uses `tiktoken` with model-family-aware encoding heuristics.

For request paths that already know the exact prompt size, callers can pass
`request_context_tokens` in the request `extra_body` to override heuristic token
estimation for that request. This override is evaluated per request and applies
to single-leaf, failover, and weighted selectors.

Examples:
- `[weight=3,max_context=128000]openai:gpt-4o^[weight=1]anthropic:claude-3-5-sonnet`
- `[first,max_context=164000,weight=4]opencode-go:glm-5.1^[weight=1]openai:gpt-4o`

Request override example:

```json
{
  "model": "[max_context=8192]openai:gpt-4o|anthropic:claude-3-5-sonnet",
  "messages": [{"role": "user", "content": "Hello"}],
  "extra_body": {
    "request_context_tokens": 9000
  }
}
```

In this example, the OpenAI branch is skipped because the override exceeds its
`max_context` limit, so routing proceeds to the next eligible branch.

#### First-Request Override in Weighted Routing

Add a `[first]` annotation to one branch to force that backend/model for the very first request of a session. Subsequent requests use normal weighted routing based on weights.

```
openai-codex:gpt-5.3-codex?reasoning_effort=low^[first]openai-codex:gpt-5.4?reasoning_effort=xhigh
```

On the first request of a session, the `[first]`-tagged branch is selected regardless of weight. From the second request onward, weighted routing applies normally (equal 50/50 split in this example since no `[weight=N]` annotations are present).

Accepted annotation forms: `[first]`, `[first=1]`, `[first=yes]`, `[first=true]`. Forms like `[first=false]`, `[first=0]`, `[first=no]` are rejected.

Rules:
- **Exactly one** branch may be tagged `[first]` per weighted selector. Multiple `[first]` tags cause a validation error.
- The `[first]` tag only affects the first request of a session. A session-level flag (`weighted_first_request_consumed`) is set after the first request is routed, ensuring subsequent requests use weighted selection even if routing fails and retries.
- Retry paths (failover bridge) ignore the `[first]` tag and always use weighted selection among remaining candidates.
- The weight on the `[first]`-tagged branch does not influence the first request; it only applies from the second request onward.
- The `[first]` annotation is only valid within weighted (`^`) selectors. Using it in failover (`|`) selectors is a validation error.

Combining both annotations on the same branch:

```
[first][weight=3]openai:gpt-4^[weight=1]anthropic:claude-3-5-sonnet
```

This uses gpt-4 for the first session request, then routes 75% / 25% weighted distribution from the second request onward.

`[max_context=N]` can be combined with `[first]` and `[weight=N]` in a single block or across consecutive blocks. These forms are equivalent:

```
[first,max_context=164000,weight=4]openai:gpt-4
[weight=4][first][max_context=164000]openai:gpt-4
```

#### Interleaved Thinker Routing

Add a `[thinker]` annotation to one weighted branch to mark the stronger model as a thinker turn:

```
[weight=1,thinker]openai:gpt-4^[weight=10]openrouter:deepseek/deepseek-v4-flash
```

Accepted forms are `[thinker]`, `[thinker=1]`, `[thinker=yes]`, and `[thinker=true]`.
Only one branch in a weighted selector may be tagged as thinker. When the thinker
branch is selected, the proxy injects the configured
`backends.interleaved_thinking_instructions_file` content into that backend request,
stores the thinker output in session state, and injects the latest memo into later
non-thinker main requests. By default this uses the shipped prompt at
`config/prompts/interleaved_thinking/thinker_prompt.md`.
The proxy does not strip, suppress, or rewrite the request's tool definitions for
thinker turns; if the selected model emits tool calls, they are passed through using
the normal backend/client protocol.

#### Parallel Routing

Uses `!` to fork one streaming A-leg into multiple backend/model B-legs and bridge
the first leg that emits meaningful output:

```
[handicap=10,ttft_timeout=10]nvidia:moonshotai/kimi-k2.6![handicap=5,ttft_timeout=5]nvidia:minimaxai/minimax-m3![handicap=2]nvidia:nvidia/nemotron-3-ultra-550b-a55b!nvidia:stepfun-ai/step-3.7-flash
```

Parallel routing is streaming-only. Non-streaming requests with `!` are rejected
because the winner is defined by first emitted meaningful output. Meaningful output
includes non-whitespace chat content, reasoning content, or tool-call deltas;
SSE keep-alives, whitespace-only chunks, and terminal error chunks do not win.

While no winner exists, the proxy keeps the client-side A-leg open with standard
SSE comment keep-alives (`: keep-alive\n\n`). Once a winner is found, the proxy
bridges that B-leg to the A-leg and cancels all losing B-legs through their
protocol-specific cancellation callback before local task cleanup. If the client
disconnects or submits an explicit cancellation request, all active and scheduled
B-legs are stopped, including the winning leg if one has already been selected.

Accepted parallel-only annotations:

- `[handicap=N]` - Non-negative seconds. The highest handicap starts immediately;
  each other leg starts after `max_handicap - handicap` seconds. If a started
  non-zero-handicap leg definitively fails before any winner exists, pending legs
  are started immediately instead of waiting out the remaining handicap schedule.
- `[ttft_timeout=N]` - Non-negative seconds. When greater than zero, the leg is
  cancelled if it does not emit meaningful output within that many seconds after
  it starts.

Rules:

- `!` cannot be mixed with `|` or `^` in the same selector.
- `handicap` and `ttft_timeout` are valid only on parallel (`!`) selectors.
- URL-encode literal `!` characters in query values as `%21`.

### Selector Rules

1. **No mixing operators** - Composite selectors must not mix `|` and `^` in the same selector string. These are rejected during validation.

2. **Quoting and escaping** - When providing selectors via CLI or environment variables, quote/escape the full selector string:
   - Windows: `|` is a PowerShell pipeline operator, `^` is a cmd.exe escape character
   - Bash: Use quotes to prevent shell interpretation

3. **Strict format for explicit routing** - `--static-route`, replacement targets, and explicit routing require strict `backend:model` format.

## Examples

### CLI Usage

```bash
# Basic backend selection
python -m src.core.cli --default-backend openai:gpt-4o

# With parameters
python -m src.core.cli --default-backend "openai:gpt-4o?temperature=0.5"

# Failover chain
python -m src.core.cli --default-backend "openai:gpt-4o|anthropic:claude-3-5-sonnet"

# Weighted routing
python -m src.core.cli --default-backend "[weight=3]openai:gpt-4^[weight=1]anthropic:claude-3-5-sonnet"

# Parallel routing for streaming requests
python -m src.core.cli --default-backend "[handicap=5,ttft_timeout=8]openai:gpt-4o!anthropic:claude-3-5-sonnet"

# Weighted with first-request override
python -m src.core.cli --default-backend "[weight=3]openai:gpt-4^[first][weight=1]anthropic:claude-3-5-sonnet"
```

### Environment Variables

```bash
# Default backend with failover
export LLM_BACKEND="openai:gpt-4o|anthropic:claude-3-5-sonnet"

# Static route with parameters
export STATIC_ROUTE="openai:gpt-4o?temperature=0.1"
```

### Configuration File

```yaml
backends:
  default_backend: "openai:gpt-4o"
  
# Failover route for specific model
failover_routes:
  "gpt-4o":
    policy: "round-robin"
    elements: ["openai:gpt-4o", "anthropic:claude-3-5-sonnet"]
```

## Legacy Compatibility

Random model replacement has been deprecated and now routes through a compatibility bridge:
- Emits deprecation metadata
- Removal timeline: N+1 (removed in release after deprecation)
- Rejects unsafe mappings with explicit migration errors

Migrate to composite selectors for similar functionality.

## See Also

- [Backends Overview](../user_guide/backends/overview.md) - Provider setup and configuration
- [Routing Configuration](../user_guide/configuration.md) - Full configuration reference
- [CLI Parameters](../user_guide/cli-parameters.md) - Command-line options
