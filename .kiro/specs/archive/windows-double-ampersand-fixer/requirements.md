# Requirements Document: Windows Double-Ampersand Command Fixer

## Introduction

This feature implements automatic on-the-fly rewriting of tool call arguments for command execution tools when the detected client OS is Windows. Remote LLMs are predominantly trained on Linux workflows and frequently generate shell commands using `&&` (double ampersand) as a command separator. While this works on Unix-like systems, it causes command execution failures on Windows-based agents/clients.

**Core Behavior**: The proxy transparently intercepts tool calls to command execution tools, detects `&&` patterns in command arguments, and replaces them with a Windows-compatible separator (`;`) before the tool call reaches the client agent. This happens on-the-fly without any additional round trips to the remote LLM.

**Non-Goals**: This feature must NOT modify arguments for file editing tools (e.g., `write_file`, `str_replace`, `Edit`, `Create`) as replacing `&&` in file content would cause data corruption.

**Quality Requirements**: This feature must have comprehensive test coverage, must not introduce any regressions to the existing test suite, and must follow industry best practices for transparent proxying.

## Glossary

- **Double Ampersand (`&&`)**: A shell command separator used in Unix-like systems to chain commands (execute second command only if first succeeds)
- **Command Execution Tool**: Any tool that executes shell commands locally, such as `Execute`, `run_command`, `bash`, `shell`, etc.
- **File Editing Tool**: Any tool that modifies file contents, such as `write_file`, `Edit`, `Create`, `str_replace`, etc.
- **Client OS**: The operating system of the client/agent detected from request context (stored in `SessionState.client_os`)
- **On-the-fly Rewrite**: Modification of tool call arguments as they pass through the proxy without requiring additional LLM round trips
- **Windows-Compatible Separator**: The semicolon (`;`) character which can separate commands on Windows PowerShell/cmd

## Requirements

### Requirement 1: Command Argument Detection and Rewriting

**User Story:** As a Windows user of an agentic coding tool, I want the proxy to automatically fix double-ampersand command separators in tool calls, so that commands from LLMs work correctly on my Windows system without failing.

#### Acceptance Criteria

1. WHEN a tool call to a command execution tool is detected AND the session's `client_os` contains "win" (case-insensitive) THEN the system SHALL scan the command argument for `&&` patterns
2. WHEN the system detects `&&` in a command argument THEN the system SHALL replace all occurrences of `&&` with `;`
3. WHEN the replacement occurs THEN the system SHALL preserve whitespace around the separator (e.g., ` && ` becomes ` ; `)
4. WHEN the replacement occurs THEN the system SHALL log the modification at INFO level with the original and modified command (truncated for long commands)
5. WHEN no `&&` patterns are found THEN the system SHALL pass the tool call through unchanged
6. WHEN the `client_os` does not contain "win" (or is None/empty) THEN the system SHALL NOT perform any replacements

### Requirement 2: Tool Name Filtering

**User Story:** As a developer maintaining the proxy, I want the fixer to only target command execution tools, so that file editing operations are not corrupted.

#### Acceptance Criteria

1. WHEN a tool call is detected THEN the system SHALL match the tool name against a predefined list of command execution tool names
2. WHEN the tool name matches a command execution pattern (e.g., `Execute`, `run_command`, `bash`, `shell`, `terminal`, `exec`, `run`, `execute_command`) THEN the system SHALL apply the `&&` replacement logic
3. WHEN the tool name matches a file editing pattern (e.g., `write_file`, `Edit`, `Create`, `str_replace`, `patch_file`, `apply_diff`) THEN the system SHALL NOT apply any replacement logic
4. WHEN an unknown tool name is encountered THEN the system SHALL NOT apply any replacement logic (fail-safe to prevent corruption)
5. WHEN matching tool names THEN the system SHALL use case-insensitive matching

### Requirement 3: Configuration and Feature Flag

**User Story:** As a system administrator, I want to be able to disable this feature if needed, so that I have control over proxy behavior.

#### Acceptance Criteria

