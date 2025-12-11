# Implementation Plan: Test Execution Reminder System

- [x] 1. Set up core data structures and configuration





  - Create `SessionState` dataclass for tracking dirty/clean state per session
  - Add configuration fields to `AppConfig` (test_execution_reminder_enabled, test_execution_reminder_message)
  - Add CLI arguments for enabling/disabling the feature
  - Add environment variable support (TEST_EXECUTION_REMINDER_ENABLED, TEST_EXECUTION_REMINDER_MESSAGE)
  - _Requirements: 5.1-5.10_

- [x] 1.1 Write property test for configuration precedence


  - **Property 10: Configuration Precedence**
  - **Validates: Requirements 5.7**
-

- [x] 2. Implement FileModificationDetector




  - Create `FileModificationDetector` class with tool name matching logic
  - Support all specified tool names (write_file, str_replace, apply_diff, etc.)
  - Implement case-insensitive matching with normalization
  - Handle tool name variations (underscores, slashes, etc.)
  - _Requirements: 1.1, 1.2_

- [x] 2.1 Write property test for file modification detection


  - **Property 1: File Modification Detection and State Transition**
  - **Validates: Requirements 1.1, 1.2, 1.4**

-

- [x] 3. Implement TestRunnerRegistry



  - Create `TestRunnerPattern` dataclass for pattern definitions
  - Create `TestRunnerRegistry` class with pattern matching logic
  - Implement `_load_default_patterns()` for Python test runners (pytest, unittest)
  - Implement `match_command()` method with regex pattern matching
  - Implement `register_pattern()` for extensibility
  - _Requirements: 2.1, 6.1, 6.2, 6.3_

- [x] 3.1 Write property test for Python test runner detection

  - **Property 2: Test Execution Clears Dirty State Across All Languages** (Python subset)
  - **Validates: Requirements 2.1**


- [x] 4. Add JavaScript/TypeScript test runner patterns




  - Add patterns for jest, npm test, yarn test, vitest, mocha, ava
  - Support module invocation and wrapper patterns
  - _Requirements: 2.2_

- [x] 4.1 Write property test for JavaScript test runner detection


  - **Property 2: Test Execution Clears Dirty State Across All Languages** (JavaScript subset)

  - **Validates: Requirements 2.2**

- [x] 5. Add remaining language test runner patterns




  - Add patterns for Rust (cargo test)
  - Add patterns for Go (go test)
  - Add patterns for Java (mvn test, gradle test)
  - Add patterns for C# (dotnet test)
  - Add patterns for Ruby (rspec, rake test)
  - Add patterns for PHP (phpunit, composer test)
  - Add patterns for C/C++ (ctest, make test)
  - Add patterns for Swift (swift test)
  - Add patterns for Kotlin (gradle test)
  - Add patterns for Scala (sbt test)
  - Add patterns for Elixir (mix test)
  - Add patterns for Dart/Flutter (flutter test, dart test)
  - _Requirements: 2.3-2.14_

- [x] 5.1 Write property test for all language test runner detection


  - **Property 2: Test Execution Clears Dirty State Across All Languages** (complete)
  - **Validates: Requirements 2.1-2.14, 2.17, 2.18**

- [x] 5.2 Write property test for pattern priority


  - **Property 9: Pattern Priority and Specificity**
  - **Validates: Requirements 6.5**

- [x] 6. Implement CompletionSignalDetector





  - Create `CompletionSignalDetector` class
  - Define completion message patterns (regex)
  - Define completion tool names
  - Implement `is_completion_signal()` method
  - _Requirements: 3.1, 3.2, 3.5_

- [x] 6.1 Write property test for completion signal detection


  - **Property 4: Completion Signal Detection**
  - **Validates: Requirements 3.1, 3.2, 3.5**
-

- [x] 7. Implement TestExecutionReminderHandler core logic




  - Create `TestExecutionReminderHandler` class implementing `IToolCallHandler`
  - Implement `name` and `priority` properties (priority=90)
  - Initialize session state dictionary with TTL tracking
  - Implement `_prune_session_state()` for memory management
  - Add default steering message constant
  - _Requirements: 8.4, 9.1_

- [x] 8. Implement handler's can_handle method




  - Check if feature is enabled (early exit if disabled)
  - Extract tool name and arguments from context
  - Check if tool is file modification (mark dirty if yes)
  - Check if tool is test execution (mark clean if yes)
  - Check if tool is completion signal
  - Return true only for completion signals in dirty state
  - _Requirements: 1.1, 2.1-2.18, 3.1-3.5_

