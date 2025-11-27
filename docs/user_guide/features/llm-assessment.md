# LLM Assessment System

The proxy includes an intelligent conversation assessment system that monitors conversation quality and detects unproductive patterns, inspired by Google's gemini-cli project.

## Overview

The LLM Assessment System uses a smaller, faster LLM to periodically analyze conversation history and provide steering when the main conversation becomes stuck. This feature operates transparently in the background, only intervening when it detects genuine unproductive patterns with high confidence.

## Key Features

- **Automatic Pattern Detection**: Identifies repetitive tool calls, cognitive loops, and lack of progress
- **Event-Driven Assessment**: Triggers after configurable turn thresholds (default: 30 turns)
- **Confidence-Based Intervention**: Only intervenes when confidence is high (default: 0.9 threshold)
- **Dynamic Frequency Adjustment**: Adjusts assessment frequency based on confidence levels
- **Multi-Backend Support**: Works with any configured backend (OpenAI, Anthropic, Gemini, etc.)

## Configuration

### CLI Arguments

```bash
--enable-llm-assessment                    # Enable the assessment system
--llm-assessment-backend openai            # Backend to use for assessment
--llm-assessment-model gpt-4o-mini         # Model for assessment (recommend fast, cheap models)
--llm-assessment-turn-threshold 30         # Turns before first assessment (default: 30)
--llm-assessment-confidence-threshold 0.9  # Confidence threshold for intervention
--llm-assessment-history-window 20         # Recent turns to analyze (default: 20)
```

### Environment Variables

```bash
export LLM_ASSESSMENT_ENABLED=true
export LLM_ASSESSMENT_BACKEND=openai
export LLM_ASSESSMENT_MODEL=gpt-4o-mini
export LLM_ASSESSMENT_TURN_THRESHOLD=30
export LLM_ASSESSMENT_CONFIDENCE_THRESHOLD=0.9
export LLM_ASSESSMENT_HISTORY_WINDOW=20
```

### YAML Configuration

```yaml
llm_assessment:
  enabled: true
  backend: openai
  model: gpt-4o-mini
  turn_threshold: 30
  confidence_threshold: 0.9
  history_window: 20
  intervals:
    min: 5      # Minimum turns between assessments
    max: 15     # Maximum turns between assessments
    default: 3  # Default interval adjustment
```

## Usage Examples

### Basic Setup with OpenAI

```bash
python -m src.core.cli \
  --enable-llm-assessment \
  --llm-assessment-backend openai \
  --llm-assessment-model gpt-4o-mini
```

### Custom Thresholds for Sensitive Detection

```bash
python -m src.core.cli \
  --enable-llm-assessment \
  --llm-assessment-backend anthropic \
  --llm-assessment-model claude-3-haiku-20240307 \
  --llm-assessment-turn-threshold 20 \
  --llm-assessment-confidence-threshold 0.8
```

## Use Cases

- **Long Coding Sessions**: Detect when an AI assistant gets stuck repeatedly calling the same tools
- **Complex Problem Solving**: Identify cognitive loops where the assistant expresses confusion or asks the same questions
- **Resource Conservation**: Automatically intervene in unproductive conversations to save API costs
- **Quality Assurance**: Ensure conversations maintain forward progress toward task completion

## How It Works

The assessment system operates in the background:

1. Monitors conversation turn count
2. When threshold is reached, analyzes recent conversation history
3. Evaluates patterns for signs of being stuck or unproductive
4. If confidence is high enough, injects a steering message
5. Adjusts assessment frequency based on confidence levels
6. Assessment failures never break the main conversation flow

## Related Features

- [Angel Verification System](angel-verification.md) - Real-time response verification
- [Session Management](session-management.md) - Intelligent session handling
