# Design Document: Test Execution Reminder System

## Overview

The Test Execution Reminder System is a middleware component that tracks file modifications and test executions within agent sessions, automatically injecting steering messages when agents attempt to complete tasks without running tests after making code changes. The system maintains a "dirty state" indicator per session and intervenes at task completion boundaries to ensure code quality practices are followed.

**Core Mechanism**: When a completion signal is detected in dirty state, the handler swallows the tool call and returns a steering message. The proxy's existing infrastructure then sends a new request to the backend LLM with all conversation history plus the steering message, and forwards the LLM's response to the client. This ensures agents are reminded to run tests before finalizing their work.

The design follows the existing tool call reactor pattern used by the pytest full-suite steering handler, integrating seamlessly with the proxy's middleware pipeline while maintaining session isolation and minimal performance overhead.

**Quality Standards**: This implementation adheres to industry best practices for agentic coding workflows by:
1. Preventing incomplete work from being marked as done
2. Enforcing test-driven development practices
3. Maintaining conversation context during steering interventions
4. Providing clear, actionable feedback to agents
5. Supporting multi-language development environments

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     LLM Proxy Pipeline                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │         Tool Call Reactor Service                   │    │
│  │  (Priority-based handler orchestration)             │    │
│  └────────────────────────────────────────────────────┘    │
│                          │                                   │
│                          ▼                                   │
│  ┌────────────────────────────────────────────────────┐    │
│  │   Test Execution Reminder Handler (Priority: 90)   │    │
│  │                                                      │    │
│  │  ┌──────────────────────────────────────────────┐  │    │
│  │  │  File Modification Tracker                   │  │    │
│  │  │  - Detects write/edit tool calls             │  │    │
│  │  │  - Marks session as dirty                    │  │    │
│  │  └──────────────────────────────────────────────┘  │    │
│  │                                                      │    │
│  │  ┌──────────────────────────────────────────────┐  │    │
│  │  │  Test Execution Detector                     │  │    │
│  │  │  - Pattern registry for test runners         │  │    │
│  │  │  - Multi-language support                    │  │    │
│  │  │  - Clears dirty state                        │  │    │
│  │  └──────────────────────────────────────────────┘  │    │
│  │                                                      │    │
│  │  ┌──────────────────────────────────────────────┐  │    │
│  │  │  Completion Signal Detector                  │  │    │
│  │  │  - Pattern matching for completion messages  │  │    │
│  │  │  - Tool call analysis                        │  │    │
│  │  └──────────────────────────────────────────────┘  │    │
│  │                                                      │    │
│  │  ┌──────────────────────────────────────────────┐  │    │
│  │  │  Session State Manager                       │  │    │
│  │  │  - Per-session dirty/clean tracking          │  │    │
│  │  │  - TTL-based cleanup                         │  │    │
│  │  │  - Memory guardrails                         │  │    │
│  │  └──────────────────────────────────────────────┘  │    │
│  └────────────────────────────────────────────────────┘    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Component Interaction Flow

```
Agent Tool Call
      │
      ▼
┌─────────────────────┐
│ Tool Call Reactor   │
│ Service             │
└─────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────┐
│ Test Execution Reminder Handler                     │
│                                                      │
│  1. Extract command/tool name                       │
│  2. Check if file modification tool                 │
│     ├─ Yes → Mark session dirty, allow through      │
│     └─ No → Continue                                │
│                                                      │
│  3. Check if test execution command                 │
│     ├─ Yes → Mark session clean, allow through      │
│     └─ No → Continue                                │
│                                                      │
│  4. Check if completion signal                      │
│     ├─ No → Allow through                           │
│     └─ Yes → Check session state                    │
│         ├─ Clean → Allow through                    │
│         └─ Dirty → Swallow & inject steering        │
└─────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────┐
│ Steering Response   │
│ (if dirty state)    │
└─────────────────────┘
```

