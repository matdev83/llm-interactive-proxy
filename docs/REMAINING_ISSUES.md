# Remaining Issues After DI Container Fixes

This document summarizes the remaining issues that need to be addressed after the Dependency Injection (DI) container fixes. The main focus of the current work was to fix the core DI container issues, which has been largely successful. However, there are still some remaining issues that need to be addressed in future work.

## Current Status

- **Tests Passing**: 511 tests passing (65.6%)
- **Tests Skipped**: 20 tests skipped (2.6%)
- **Tests Failing**: 40 tests failing (5.1%)
- **Tests Deselected**: 208 tests deselected (26.7%)

## Categories of Remaining Issues

### 1. Command Handling and Message Processing

Many of the failing tests are related to command handling and message processing. The command system has been refactored in the new architecture, and the tests need to be updated to match the new behavior.

Key issues:
- Command response format has changed (e.g., "Model set to X" is now "Backend changed to Y; Model changed to Z")
- Command parameter validation has changed (e.g., "Unknown parameter: X" vs "set: no valid parameters provided or action taken")
- Session state updates are not being applied correctly in some tests

Affected tests:
- `tests/unit/proxy_logic_tests/test_process_commands_in_messages.py`
- `tests/unit/proxy_logic_tests/test_process_text_for_commands.py`
- `tests/unit/chat_completions_tests/test_temperature_commands.py`
- `tests/unit/chat_completions_tests/test_project_dir_commands.py`
- `tests/unit/chat_completions_tests/test_pwd_command.py`

### 2. Session History and State Management

Some tests related to session history and state management are failing because the session state is not being updated correctly or the history is not being recorded properly.

Key issues:
- Streaming responses are not being recorded correctly in session history
- Session state is not being updated correctly for some commands

Affected tests:
- `tests/unit/chat_completions_tests/test_session_history.py`

### 3. API Authentication

Some tests related to API authentication are failing because the API keys are not being properly set up or validated.

Key issues:
- API key authentication is failing in some tests
- The models endpoint is returning 401 Unauthorized instead of 200 OK

Affected tests:
- `tests/unit/test_models_endpoint.py`

### 4. Configuration Persistence

Some tests related to configuration persistence are failing because the configuration is not being loaded or validated correctly.

Key issues:
- Invalid persisted backends are not being handled correctly

Affected tests:
- `tests/unit/test_config_persistence.py`

### 5. Multimodal and Cross-Protocol Tests

Some tests related to multimodal and cross-protocol functionality are failing because the service provider is not being properly initialized.

Key issues:
- `'State' object has no attribute 'service_provider'` error in multimodal tests

Affected tests:
- `tests/unit/chat_completions_tests/test_multimodal_cross_protocol.py`

### 6. One-off Command Tests

Some tests related to one-off commands are failing because the backends are not being properly initialized.

Key issues:
- `'State' object has no attribute 'gemini_backend'` error in one-off command tests

Affected tests:
- `tests/unit/chat_completions_tests/test_oneoff_command.py`

### 7. Project Command Tests

Some tests related to project commands are failing because the session service API has changed.

Key issues:
- `'SessionService' object has no attribute 'get_session_async'` error in project command tests

Affected tests:
- `tests/unit/chat_completions_tests/test_project_commands.py`

## Next Steps

1. Update command handling tests to match the new command response format and behavior
2. Fix session history and state management issues
3. Fix API authentication issues in models endpoint tests
4. Fix configuration persistence issues
5. Fix multimodal and cross-protocol tests
6. Fix one-off command tests
7. Fix project command tests
8. Fix anthropic connector tests (separate from DI issues)

## Conclusion

The core DI container issues have been largely fixed, but there are still some remaining issues that need to be addressed. These issues are mostly related to the command system and session management, which have been refactored in the new architecture. The tests need to be updated to match the new behavior.
