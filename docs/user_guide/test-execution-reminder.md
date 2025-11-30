# Test Execution Reminder

## Overview

The Test Execution Reminder system automatically detects when coding agents have modified files but haven't run tests before attempting to complete a task. When this happens, the proxy injects a steering message reminding the agent to run tests first, ensuring code quality practices are followed.

## How It Works

1. **File Modification Tracking**: The system monitors all file-modifying tool calls (write_file, str_replace, apply_diff, etc.)
2. **Test Execution Detection**: Recognizes test commands across 14+ programming languages
3. **Completion Signal Detection**: Identifies when agents attempt to signal task completion using two reliable methods:
   - **Primary**: Actual completion tool names from popular agents (e.g., `attempt_completion` from Cline/Roo-Code, `finish` from OpenHands)
   - **Secondary**: Streaming `finish_reason` markers from LLM APIs (e.g., "stop", "tool_calls", "length", "end_turn")
4. **Steering Intervention**: If files were modified but tests weren't run, the system:
   - Swallows the completion tool call
   - Injects a steering message reminding the agent to run tests
   - Sends a new request to the backend LLM with full conversation history
   - Forwards the LLM's response back to the client

## Supported Languages

The system recognizes test execution commands for:

- **Python**: `pytest`, `python -m pytest`, `py.test`, `python -m unittest`
- **JavaScript/TypeScript**: `jest`, `npm test`, `yarn test`, `vitest`, `mocha`, `ava`
- **Rust**: `cargo test`
- **Go**: `go test`
- **Java**: `mvn test`, `gradle test`, `./gradlew test`
- **C#**: `dotnet test`
- **Ruby**: `rspec`, `rake test`, `bundle exec rspec`
- **PHP**: `phpunit`, `composer test`
- **C/C++**: `ctest`, `make test`, `cmake --build . --target test`
- **Swift**: `swift test`
- **Kotlin**: `gradle test` (Kotlin projects)
- **Scala**: `sbt test`
- **Elixir**: `mix test`
- **Dart/Flutter**: `flutter test`, `dart test`

## Configuration

### Enable/Disable the Feature

**CLI Flags** (highest priority):
```bash
# Enable
python -m src.core.cli --test-execution-reminder-enabled

# Disable
python -m src.core.cli --no-test-execution-reminder-enabled
```

**Environment Variables**:
```bash
export TEST_EXECUTION_REMINDER_ENABLED=true
export TEST_EXECUTION_REMINDER_MESSAGE="Custom reminder message..."
```

**Config File** (`config/config.yaml`):
```yaml
test_execution_reminder_enabled: true
test_execution_reminder_message: "Custom reminder message..."
```

### Configuration Precedence

Configuration sources are applied in this order (highest to lowest):
1. CLI flags
2. Environment variables
3. Config file

### Custom Steering Message

You can customize the message that agents receive:

**Default Message**:
```
You have made code changes but haven't run tests yet. Please run the test suite to verify your changes before completing this task. Once tests pass, you can proceed with task completion.
```

**Custom Message via Environment Variable**:
```bash
export TEST_EXECUTION_REMINDER_MESSAGE="Run tests before marking this task complete!"
```

**Custom Message via Config File**:
```yaml
test_execution_reminder_message: |
  Please execute the test suite to verify your changes.
  All tests must pass before task completion.
```

## Usage Examples

### Example 1: Basic Flow

```
Agent: [Modifies file with write_file tool]
System: [Marks session as "dirty"]

Agent: [Attempts to complete task]
System: [Detects dirty state + completion signal]
System: [Injects steering message]

Agent: [Receives reminder to run tests]
Agent: [Runs pytest]
System: [Marks session as "clean"]

Agent: [Attempts to complete task again]
System: [Allows completion - state is clean]
```

### Example 2: Multi-Language Project

```
Agent: [Modifies Python file]
System: [Session marked dirty]

Agent: [Runs pytest tests/unit/]
System: [Session marked clean]

Agent: [Modifies TypeScript file]
System: [Session marked dirty again]

Agent: [Runs npm test]
System: [Session marked clean]

Agent: [Completes task]
System: [Allows completion]
```

### Example 3: Disabled Feature

```bash
# Start proxy with feature disabled
python -m src.core.cli --no-test-execution-reminder-enabled

# Agent can complete tasks without running tests
# No state tracking occurs
# No steering messages are injected
```

## Session Isolation

Each agent session maintains independent state:

- Session A modifies files → Session A is dirty
- Session B is unaffected → Session B remains clean
- Sessions are isolated and don't interfere with each other

## Memory Management

The system includes automatic cleanup:

- **TTL-based cleanup**: Sessions inactive for 30 minutes are removed
- **Max sessions limit**: Maximum 1024 sessions tracked simultaneously
- **Oldest-first eviction**: When limit is reached, oldest sessions are removed

## Error Handling

The system is designed to fail open:

- **Pattern matching errors**: Logged as warnings, request proceeds
- **State corruption**: Session reset to clean state, request proceeds
- **Unknown tool calls**: Ignored, request proceeds
- **Configuration errors**: Default values used, feature remains functional

The feature will never crash the proxy pipeline or block legitimate requests.