## Components and Interfaces

### 1. TestExecutionReminderHandler

Main handler class implementing `IToolCallHandler` interface.

```python
class TestExecutionReminderHandler(IToolCallHandler):
    """Handler that tracks file modifications and test executions."""
    
    def __init__(
        self,
        message: str | None = None,
        enabled: bool = True,
        *,
        state_ttl_seconds: int = 1800,
        max_sessions: int = 1024,
        test_runner_registry: TestRunnerRegistry | None = None,
    ) -> None:
        """Initialize the handler.
        
        Args:
            message: Custom steering message (uses default if None)
            enabled: Whether the feature is enabled
            state_ttl_seconds: TTL for session state (default: 30 minutes)
            max_sessions: Maximum number of sessions to track
            test_runner_registry: Registry of test runner patterns
        """
    
    @property
    def name(self) -> str:
        return "test_execution_reminder_handler"
    
    @property
    def priority(self) -> int:
        return 90  # Below pytest full-suite (95), above generic steering
    
    async def can_handle(self, context: ToolCallContext) -> bool:
        """Check if this tool call should be processed."""
    
    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        """Process the tool call and potentially inject steering."""
```

### 2. SessionState

Tracks the dirty/clean state for a single session.

```python
@dataclass
class SessionState:
    """State tracking for a single session."""
    
    is_dirty: bool = False
    """Whether files have been modified since last test run."""
    
    last_modification_time: float = 0.0
    """Timestamp of last file modification."""
    
    last_test_time: float = 0.0
    """Timestamp of last test execution."""
    
    last_seen: float = 0.0
    """Timestamp of last activity (for TTL cleanup)."""
    
    modification_count: int = 0
    """Number of modifications since last test run."""
```

### 3. TestRunnerRegistry

Registry of test runner patterns organized by language/framework.

```python
@dataclass
class TestRunnerPattern:
    """Pattern for detecting test execution commands."""
    
    language: str
    """Programming language (e.g., 'python', 'javascript')."""
    
    framework: str | None
    """Test framework name (e.g., 'pytest', 'jest')."""
    
    patterns: list[re.Pattern]
    """Compiled regex patterns for matching commands."""
    
    priority: int = 0
    """Priority for pattern matching (higher = more specific)."""


class TestRunnerRegistry:
    """Registry of test runner patterns for multiple languages."""
    
    def __init__(self) -> None:
        """Initialize with default patterns for popular languages."""
        self._patterns: list[TestRunnerPattern] = []
        self._load_default_patterns()
    
    def match_command(self, command: str) -> tuple[bool, str | None, str | None]:
        """Match command against registered patterns.
        
        Returns:
            Tuple of (is_match, language, framework)
        """
    
    def register_pattern(self, pattern: TestRunnerPattern) -> None:
        """Register a new test runner pattern."""
    
    def _load_default_patterns(self) -> None:
        """Load default patterns for popular languages."""
```

### 4. FileModificationDetector

Detects file modification tool calls.

```python
class FileModificationDetector:
    """Detects tool calls that modify files."""
    
    # Tool names that indicate file modifications
    FILE_MODIFICATION_TOOLS = {
        "write_file",
        "replace_lines",
        "replace_in_file",
        "write_to_file",
        "apply_diff",
        "apply_patch",
        "patch_file",
        "str_replace",
        "multiedit",
        "fs/write_text_file",
        "insert_content",
        "patch",
        "patchfile",
        "strreplace",
        "fswrite",
        "fs_write",
    }
    
    @classmethod
    def is_file_modification(cls, tool_name: str) -> bool:
        """Check if tool name indicates file modification."""
        normalized = tool_name.lower().replace("_", "").replace("/", "")
        return any(
            normalized == pattern.replace("_", "")
            for pattern in cls.FILE_MODIFICATION_TOOLS
        )
```

### 5. CompletionSignalDetector