- [x] 8.1 Write property test for state transitions

  - **Property 1: File Modification Detection and State Transition**
  - **Validates: Requirements 1.1, 1.2, 1.4**

- [x] 8.2 Write property test for clean state preservation

  - **Property 3: Clean State Preservation**
  - **Validates: Requirements 2.16**
-

- [x] 9. Implement handler's handle method



  - Verify feature is enabled
  - Verify dirty state and completion signal
  - Log steering intervention
  - Return ToolCallReactionResult with should_swallow=True
  - Include steering message in replacement_response
  - Add metadata (handler name, tool name, source)
  - _Requirements: 3.4, 4.1, 4.4, 4.5_

- [x] 9.1 Write property test for steering injection on dirty completion


  - **Property 5: Steering Injection on Dirty Completion**
  - **Validates: Requirements 3.4, 4.1**

- [x] 9.2 Write property test for no steering on clean completion


  - **Property 6: No Steering on Clean Completion**
  - **Validates: Requirements 3.3**

- [x] 10. Implement session isolation and cleanup




  - Ensure each session has independent state
  - Implement TTL-based cleanup in `_prune_session_state()`
  - Enforce max_sessions limit
  - Remove oldest sessions when limit exceeded
  - _Requirements: 8.3, 8.4_

- [x] 10.1 Write property test for session isolation

  - **Property 7: Session Isolation**
  - **Validates: Requirements 8.3**

- [x] 10.2 Write property test for TTL cleanup

  - **Property 11: State TTL Cleanup**
  - **Validates: Requirements 8.4**

- [x] 11. Implement error handling




  - Add try-except blocks around pattern matching
  - Add try-except blocks around state management
  - Log errors at appropriate levels
  - Fail open (allow requests through on errors)
  - Never crash the pipeline
  - _Requirements: 8.5, 9.5_

- [x] 11.1 Write property test for error handling

  - **Property 15: Error Handling for Unknown Tools**
  - **Validates: Requirements 8.5, 9.5**
-

- [x] 12. Implement disabled feature behavior



  - Early exit in can_handle if disabled
  - No state tracking when disabled
  - No steering injection when disabled
  - Log initialization message indicating disabled status
  - _Requirements: 5.11_

- [x] 12.1 Write property test for disabled feature


  - **Property 12: Disabled Feature Has No Effect**
  - **Validates: Requirements 5.11**
- [x] 13. Add comprehensive logging




- [ ] 13. Add comprehensive logging

  - Log feature initialization (enabled/disabled, pattern count)
  - Log file modifications (tool name, session ID, timestamp)
  - Log test executions (command, language, session ID, state transition)
  - Log completion signal detection (reason, current state)
  - Log steering injections (session ID, message preview)
  - Use appropriate log levels (INFO, DEBUG, WARNING, ERROR)
  - _Requirements: 7.1-7.6_

- [x] 14. Integrate handler with tool call reactor service





  - Register handler in application startup
  - Verify handler priority is correct (90)
  - Ensure handler is called in correct order
  - Test with existing handlers (should not interfere)
  - _Requirements: 9.1, 9.2_

- [x] 15. Add configuration file support





  - Update config.example.yaml with new fields
  - Update tool_call_reactor_config.yaml if needed
  - Document configuration options
  - _Requirements: 5.5, 5.6_
-

- [x] 16. Update sample.env with new environment variables



  - Add TEST_EXECUTION_REMINDER_ENABLED
  - Add TEST_EXECUTION_REMINDER_MESSAGE
  - Document expected values
  - _Requirements: 5.3, 5.4, 5.8_

- [x] 17. Write property test for multiple test runs




  - **Property 13: Multiple Test Runs Maintain Clean State**
  - **Validates: Requirements 8.1**

- [x] 18. Write property test for state transition cycle





  - **Property 14: State Transition Cycle**
  - **Validates: Requirements 8.2**

- [x] 19. Write property test for test runner pattern matching





  - **Property 8: Test Runner Pattern Matching**
  - **Validates: Requirements 6.3**

- [x] 20. Write unit tests for FileModificationDetector



  - Test each tool name variant
  - Test case-insensitive matching
  - Test normalization (underscores, slashes)
  - Test edge cases (empty strings, None)
  - _Requirements: 1.1, 1.2_