## Integration with Other Features

The Test Execution Reminder works alongside other proxy features:

- **Priority**: 90 (below pytest full-suite handler at 95)
- **Tool Call Reactor**: Uses the same event-driven architecture
- **Session Management**: Integrates with existing session infrastructure
- **Logging**: Comprehensive logging at appropriate levels

## Troubleshooting

### Feature Not Working

1. Check if feature is enabled:
   ```bash
   # Look for initialization log message
   grep "Test Execution Reminder" logs/proxy.log
   ```

2. Verify configuration precedence:
   - CLI flags override environment variables
   - Environment variables override config file

3. Check session state:
   - Look for "Marking session dirty" log messages
   - Look for "Marking session clean" log messages

### Tests Not Detected

1. Verify test command matches supported patterns
2. Check logs for pattern matching attempts
3. Consider adding custom pattern to registry (see extensibility)

### Steering Message Not Appearing

1. Verify session is in dirty state
2. Confirm completion signal is detected
3. Check handler priority (should be 90)
4. Review logs for steering injection messages

## Extensibility

The system is designed to be extensible. New test runners can be added by:

1. Creating a new `TestRunnerPattern` with regex patterns
2. Registering the pattern with the `TestRunnerRegistry`
3. No changes to core logic required

Example:
```python
from src.services.test_execution_reminder.test_runner_registry import (
    TestRunnerRegistry,
    TestRunnerPattern
)
import re

# Add support for a new test framework
registry = TestRunnerRegistry()
registry.register_pattern(TestRunnerPattern(
    language="custom",
    framework="mytest",
    patterns=[re.compile(r"^mytest\b")],
    priority=10
))
```

## Best Practices

1. **Enable by default**: Helps enforce test-driven development
2. **Custom messages**: Tailor messages to your team's workflow
3. **Monitor logs**: Review steering interventions to understand agent behavior
4. **Session cleanup**: Default TTL (30 min) works for most use cases
5. **Multi-language projects**: System automatically handles all supported languages

## Performance Impact

The feature has minimal performance impact:

- **Pattern matching**: Uses compiled regex for efficiency
- **State storage**: O(1) session lookup with dict
- **Memory bounds**: Enforced max sessions and TTL cleanup
- **Early exit**: Disabled feature returns immediately

## Security Considerations

The feature is designed with security in mind:

- **No code execution**: Only pattern matching and state tracking
- **Session isolation**: Sessions cannot interfere with each other
- **Fail-open**: Errors never block legitimate requests
- **Logging**: All interventions are logged for audit

## Completion Detection Methods

The system uses two reliable methods to detect when agents signal task completion:

### Primary: Actual Completion Tool Names

Based on source code analysis of popular coding agents, the system recognizes these completion tools:

- **`attempt_completion`**: Used by Cline and Roo-Code (Kilo Code) - most common
- **`finish`**: Used by OpenHands (formerly OpenDevin)
- **`finish_task`**: Generic completion tool
- **`task_complete`**: Generic completion tool
- **`mark_complete`**: Generic completion tool
- **`complete`**: Generic completion tool
- **`done`**: Generic completion tool

This approach is based on actual agent source code rather than speculation, making it highly reliable.

### Secondary: Streaming finish_reason Markers

The system also recognizes standard `finish_reason` values from LLM APIs:

- **`stop`**: Normal completion (OpenAI, Anthropic)
- **`tool_calls`**: Completed with tool calls (OpenAI)
- **`length`**: Maximum token limit reached (OpenAI, Anthropic)
- **`end_turn`**: Anthropic's completion marker

These markers are extracted from streaming responses and metadata, providing a reliable secondary detection method.

### Why This Approach?

**Phase 2 Improvements** (December 2025): The initial implementation used pattern matching against model output text, which was unreliable and prone to false positives. The current implementation uses:

1. **Evidence-Based Detection**: Actual tool names from real agent source code
2. **API-Compliant Detection**: Standard finish_reason values from LLM specifications
3. **No False Positives**: Only triggers on explicit signals, not ambiguous text
4. **Streaming Support**: Works with streaming responses via finish_reason
5. **Maintainable**: Easy to add new agent tool names as discovered

## Agent Compatibility

The system is compatible with popular coding agents:

| Agent | Completion Tool | Detection Method |
|-------|----------------|------------------|
| **Cline** | `attempt_completion` | Primary (tool name) |
| **Roo-Code (Kilo Code)** | `attempt_completion` | Primary (tool name) |
| **OpenHands** | `finish` | Primary (tool name) |
| **Generic Agents** | Various | Secondary (finish_reason) |
| **Custom Agents** | Extensible | Both methods |

The system automatically detects completion signals from these agents without requiring any agent-specific configuration.

## Related Features

- [Pytest Full-Suite Steering](features/pytest-full-suite-steering.md) - Prevents agents from running entire test suites inadvertently
- [Dangerous Command Protection](features/dangerous-command-protection.md) - Blocks destructive operations
- [Tool Access Control](features/tool-access-control.md) - Fine-grained control over tool usage
- [LLM Assessment](features/llm-assessment.md) - Detects conversation loops and stuck patterns