Detects when agents signal task completion.

```python
from __future__ import annotations

from src.core.domain.chat import ToolCall

class CompletionSignalDetector:
    """Detects completion signals in tool calls and messages."""
    
    # Patterns that indicate task completion
    COMPLETION_PATTERNS = [
        re.compile(r"\b(task|implementation|feature|fix|change)s?\s+(is\s+)?(complete|done|finished|ready)\b", re.IGNORECASE),
        re.compile(r"\bcompleted?\s+(the\s+)?(task|implementation|feature|fix|work)\b", re.IGNORECASE),
        re.compile(r"\ball\s+(tests?|checks?)\s+pass(ing|ed)?\b", re.IGNORECASE),
        re.compile(r"\bready\s+(for|to)\s+(review|merge|deploy|commit)\b", re.IGNORECASE),
        re.compile(r"\bfinished\s+(implementing|coding|working\s+on)\b", re.IGNORECASE),
    ]
    
    # Tool names that signal completion
    COMPLETION_TOOLS = {
        "task_complete",
        "mark_complete",
        "finish_task",
        "complete",
        "done",
    }
    
    @classmethod
    def is_completion_signal(
        cls,
        tool_call: ToolCall,
        response_text: str | None = None,
    ) -> bool:
        """Check if this represents a completion signal."""
```

## Data Models

### Configuration Model

```python
@dataclass
class TestExecutionReminderConfig:
    """Configuration for test execution reminder feature."""
    
    enabled: bool = False
    """Whether the feature is enabled."""
    
    message: str | None = None
    """Custom steering message (None = use default)."""
    
    state_ttl_seconds: int = 1800
    """TTL for session state in seconds (default: 30 minutes)."""
    
    max_sessions: int = 1024
    """Maximum number of sessions to track."""
    
    @classmethod
    def from_app_config(cls, app_config: AppConfig) -> TestExecutionReminderConfig:
        """Create from application configuration."""
```

### AppConfig Extensions

Add to `src/core/config/app_config.py`:

```python
class AppConfig:
    # ... existing fields ...
    
    test_execution_reminder_enabled: bool = False
    """Whether test execution reminder steering is enabled."""
    
    test_execution_reminder_message: str | None = None
    """Optional custom steering message for test execution reminders."""
```

### Environment Variables

Add to configuration loading:

```
TEST_EXECUTION_REMINDER_ENABLED=true|false
TEST_EXECUTION_REMINDER_MESSAGE="Custom message..."
```

### CLI Arguments

Add to `src/core/cli.py`:

