# Quality Verifier System

The Quality Verifier system is a proxy-level quality helper that uses a secondary LLM to periodically assess a session and optionally provide private steering guidance to the main model.

## Overview


## Key Features

- **Periodic Assessment (Asynchronous)**: Runs every N eligible turns without delaying the user-visible response
- **Progress & Direction Steering**: Detects stagnation, wrong approaches, or missing next steps and suggests better course corrections
- **Private Guidance**: Steering notes are injected into future main-model requests; they are not shown to the user
- **Configurable Frequency**: Control how often assessment runs (every N eligible turns)
- **Context Window Protection**: Truncate conversation history sent to the verifier (opt-in)
- **Memory Safety**: 1MB capture limit for streaming assessment to prevent OOM
- **Model Flexibility**: Use any supported backend/model for assessment
- **User-Configurable Prompts**: Customize verifier behavior by editing markdown files
- **Fail-Open Design**: Verifier failures never break the user session

## How It Works

1. Main model generates a response and it is streamed/returned to the user normally.
2. Periodically (every N eligible turns), the proxy calls the Quality Verifier model *asynchronously*.
3. If the verifier decides guidance is useful, it emits a short steering note.
4. The proxy stores that note and injects it as a private system message into a *future* main-model request.

The verifier does not block or rewrite the current response.

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
- **`steering_template.md`**: The template used to wrap the private steering note that is injected into future main-model requests

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

- **Fail-Open**: If the Quality Verifier model errors, times out, or the proxy hits the 1MB capture limit, the main response is unaffected.
- **Atomic Loading**: Prompts are loaded once at startup with thread-safe mechanisms to prevent race conditions.
- **Private Injection**: Steering notes are injected as proxy-generated messages and not shown to the user.

## When to Use Quality Verifier

- Use Quality Verifier when you want periodic, lightweight guidance to keep long sessions on track.
- It is best for complex workflows where occasional course corrections are valuable.

## Related Features

- [Tool Access Control](tool-access-control.md) - Control which tools can be executed
- [Dangerous Command Protection](dangerous-command-protection.md) - Block destructive operations
