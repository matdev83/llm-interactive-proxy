# Requirements Document

## Introduction

This feature implements an intelligent test execution reminder system that detects when coding agents have modified files but haven't run tests before attempting to complete a task. The system tracks file modification tool calls and test execution commands, maintaining a "dirty state" indicator. When an agent attempts to signal task completion while in a dirty state, the proxy automatically injects a steering message reminding the agent to run tests first.

**Core Behavior**: The proxy intercepts the completion attempt, sends a new request to the backend LLM with all conversation history plus a steering message instructing it to run tests, and forwards the LLM's response back to the client. This prevents agents from completing tasks without verifying their changes work correctly.

**Quality Requirements**: This feature must have 100% test coverage, must not introduce any regressions to the existing test suite (all tests must remain green), and must follow industry best practices for agentic coding workflows.

## Glossary

- **File Modification Tool Call**: Any tool call that modifies source code files, including write_file, replace_lines, str_replace, apply_diff, apply_patch, patch_file, multiedit, fs/write_text_file, insert_content, and patchFile
- **Test Execution Command**: Any command that runs a test suite across supported languages and frameworks (see Test Runner Patterns)
- **Test Runner Patterns**: Recognized test execution commands including pytest (Python), jest/vitest/mocha (JavaScript/TypeScript), cargo test (Rust), go test (Go), mvn test/gradle test (Java), dotnet test (C#), rspec (Ruby), phpunit (PHP), and others
- **Dirty State**: A session state where file modifications have occurred but tests have not been run since the last modification
- **Clean State**: A session state where either no modifications have occurred, or tests have been run after all modifications
- **Task Completion Signal**: Any tool call or message pattern that indicates the agent believes the task is complete
- **Steering Message**: An injected system message that guides the agent to take a specific action
- **Test Execution Reminder System**: The complete system that tracks modifications, detects completion attempts, and injects steering messages

## Requirements

### Requirement 1

**User Story:** As a human user of the proxy, I want the system to track when agents modify files, so that I can ensure tests are run before task completion.

#### Acceptance Criteria

1. WHEN an agent invokes a file modification tool call THEN the system SHALL record the modification event in the session state
2. WHEN multiple file modification tool calls occur in sequence THEN the system SHALL maintain the dirty state until tests are executed
3. WHEN a file modification tool call is detected THEN the system SHALL log the event with the tool name and session identifier
4. WHEN the session state is queried THEN the system SHALL accurately report whether the state is dirty or clean
5. WHEN a new session begins THEN the system SHALL initialize the state as clean

### Requirement 2

**User Story:** As a human user of the proxy, I want the system to recognize when tests are executed across multiple programming languages, so that the dirty state can be cleared appropriately regardless of the tech stack.

#### Acceptance Criteria

1. WHEN an agent executes a Python test command (pytest, python -m pytest, py.test, python -m unittest) THEN the system SHALL transition the session state from dirty to clean
2. WHEN an agent executes a JavaScript/TypeScript test command (jest, npm test, npm run test, yarn test, vitest, mocha, ava) THEN the system SHALL transition the session state from dirty to clean
3. WHEN an agent executes a Rust test command (cargo test) THEN the system SHALL transition the session state from dirty to clean
4. WHEN an agent executes a Go test command (go test) THEN the system SHALL transition the session state from dirty to clean
5. WHEN an agent executes a Java test command (mvn test, gradle test, ./gradlew test) THEN the system SHALL transition the session state from dirty to clean
6. WHEN an agent executes a C# test command (dotnet test) THEN the system SHALL transition the session state from dirty to clean
7. WHEN an agent executes a Ruby test command (rspec, rake test, ruby -Itest) THEN the system SHALL transition the session state from dirty to clean
8. WHEN an agent executes a PHP test command (phpunit, composer test) THEN the system SHALL transition the session state from dirty to clean
9. WHEN an agent executes a C/C++ test command (ctest, make test) THEN the system SHALL transition the session state from dirty to clean
10. WHEN an agent executes a Swift test command (swift test) THEN the system SHALL transition the session state from dirty to clean
11. WHEN an agent executes a Kotlin test command (./gradlew test for Kotlin projects) THEN the system SHALL transition the session state from dirty to clean
12. WHEN an agent executes a Scala test command (sbt test) THEN the system SHALL transition the session state from dirty to clean
13. WHEN an agent executes an Elixir test command (mix test) THEN the system SHALL transition the session state from dirty to clean
14. WHEN an agent executes a Dart/Flutter test command (flutter test, dart test) THEN the system SHALL transition the session state from dirty to clean
15. WHEN a test execution command is detected THEN the system SHALL log the event with the command pattern, language detected, and session identifier
16. WHEN test execution occurs in a clean state THEN the system SHALL maintain the clean state
17. WHEN partial test execution occurs (specific test files or functions) THEN the system SHALL still transition to clean state
18. WHEN test execution fails THEN the system SHALL still transition to clean state (execution occurred, regardless of outcome)

### Requirement 3

**User Story:** As a human user of the proxy, I want the system to detect task completion signals, so that I can intervene before the agent finalizes without running tests.

#### Acceptance Criteria

1. WHEN an agent sends a message containing completion indicators THEN the system SHALL identify it as a task completion signal
2. WHEN an agent invokes a task completion tool call THEN the system SHALL identify it as a task completion signal
3. WHEN a task completion signal is detected in clean state THEN the system SHALL allow the response to proceed normally
4. WHEN a task completion signal is detected in dirty state THEN the system SHALL trigger the steering intervention
5. WHEN ambiguous messages are analyzed THEN the system SHALL use pattern matching to distinguish completion signals from progress updates

### Requirement 4

**User Story:** As a human user of the proxy, I want the system to inject steering messages when needed, so that agents are reminded to run tests before completing tasks.

#### Acceptance Criteria

1. WHEN a task completion signal occurs in dirty state THEN the system SHALL swallow the tool call and return a steering message response
2. WHEN a steering message is returned THEN the proxy infrastructure SHALL send a new request to the backend LLM with all conversation history plus the steering message
3. WHEN the backend LLM responds to the steering message THEN the proxy SHALL forward the response to the client
4. WHEN the steering message is formatted THEN the system SHALL clearly instruct the agent to run tests before finalizing
5. WHEN the steering intervention occurs THEN all conversation context SHALL be preserved in the new request to the backend

### Requirement 5

**User Story:** As a system administrator, I want the feature to be configurable through multiple methods, so that I can enable or disable it based on deployment needs using CLI flags, environment variables, or config files.

#### Acceptance Criteria

1. WHEN the proxy starts with --test-execution-reminder-enabled CLI flag THEN the system SHALL enable the test execution reminder feature
2. WHEN the proxy starts with --no-test-execution-reminder-enabled CLI flag THEN the system SHALL disable the test execution reminder feature
3. WHEN the TEST_EXECUTION_REMINDER_ENABLED environment variable is set to true THEN the system SHALL enable the feature
4. WHEN the TEST_EXECUTION_REMINDER_ENABLED environment variable is set to false THEN the system SHALL disable the feature
5. WHEN the config file contains test_execution_reminder_enabled: true THEN the system SHALL enable the feature
6. WHEN the config file contains test_execution_reminder_enabled: false THEN the system SHALL disable the feature
7. WHEN multiple configuration sources are present THEN the system SHALL apply precedence: CLI flags override environment variables, environment variables override config file
8. WHEN a custom steering message is provided via TEST_EXECUTION_REMINDER_MESSAGE environment variable THEN the system SHALL use the custom message
9. WHEN a custom steering message is provided in the config file (test_execution_reminder_message) THEN the system SHALL use the custom message
10. WHEN no custom message is configured THEN the system SHALL use a default message instructing the agent to run tests
11. WHEN the feature is disabled in configuration THEN the system SHALL not track modifications or inject steering messages
12. WHEN the feature is enabled in configuration THEN the system SHALL activate all tracking and steering behaviors

### Requirement 6

**User Story:** As a developer, I want the system to maintain a comprehensive registry of test runner patterns, so that new languages and frameworks can be easily supported.

#### Acceptance Criteria

1. WHEN the system initializes THEN the system SHALL load a registry of test runner patterns organized by language and framework
2. WHEN a command is analyzed THEN the system SHALL match it against all registered test runner patterns
3. WHEN a test runner pattern is matched THEN the system SHALL identify the language or framework associated with the pattern
4. WHEN the registry is extended with new patterns THEN the system SHALL support the new patterns without code changes to the core logic
5. WHEN multiple patterns could match a command THEN the system SHALL use the most specific pattern match

### Requirement 7

**User Story:** As a developer, I want comprehensive logging of the feature's behavior, so that I can debug issues and understand system decisions.

#### Acceptance Criteria

1. WHEN a file modification is tracked THEN the system SHALL log the tool name, session ID, and timestamp
2. WHEN a test execution is detected THEN the system SHALL log the command pattern, detected language/framework, session ID, and state transition
3. WHEN a task completion signal is detected THEN the system SHALL log the detection reason and current state
4. WHEN a steering message is injected THEN the system SHALL log the injection event with session ID and message preview
5. WHEN the feature is disabled THEN the system SHALL log a single initialization message indicating disabled status
6. WHEN the feature is enabled THEN the system SHALL log the initialization with the count of registered test runner patterns

### Requirement 8

**User Story:** As a human user of the proxy, I want the system to handle edge cases gracefully, so that the feature works reliably in all scenarios.

#### Acceptance Criteria

1. WHEN an agent runs tests multiple times in succession THEN the system SHALL maintain clean state without errors
2. WHEN an agent modifies files after running tests THEN the system SHALL correctly transition back to dirty state
3. WHEN multiple sessions are active concurrently THEN the system SHALL maintain independent state for each session
4. WHEN a session ends THEN the system SHALL clean up the associated state tracking data
5. WHEN the system encounters an unrecognized tool call THEN the system SHALL not modify the state or raise errors

### Requirement 9

**User Story:** As a developer, I want the feature to integrate seamlessly with existing middleware, so that it doesn't disrupt current functionality.

#### Acceptance Criteria

1. WHEN the feature is enabled THEN the system SHALL integrate with the existing tool call reactor pipeline
2. WHEN other middleware processes requests THEN the system SHALL not interfere with their operation
3. WHEN the feature injects a steering message THEN the system SHALL preserve all existing request metadata
4. WHEN the feature is disabled THEN the system SHALL have zero performance impact on request processing
5. WHEN the feature encounters errors THEN the system SHALL log the error and allow the request to proceed normally