```python
# Test execution reminder
test_exec_reminder_group = parser.add_mutually_exclusive_group()
test_exec_reminder_group.add_argument(
    "--test-execution-reminder-enabled",
    action="store_const",
    const=True,
    dest="test_execution_reminder_enabled",
    default=None,
    help="Enable test execution reminder steering (overrides config)",
)
test_exec_reminder_group.add_argument(
    "--no-test-execution-reminder-enabled",
    action="store_const",
    const=False,
    dest="test_execution_reminder_enabled",
    help="Disable test execution reminder steering (overrides config)",
)
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property Reflection

After analyzing all acceptance criteria, I identified the following redundancies:
- Requirements 2.1-2.14 all test the same property (test execution clears dirty state) across different languages - combined into Property 2
- Requirement 2.17 is covered by Property 2 (any test execution clears state)
- Requirement 4.1 is the same as 3.4 (steering injection on dirty completion) - combined into Property 5
- Requirement 5.12 is covered by other properties testing enabled behavior
- Several logging requirements (1.3, 2.15, 7.1-7.6) are implementation details, not core correctness properties
- Requirements 4.2-4.4 are about backend communication flow, handled by the proxy pipeline
- Requirements 9.2-9.4 are integration/performance concerns, not functional correctness properties

### Property 1: File Modification Detection and State Transition

*For any* tool call, if the tool name matches a file modification pattern, then the session state should transition to dirty (or remain dirty if already dirty), and if the tool name does not match, the state should not change due to that tool call.

**Validates: Requirements 1.1, 1.2, 1.4**

### Property 2: Test Execution Clears Dirty State Across All Languages

*For any* test execution command (across Python, JavaScript, Rust, Go, Java, C#, Ruby, PHP, C/C++, Swift, Kotlin, Scala, Elixir, Dart/Flutter), if the session is in dirty state, then processing the command should transition the state to clean.

**Validates: Requirements 2.1-2.14, 2.17, 2.18**

### Property 3: Clean State Preservation

*For any* session in clean state, if a non-modification tool call is processed (including test execution), then the session state should remain clean.

**Validates: Requirements 2.16**

### Property 4: Completion Signal Detection

*For any* tool call or message, if it contains completion indicators (patterns or tool names), then the completion signal detector should identify it as a completion signal, and if it does not contain indicators, it should not be identified as completion.

**Validates: Requirements 3.1, 3.2, 3.5**

### Property 5: Steering Injection on Dirty Completion

*For any* session in dirty state, if a completion signal is detected, then a steering message should be injected, the tool call should be swallowed, and the response should contain the steering message.

**Validates: Requirements 3.4, 4.1**

### Property 6: No Steering on Clean Completion

*For any* session in clean state, if a completion signal is detected, then no steering message should be injected and the tool call should proceed normally (not swallowed).

**Validates: Requirements 3.3**

### Property 7: Session Isolation

*For any* two different sessions with different session IDs, tool calls processed in one session should not affect the state of the other session.

**Validates: Requirements 8.3**

### Property 8: Test Runner Pattern Matching

*For any* test execution command that matches a registered pattern, the test runner registry should correctly identify the associated language and framework.

**Validates: Requirements 6.3**

### Property 9: Pattern Priority and Specificity

*For any* command that matches multiple test runner patterns, the system should use the pattern with the highest priority (most specific match).

**Validates: Requirements 6.5**

### Property 10: Configuration Precedence

*For any* configuration setting (enabled flag or custom message), if multiple sources provide values (CLI, environment, config file), then the value from the highest precedence source should be used (CLI > Environment > Config).

**Validates: Requirements 5.7**

### Property 11: State TTL Cleanup

*For any* session state that has not been accessed for longer than the configured TTL period, the state should be removed from memory during the next cleanup cycle.

**Validates: Requirements 8.4**

### Property 12: Disabled Feature Has No Effect

*For any* tool call, if the feature is disabled in configuration, then no state tracking should occur and no steering messages should be injected.

**Validates: Requirements 5.11**

### Property 13: Multiple Test Runs Maintain Clean State

*For any* session in clean state, if multiple test execution commands are processed in succession, the state should remain clean without errors.

**Validates: Requirements 8.1**

### Property 14: State Transition Cycle

*For any* session, if the sequence is: modify file → run tests → modify file, then the state transitions should be: clean → dirty → clean → dirty.

**Validates: Requirements 8.2**

### Property 15: Error Handling for Unknown Tools

*For any* unrecognized tool call (not in file modification or test execution patterns), the system should not modify the state, should not raise errors, and should allow the request to proceed.

**Validates: Requirements 8.5, 9.5**

## Error Handling

### Error Scenarios

1. **Pattern Matching Errors**
   - Malformed regex patterns in test runner registry
   - Handle: Log error, skip pattern, continue with remaining patterns
   - Never crash the handler

2. **State Management Errors**
   - Session state corruption
   - Handle: Reset session state to clean, log warning
   - Allow request to proceed

3. **Configuration Errors**
   - Invalid configuration values
   - Handle: Use default values, log warning
   - Feature remains functional with defaults

4. **Tool Call Extraction Errors**
   - Malformed tool arguments
   - Handle: Log debug message, treat as non-matching
   - Allow request to proceed

5. **Memory Pressure**
   - Too many sessions tracked
   - Handle: Enforce max_sessions limit, prune oldest
   - Maintain bounded memory usage

### Error Recovery Strategy

All errors in the handler should be non-fatal. The handler follows these principles:

1. **Fail Open**: If uncertain, allow the tool call through
2. **Log and Continue**: Log errors but never crash the pipeline
3. **Graceful Degradation**: Feature can be disabled without affecting proxy
4. **State Reset**: When in doubt, reset to clean state (safer than dirty)

## Testing Strategy

**Testing Requirements**: This feature MUST achieve 100% test coverage and MUST NOT introduce any regressions. All existing tests must pass (green) after implementation. The testing strategy includes comprehensive unit tests, property-based tests, and integration tests to ensure correctness and reliability.

### Unit Testing

Unit tests will cover:

1. **File Modification Detection**
   - Test each file modification tool name variant
   - Test case-insensitive matching
   - Test with underscores, slashes, and other variations

2. **Test Runner Pattern Matching**
   - Test each language's test runner patterns
   - Test with various command formats (direct, module, wrapper)
   - Test with flags and arguments

3. **Completion Signal Detection**
   - Test completion message patterns
   - Test completion tool names
   - Test ambiguous messages (should not match)

4. **Session State Management**
   - Test state transitions (clean → dirty → clean)
   - Test TTL cleanup
   - Test max sessions enforcement
   - Test session isolation

5. **Configuration Loading**
   - Test precedence (CLI > Env > Config)
   - Test default values
   - Test custom messages

### Property-Based Testing

The testing framework will use **Hypothesis** (Python's property-based testing library) to verify correctness properties.

Each property-based test will run a minimum of 100 iterations to ensure thorough coverage of the input space.

#### Property Test 1: State Transition Consistency

**Feature: test-execution-reminder, Property 1: State Transition Consistency**

Generate random sequences of tool calls (mix of file modifications and other tools) and verify that dirty state is set correctly after each file modification.

**Validates: Requirements 1.1, 1.2**

#### Property Test 2: Test Execution Clears Dirty State

**Feature: test-execution-reminder, Property 2: Test Execution Clears Dirty State**

Generate random test execution commands across all supported languages and verify that dirty state is cleared after each test execution.

**Validates: Requirements 2.1-2.14, 2.16**

#### Property Test 3: Clean State Preservation

**Feature: test-execution-reminder, Property 3: Clean State Preservation**

Generate random non-modification tool calls and verify that clean state is preserved.

**Validates: Requirements 2.16**

#### Property Test 4: Completion Signal Detection Accuracy

**Feature: test-execution-reminder, Property 4: Completion Signal Detection Accuracy**

Generate random messages with completion indicators and verify they are detected correctly.

**Validates: Requirements 3.1, 3.2**

#### Property Test 5: Steering Injection on Dirty Completion

**Feature: test-execution-reminder, Property 5: Steering Injection on Dirty Completion**

Generate random completion signals in dirty state and verify steering is injected.

**Validates: Requirements 3.4, 4.1**

#### Property Test 6: No Steering on Clean Completion

**Feature: test-execution-reminder, Property 6: No Steering on Clean Completion**

Generate random completion signals in clean state and verify no steering is injected.

**Validates: Requirements 3.3**

#### Property Test 7: Session Isolation

**Feature: test-execution-reminder, Property 7: Session Isolation**

Generate random tool calls for multiple sessions and verify state isolation.

**Validates: Requirements 8.3**

#### Property Test 8: Test Runner Pattern Matching

**Feature: test-execution-reminder, Property 8: Test Runner Pattern Matching**

Generate random test commands for each language and verify correct language/framework detection.

**Validates: Requirements 2.15, 6.3**

#### Property Test 9: Configuration Precedence

**Feature: test-execution-reminder, Property 9: Configuration Precedence**

Generate random configuration values from different sources and verify precedence is correct.

**Validates: Requirements 5.7**

#### Property Test 10: State TTL Cleanup

**Feature: test-execution-reminder, Property 10: State TTL Cleanup**

Generate random session states with varying last-seen times and verify TTL cleanup.

**Validates: Requirements 8.4**

### Integration Testing

Integration tests will verify:

1. **Handler Registration**
   - Handler is registered with correct priority
   - Handler is called in correct order

2. **End-to-End Flow**
   - File modification → dirty state
   - Test execution → clean state
   - Completion in dirty state → steering injected
   - Completion in clean state → no steering

3. **Configuration Integration**
   - CLI flags override environment variables
   - Environment variables override config file
   - Custom messages are used correctly

4. **Multi-Session Scenarios**
   - Multiple concurrent sessions maintain independent state
   - Session cleanup works correctly

5. **Regression Prevention**
   - All existing proxy tests must pass
   - No changes to existing handler behavior
   - No performance degradation in request processing

### Test Coverage Requirements

**Mandatory Coverage Targets**:
- **Line Coverage**: 100% of all new code
- **Branch Coverage**: 100% of all conditional logic
- **Property Tests**: Minimum 100 iterations per property
- **Edge Cases**: All error paths and boundary conditions

**Regression Testing**:
- Run full existing test suite after implementation
- Verify all tests pass (green status)
- No test modifications unless fixing actual bugs
- No test deletions unless explicitly approved

**Continuous Verification**:
- Tests must pass on every commit
- Coverage reports must be generated
- No decrease in overall project coverage

## Implementation Notes

### Default Steering Message

```
"You have made code changes but haven't run tests yet. Please run the test suite to verify your changes before completing this task. Once tests pass, you can proceed with task completion."
```

### Test Runner Patterns

The registry will include patterns for:

- **Python**: pytest, python -m pytest, py.test, python -m unittest, unittest
- **JavaScript/TypeScript**: jest, npm test, npm run test, yarn test, vitest, mocha, ava, npm run jest
- **Rust**: cargo test
- **Go**: go test
- **Java**: mvn test, gradle test, ./gradlew test, mvn verify
- **C#**: dotnet test
- **Ruby**: rspec, rake test, ruby -Itest, bundle exec rspec
- **PHP**: phpunit, composer test, vendor/bin/phpunit
- **C/C++**: ctest, make test, cmake --build . --target test
- **Swift**: swift test
- **Kotlin**: ./gradlew test, gradle test (Kotlin projects)
- **Scala**: sbt test
- **Elixir**: mix test
- **Dart/Flutter**: flutter test, dart test

Each pattern will support common variations:
- Direct invocation: `pytest`
- Module invocation: `python -m pytest`
- Wrapper invocation: `pipenv run pytest`, `poetry run pytest`
- With arguments: `pytest tests/`, `pytest -v`

### Performance Considerations

1. **Pattern Matching**: Use compiled regex patterns for efficiency
2. **State Storage**: Use dict for O(1) session lookup
3. **Memory Bounds**: Enforce max_sessions and TTL cleanup
4. **Early Exit**: Check enabled flag first, return immediately if disabled

### Logging Strategy

Log levels:
- **INFO**: Feature enabled/disabled, steering injections, state transitions
- **DEBUG**: Pattern matches, tool call analysis, session state queries
- **WARNING**: Configuration issues, state cleanup, pattern errors
- **ERROR**: Unexpected errors (should be rare, fail open)

## Dependencies

- **Existing**: `IToolCallHandler`, `ToolCallContext`, `ToolCallReactionResult`
- **Existing**: `AppConfig`, CLI argument parsing
- **Existing**: Tool call reactor service and registration
- **New**: Test runner registry (new module)
- **New**: Session state management (new module)
- **New**: Pattern matching utilities (new module)