-

- [x] 21. Write unit tests for TestRunnerRegistry



  - Test pattern loading
  - Test pattern registration
  - Test command matching for each language
  - Test priority ordering
  - Test extensibility
  - _Requirements: 6.1-6.5_
-

- [x] 22. Write unit tests for CompletionSignalDetector



  - Test completion message patterns
  - Test completion tool names
  - Test ambiguous messages (should not match)
  - Test edge cases
  - _Requirements: 3.1, 3.2, 3.5_
-

- [x] 23. Write unit tests for SessionState



  - Test state initialization
  - Test state transitions
  - Test timestamp tracking
  - Test modification counting
  - _Requirements: 1.4, 1.5_
-

- [x] 24. Write unit tests for TestExecutionReminderHandler



  - Test handler initialization
  - Test name and priority properties
  - Test can_handle logic for all scenarios
  - Test handle logic for all scenarios
  - Test session state management
  - Test TTL cleanup
  - Test max sessions enforcement
  - Test error handling
  - _Requirements: All_

- [x] 25. Write integration tests




- [ ] 25. Write integration tests
  - Test handler registration
  - Test end-to-end flow (modify → test → complete)
  - Test configuration precedence
  - Test multi-session scenarios
  - Test with existing handlers (no interference)
  - _Requirements: 9.1, 9.2, 9.3_
-

- [x] 26. Run full test suite and verify no regressions




  - Run all existing tests
  - Verify all tests pass (green)
  - Generate coverage report
  - Verify 100% coverage for new code
  - _Requirements: All (quality requirement)_
-

- [x] 27. Final verification and documentation




  - Verify all requirements are met
  - Verify all properties are tested
  - Update CHANGELOG.md with feature description
  - Update README.md if needed
  - Create usage examples
  - _Requirements: All_

## Phase 2: Improved Completion Detection (Reliable Methods)

### Background
The initial implementation used unreliable pattern matching against speculative model output. This phase replaces it with two reliable detection methods:
1. **Primary**: Actual completion tool names from popular agents (e.g., `attempt_completion` from Cline/Roo-Code)
2. **Secondary**: Streaming `finish_reason` markers (e.g., "stop", "tool_calls", "length")

### Current Status
- ✅ Core implementation updated (CompletionSignalDetector and Handler)
- ⚠️ 17 unit tests failing due to API changes (expected - need rewrite)
- ⏳ Tests need to be updated to use new detection methods
- ⏳ Documentation needs to be updated

### Known Failing Tests
The following 17 tests in `test_completion_signal_detector.py` are failing with:
`TypeError: CompletionSignalDetector.is_completion_signal() got an unexpected keyword argument 'response_text'`

These tests were written for the old pattern-matching approach and need to be rewritten for the new reliable detection methods (tool names + finish_reason).

### Implementation Tasks

- [ ] 28. Update CompletionSignalDetector implementation
  - [x] 28.1 Remove unreliable regex pattern matching (COMPLETION_PATTERNS)
  - [x] 28.2 Add `attempt_completion` to COMPLETION_TOOLS (used by Cline, Roo-Code)
  - [x] 28.3 Add FINISH_REASONS set (stop, tool_calls, length, end_turn)
  - [x] 28.4 Update is_completion_signal() signature to accept finish_reason and metadata
  - [x] 28.5 Add _is_finish_reason() method for finish_reason validation
  - [x] 28.6 Remove _contains_completion_pattern() method
  - _Requirements: 3.1, 3.2_

- [ ] 29. Update TestExecutionReminderHandler to use new detection
  - [x] 29.1 Add _extract_finish_reason() method to extract from full_response
  - [x] 29.2 Add _extract_metadata() method to extract metadata dict
  - [x] 29.3 Update can_handle() to pass finish_reason and metadata to detector
  - [x] 29.4 Update handle() to pass finish_reason and metadata to detector
  - [x] 29.5 Update logging to show finish_reason instead of pattern matching
  - [x] 29.6 Remove _extract_response_text() method (no longer needed)




  - _Requirements: 3.1, 3.2, 3.4_

