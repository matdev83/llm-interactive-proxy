# Quality Verifier System

The Quality Verifier is a proxy-level helper that uses a **secondary LLM** on a schedule (every N eligible turns) to audit the **current** main-model completion. On those turns it **holds** the client response until verification finishes, then either returns the original output, runs an **inline** main-model recall with steering, or fails open to the original output if anything goes wrong.

## Overview

Verification shares one code path for **streaming and non-streaming**: buffer (or use) the main completion, call the verifier (plus at most one XML format-retry), reset the eligible-turn counter, then apply pass vs steer vs fail-open rules.

## Key Features

- **Scheduled, blocking verification**: On eligible turns the user-visible response waits until the verifier finishes (streaming buffers chunks up to a 1MB cap; overflow fail-opens to live passthrough without resetting the turn counter).
- **Progress & direction steering**: Detects stagnation, wrong approaches, or missing next steps and can steer the main model.
- **Inline steering recall**: When the verifier returns `<steering>...</steering>`, the proxy issues a **same-request** main-model call with a private steering system message; the client sees the recalled completion, not a deferred patch on a later turn.
- **Legacy deferred store** (optional): `quality_verifier_steering_store` + `request_transform_pipeline` can still apply steering on a **subsequent** request for auxiliary flows; primary production behavior is inline recall.
- **Configurable frequency**: Every N eligible turns (with scaled counters in session + LRU).
- **Context window protection**: Truncate history sent to the verifier (opt-in).
- **Model flexibility**: Any supported backend/model for the verifier role.
- **User-configurable prompts**: Markdown prompts under `config/prompts/quality_verifier_prompts/`.
- **Fail-open design**: Verifier errors, timeouts, recall failures, or parse issues leave the user with the **original** main output.

## How It Works

1. The main model runs as usual. If this turn is **not** a scheduled verifier turn, the client sees the stream or non-stream response immediately.
2. On a scheduled turn, the proxy **buffers** the main output (streaming) or uses the completed body (non-streaming), then calls the verifier model once (with optional XML correction retry). If the stream yields chunks but **no extractable text** is captured, the verifier is skipped and the ledger is **not** reset for that turn.
3. The eligible-turn counter is **reset** after that verification episode completes (not after buffer-overflow fail-open, and not when streaming verification was skipped due to empty text).
4. If the verdict is **pass** or unparseable, the proxy replays or returns the **original** buffered completion.
5. If the verdict is **steer**, the proxy runs an **inline** main-model request that includes the steering note; if that recall fails, the client still gets the **original** completion.

The verifier therefore **can** delay the response on scheduled turns; it does not run in the background after the client has already received the answer for that turn.

**Streaming edge case:** If the verifier returns **steer** but **no** `RequestContext` is available to build the recall call, the proxy replays the original buffered stream; the eligible-turn counter has already been reset for that verification run (the verifier model was still invoked).

## Configuration

### CLI Arguments

```bash
--quality-verifier-model "backend:model"  # Enable Quality Verifier with specified model
--quality-verifier-frequency 10               # Verify every N eligible turns (default: 10)
--quality-verifier-max-history 10             # Truncate history to last N messages (optional)
--quality-verifier-max-consecutive-failures 5 # Circuit-breaker threshold (default: 5)
--quality-verifier-cooldown-seconds 300       # Circuit-breaker cooldown (default: 300)
```

### Environment Variables

```bash
export QUALITY_VERIFIER_MODEL="openai:gpt-4o-mini"
export QUALITY_VERIFIER_FREQUENCY=10
export QUALITY_VERIFIER_MAX_HISTORY=10
```

### YAML Configuration

```yaml
session:
  quality_verifier_model: "anthropic:claude-3-5-haiku-20241022"
  quality_verifier_frequency: 10   # Verify every 10 eligible turns (default)
  quality_verifier_max_history: 10 # Optional truncation
```

## Usage Examples

### Basic Setup with OpenAI

```bash
python -m src.core.cli \
  --quality-verifier-model "openai:gpt-4o-mini" \
  --quality-verifier-frequency 1
```

### Sophisticated Verification with Claude

```bash
# Use Claude for more sophisticated verification, check every 2 turns
python -m src.core.cli \
  --quality-verifier-model "anthropic:claude-3-5-haiku-20241022" \
  --quality-verifier-frequency 2
```

### With Model Parameters

```bash
python -m src.core.cli \
  --quality-verifier-model "openai:gpt-4o-mini?temperature=0.3"
```

## Customizing Quality Verifier Prompts

Quality Verifier prompts are stored as markdown files in `config/prompts/quality_verifier_prompts/` and can be customized to change verification behavior:

- **`quality_verifier_prompt.md`**: The main instruction prompt that defines the verifier role, output format, and what problems to look for
- **`steering_template.md`**: Template used when building the private steering system message for **inline** recall (and related paths)

### Example Customization

To add a new problem pattern to detect, edit `config/prompts/quality_verifier_prompts/quality_verifier_prompt.md` and add under "Problems you should look for:":

```markdown
- assistant is making promises about future work instead of implementing now
```

After editing the prompts, restart the proxy to load the updated configuration.

## Use Cases

- **Maintain Focus**: Detect when the assistant loses track of the main goal
- **Improve Progress**: Suggest next actions when the assistant is stuck
- **Detect Logic Errors**: Identify flawed reasoning or incorrect conclusions and suggest course corrections

## Robustness & Security

The Quality Verifier system is designed for high reliability and safety:

- **Fail-Open**: If the Quality Verifier model errors, times out, the proxy hits the 1MB streaming capture limit, or inline recall fails, the client receives the **original** main-model completion for that turn.
- **Atomic Loading**: Prompts are loaded once at startup with thread-safe mechanisms to prevent race conditions.
- **Private injection**: Steering is carried as proxy-generated system content on the **recall** request; the end user still only sees model output, not the raw steering XML from the verifier.

## When to Use Quality Verifier

- Use Quality Verifier when you want periodic, lightweight guidance to keep long sessions on track.
- It is best for complex workflows where occasional course corrections are valuable.

## Related Features

- [Tool Access Control](tool-access-control.md) - Control which tools can be executed
- [Dangerous Command Protection](dangerous-command-protection.md) - Block destructive operations
