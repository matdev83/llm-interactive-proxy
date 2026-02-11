# Quality Verifier System

The Quality Verifier system is a proxy-level quality control feature that uses a secondary LLM to review and verify assistant responses before they reach the user.

## Overview


## Key Features

- **Real-Time Response Verification**: Reviews each assistant response before forwarding it to the user
- **Error Detection**: Identifies logical errors, wrong tool calls, and misbehaviors
- **Automatic Correction**: Prompts the main model to fix detected issues transparently
- **Configurable Frequency**: Control how often verification runs (every N user turns)
- **Context Window Protection**: Truncate conversation history sent to the verifier (opt-in)
- **Memory Safety**: 1MB buffer limit for streaming verification to prevent OOM
- **Model Flexibility**: Use any supported backend/model for verification
- **User-Configurable Prompts**: Customize verification behavior by editing markdown files
- **Fail-Open Design**: Automatically falls back to original response if the verifier backend fails

## How It Works

```mermaid
sequenceDiagram
    participant User
    participant Proxy
    participant Main as Main Model
    participant Verifier as Quality Verifier Model

    User->>Proxy: Request
    Proxy->>Main: Forward Request
    Main-->>Proxy: Response 1
    
    Note over Proxy: Buffer Response 1
    
    Proxy->>Verifier: Verify Response 1
    Verifier-->>Proxy: Decision
    
    alt Decision = Pass
        Proxy-->>User: Response 1
    else Decision = Fail (Steer)
        Note over Proxy: Construct Correction Request
        Proxy->>Main: Correction Request + Steering
        Main-->>Proxy: Response 2 (Corrected)
        Proxy-->>User: Response 2
    end
```

1. Main model generates a response
2. Quality Verifier (secondary LLM) reviews the response for issues
3. If issues are found, Quality Verifier provides steering feedback to the main model
4. Main model regenerates a corrected response
5. Corrected response is sent to the user (original error never seen)

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
- **`steering_template.md`**: The template used when Quality Verifier detects an issue and needs to guide the main model to correct it

### Example Customization

To add a new problem pattern to detect, edit `config/prompts/quality_verifier_prompts/quality_verifier_prompt.md` and add under "Problems you should look for:":

```markdown
- assistant is making promises about future work instead of implementing now
```

After editing the prompts, restart the proxy to load the updated configuration.

## Use Cases

- **Prevent Tool Call Errors**: Catch incorrect tool usage before it causes issues
- **Detect Logic Errors**: Identify flawed reasoning or incorrect conclusions
- **Stop Dangerous Commands**: Block potentially destructive operations
- **Maintain Focus**: Detect when the assistant loses track of the main goal
- **Quality Control**: Ensure outputs meet quality standards before reaching users

## Robustness & Security

The Quality Verifier system is designed for high reliability and safety:

- **Fail-Open**: If the Quality Verifier model errors, times out, or the proxy hits a 1MB buffer limit, the original assistant response is released immediately. Verification never breaks the user session.
- **Atomic Loading**: Prompts are loaded once at startup with thread-safe mechanisms to prevent race conditions.
- **Secure Steering**: Steering instructions are injected as `user` role messages with distinct markers, ensuring compatibility with all backends (like Claude/Gemini) and preventing internal prompt leakage.
- **No Bypass**: The previous "Override" mechanism has been removed to prevent malfunctioning models from vetoing safety checks.

## When to Use Quality Verifier

- Use Quality Verifier for immediate, per-response quality control and error prevention.
- It is best for critical workflows where each response should be checked before delivery.

## Related Features

- [Tool Access Control](tool-access-control.md) - Control which tools can be executed
- [Dangerous Command Protection](dangerous-command-protection.md) - Block destructive operations