1. WHEN the proxy starts with `--disable-double-ampersand-fixes-for-windows` CLI flag THEN the system SHALL disable the double-ampersand fixer feature
2. WHEN the environment variable `DISABLE_DOUBLE_AMPERSAND_FIXES_FOR_WINDOWS` is set to `true` (or `1`, `yes`) THEN the system SHALL disable the feature
3. WHEN the config file contains `double_ampersand_fixes_for_windows_enabled: false` THEN the system SHALL disable the feature
4. WHEN the feature is not explicitly disabled THEN the system SHALL enable the feature by default
5. WHEN multiple configuration sources are present THEN the system SHALL apply precedence: CLI flags override environment variables, environment variables override config file
6. WHEN the feature is disabled THEN the system SHALL have zero performance impact on request processing

### Requirement 4: Integration with Tool Call Reactor

**User Story:** As a developer, I want this feature to integrate with the existing tool call reactor middleware, so that it fits naturally into the proxy architecture.

#### Acceptance Criteria

1. WHEN the feature is enabled THEN the system SHALL integrate as a handler in the tool call reactor pipeline
2. WHEN processing a tool call THEN the system SHALL NOT swallow the tool call (it must pass through to the client with modified arguments)
3. WHEN a tool call's arguments are modified THEN the modified arguments SHALL be written back to the response before it reaches the client
4. WHEN the feature processes a tool call THEN it SHALL access the session's `client_os` from the session state
5. WHEN errors occur during processing THEN the system SHALL log the error and allow the request to proceed with original arguments

### Requirement 5: Argument Extraction and Modification

**User Story:** As a developer, I want the system to correctly extract and modify command strings from various argument formats, so that the feature works across different tool call schemas.

#### Acceptance Criteria

1. WHEN tool arguments contain a `command` field (string) THEN the system SHALL apply replacement to that field
2. WHEN tool arguments contain a `cmd` field (string) THEN the system SHALL apply replacement to that field
3. WHEN tool arguments are a raw string THEN the system SHALL apply replacement to the entire string
4. WHEN tool arguments contain nested fields (e.g., `{"input": {"command": "..."}}`) THEN the system SHALL apply replacement to the nested command field
5. WHEN the command string contains `&&` inside quoted strings THEN the system SHALL still replace them (conservative approach for Windows compatibility)

### Requirement 6: Edge Cases and Safety

**User Story:** As a user, I want the system to handle edge cases safely, so that commands are not corrupted by overly aggressive replacement.

#### Acceptance Criteria

1. WHEN the command contains multiple `&&` sequences THEN the system SHALL replace all occurrences
2. WHEN the command is empty or whitespace-only THEN the system SHALL return it unchanged
3. WHEN the command is extremely long (>10000 characters) THEN the system SHALL still process it (no arbitrary limits)
4. WHEN the tool arguments cannot be parsed as JSON THEN the system SHALL NOT modify the raw string (fail-safe)
5. WHEN the command contains only a single `&` (not `&&`) THEN the system SHALL NOT modify it
6. WHEN the command contains `&&&` or more THEN the system SHALL replace only the `&&` portions correctly

### Requirement 7: Logging and Observability

**User Story:** As a system administrator, I want comprehensive logging of the feature's behavior, so that I can debug issues and understand what modifications are being made.

#### Acceptance Criteria

1. WHEN the feature is enabled and a modification occurs THEN the system SHALL log at INFO level: session ID, tool name, original command (first 200 chars), modified command (first 200 chars)
2. WHEN the feature is enabled but no modification is needed THEN the system SHALL log at DEBUG level that the tool call was checked but no changes were needed
3. WHEN the feature skips a tool call due to tool name filtering THEN the system SHALL log at DEBUG level
4. WHEN the feature skips a tool call due to non-Windows client OS THEN the system SHALL log at DEBUG level
5. WHEN the feature encounters an error THEN the system SHALL log at WARNING level with the error details

### Requirement 8: Documentation

**User Story:** As a user, I want documentation explaining this feature, so that I understand what the proxy is doing and how to configure it.

#### Acceptance Criteria

1. WHEN the feature is documented THEN the documentation SHALL be placed in `docs/user_guide/features/windows-double-ampersand-fixer.md`
2. WHEN the documentation is written THEN it SHALL explain the problem being solved (Linux-trained LLMs vs Windows clients)
3. WHEN the documentation is written THEN it SHALL list all configuration options (CLI flag, env var, config file)
4. WHEN the documentation is written THEN it SHALL explain which tool calls are affected and which are protected
5. WHEN the documentation is written THEN it SHALL provide examples of before/after command transformations