- [x] 30. Update unit tests for CompletionSignalDetector





  - [x] 30.1 Fix 17 failing tests that use old response_text parameter


    - Tests failing: test_completion_message_detection, test_ambiguous_message_rejection,
      test_non_completion_message_rejection, test_combined_detection, test_empty_and_none_handling,
      test_case_insensitive_matching, test_whitespace_variations, test_pattern_position_in_message,
      test_multiple_patterns_in_message, test_special_characters_in_messages, test_long_messages,
      test_negative_lookbehind_patterns, test_word_boundary_matching, test_all_completion_message_patterns,
      test_ambiguous_messages_comprehensive, test_edge_case_almost_ready_for_review,
      test_empty_tool_name_with_completion_message
    - Error: "CompletionSignalDetector.is_completion_signal() got an unexpected keyword argument 'response_text'"
    - Action: Remove/rewrite these pattern matching tests
  - [x] 30.2 Add tests for attempt_completion tool detection

  - [x] 30.3 Add tests for finish_reason detection (stop, tool_calls, length, end_turn)

  - [x] 30.4 Add tests for finish_reason in metadata

  - [x] 30.5 Add tests for finish_reason in choices array (OpenAI format)

  - [x] 30.6 Add tests for combined tool + finish_reason detection

  - [x] 30.7 Update edge case tests to use new parameters

  - _Requirements: 3.1, 3.2_
-

- [x] 31. Update property-based tests for completion detection




  - [x] 31.1 Update test_completion_signal_detection_properties.py


  - [x] 31.2 Remove pattern matching property tests

  - [x] 31.3 Add property tests for tool name detection

  - [x] 31.4 Add property tests for finish_reason detection

  - [x] 31.5 Ensure 100+ iterations per property

  - _Requirements: 3.1, 3.2_
- [x] 32. Update integration tests




- [ ] 32. Update integration tests

  - [x] 32.1 Update test_test_execution_reminder_integration.py

  - [x] 32.2 Add tests with attempt_completion tool

  - [x] 32.3 Add tests with finish_reason in responses

  - [x] 32.4 Verify end-to-end flow with real agent tool names

  - _Requirements: 3.1, 3.2, 9.1_

- [x] 33. Update handler unit tests




  - [x] 33.1 Update test_test_execution_reminder_handler.py


  - [x] 33.2 Update tests to use finish_reason instead of response_text

  - [x] 33.3 Add tests for _extract_finish_reason() method

  - [x] 33.4 Add tests for _extract_metadata() method

  - [x] 33.5 Update completion detection tests

  - _Requirements: 3.1, 3.2_
-

- [x] 34. Research additional agent completion tools




  - [x] 34.1 Check Aider source code for completion tools


  - [x] 34.2 Check Gemini CLI source code for completion tools


  - [x] 34.3 Check OpenCode source code for completion tools


  - [x] 34.4 Check Crush source code for completion tools


  - [x] 34.5 Add any discovered tool names to COMPLETION_TOOLS


  - _Requirements: 3.1, 3.2_

- [x] 35. Update documentation



  - [x] 35.3 Update user guide (docs/user_guide/test-execution-reminder.md)


  - [x] 35.4 Update CHANGELOG.md with improved detection


  - [x] 35.5 Document which agents use which completion tools


  - _Requirements: All_
-

- [x] 36. Verify all tests pass




  - [x] 36.1 Run all unit tests for test execution reminder


  - [x] 36.2 Run all property tests


  - [x] 36.3 Run all integration tests


  - [x] 36.4 Verify no regressions in full test suite




  - [x] 36.5 Verify 100% code coverage maintained


  - _Requirements: All_

- [x] 37. Final validation




  - [x] 37.1 Verify attempt_completion detection works

  - [x] 37.2 Verify finish_reason detection works

  - [x] 37.3 Verify no false positives from removed pattern matching

  - [x] 37.4 Update COMPLETION_SUMMARY.md with improvements

  - _Requirements: All_

### Key Changes Summary

**Removed (Unreliable)**:
- Regex pattern matching against model output
- COMPLETION_PATTERNS list
- _contains_completion_pattern() method
- response_text parameter

**Added (Reliable)**:
- `attempt_completion` tool name (Cline, Roo-Code)
- FINISH_REASONS set (stop, tool_calls, length, end_turn)
- finish_reason parameter
- metadata parameter
- _is_finish_reason() method
- _extract_finish_reason() method
- _extract_metadata() method

**Benefits**:
- More reliable detection based on actual agent behavior
- No false positives from ambiguous text patterns
- Works with streaming responses (finish_reason)
- Works with explicit completion tools (attempt_completion)
- Based on real agent source code analysis, not speculation
