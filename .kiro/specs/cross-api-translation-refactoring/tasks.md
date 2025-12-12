# Implementation Plan

## Safety Practices

This refactoring follows incremental development practices to prevent codebase destabilization:

1. **Incremental Extraction**: Each utility/translator is extracted and tested independently before moving to the next
2. **Parallel Implementation**: New code is added alongside existing code, not replacing it until verified
3. **Backward Compatibility Layer**: Original static methods remain functional throughout, delegating to new implementations
4. **Frequent Checkpoints**: Test suite runs after each sub-phase to catch regressions early
5. **Rollback Strategy**: Each phase can be reverted independently if issues arise
6. **Feature Flag Pattern**: New translators can be enabled/disabled via registry without code changes

---

- [ ] 1. Extract shared utility modules from Translation class
  - [ ] 1.1 Create translation_utils directory structure
    - Create `src/core/domain/translation_utils/__init__.py`
    - Create directory for shared utility modules
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 8.2_

  - [ ] 1.2 Extract JSON utilities to json_utils.py
    - Extract `_is_json_serializable`, `_sanitize_dict_for_json`, `_sanitize_list_for_json` from Translation class
    - Create `src/core/domain/translation_utils/json_utils.py`
    - Update imports in Translation class to use new module
    - _Requirements: 2.1_

  - [ ] 1.3 Write property test for JSON utilities
    - **Property 2: Shared Utility Output Validity**
    - **Validates: Requirements 2.1**

  - [ ] 1.4 Extract tool utilities to tool_utils.py
    - Extract `_normalize_tool_arguments`, `_process_gemini_function_call` from Translation class
    - Create `src/core/domain/translation_utils/tool_utils.py`
    - Update imports in Translation class
    - _Requirements: 2.2_

  - [ ] 1.5 Write property test for tool utilities
    - **Property 2: Shared Utility Output Validity**
    - **Validates: Requirements 2.2**

  - [ ] 1.6 Extract media utilities to media_utils.py
    - Extract `_detect_image_mime_type`, `_process_gemini_image_part` from Translation class
    - Create `src/core/domain/translation_utils/media_utils.py`
    - Update imports in Translation class
    - _Requirements: 2.4_

  - [ ] 1.7 Write property test for media utilities
    - **Property 2: Shared Utility Output Validity**
    - **Validates: Requirements 2.4**

  - [ ] 1.8 Extract content utilities to content_utils.py
    - Extract `_safe_string`, `_coerce_reasoning_text`, `_collect_reasoning_lines` from Translation class
    - Create `src/core/domain/translation_utils/content_utils.py`
    - Update imports in Translation class
    - _Requirements: 2.5_

  - [ ] 1.9 Write property test for content utilities
    - **Property 2: Shared Utility Output Validity**
    - **Validates: Requirements 2.5**

  - [ ] 1.10 Extract usage utilities to usage_utils.py
    - Extract `_normalize_usage_metadata` from Translation class
    - Create `src/core/domain/translation_utils/usage_utils.py`
    - Update imports in Translation class
    - _Requirements: 2.3_

  - [ ] 1.11 Write property test for usage utilities
    - **Property 7: Usage Metadata Normalization Consistency**
    - **Validates: Requirements 2.3**

  - [ ] 1.12 Run full test suite after utility extraction
    - Run `./.venv/Scripts/python.exe -m pytest` to verify no regressions
    - All existing tests must pass before proceeding
    - _Requirements: 7.5_

- [ ] 2. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 3. Create translator infrastructure
  - [ ] 3.1 Create TranslatorProtocol interface
    - Create `src/core/interfaces/translator_protocol.py`
    - Define TranslatorProtocol with to_domain_request, from_domain_request, to_domain_response, from_domain_response
    - Define StreamingTranslatorProtocol with to_domain_stream_chunk, from_domain_stream_chunk
    - _Requirements: 4.1, 4.2_

  - [ ] 3.2 Create BaseTranslator abstract base class
    - Create `src/core/domain/translators/__init__.py`
    - Create `src/core/domain/translators/base.py`
    - Implement BaseTranslator ABC with abstract methods
    - Implement StreamingTranslatorMixin
    - _Requirements: 4.1, 4.2_

  - [ ] 3.3 Create TranslatorRegistry
    - Create `src/core/domain/translators/registry.py`
    - Implement register, register_factory, get, has methods
    - Support lazy translator creation via factories
    - _Requirements: 3.1, 3.2, 4.3_

  - [ ] 3.4 Write property test for TranslatorRegistry
    - **Property 5: Format-Based Routing Correctness**
    - **Validates: Requirements 4.3**

  - [ ] 3.5 Run full test suite after infrastructure creation
    - Run `./.venv/Scripts/python.exe -m pytest` to verify no regressions
    - New infrastructure must not break existing functionality
    - _Requirements: 7.5_

- [ ] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Implement OpenAI translator
  - [ ] 5.1 Create OpenAITranslator class
    - Create `src/core/domain/translators/openai_translator.py`
    - Extract `openai_to_domain_request` logic from Translation class
    - Extract `openai_to_domain_response` logic from Translation class
    - Extract `from_domain_to_openai_request` logic from Translation class
    - Implement StreamingTranslatorMixin methods
    - _Requirements: 1.1, 6.1, 6.2_

  - [ ] 5.2 Write property test for OpenAI translator backward compatibility
    - **Property 3: Backward Compatibility Equivalence**
    - **Validates: Requirements 5.1, 5.3**

  - [ ] 5.3 Write property test for OpenAI translator correctness
    - **Property 1: Translator Module Existence and Correctness**
    - **Validates: Requirements 1.1**

  - [ ] 5.4 Run test suite after OpenAI translator
    - Run `./.venv/Scripts/python.exe -m pytest -k "openai or translation"` to verify OpenAI-related tests pass
    - Verify new translator produces identical output to original
    - _Requirements: 5.1, 7.5_

- [ ] 6. Implement Anthropic translator
  - [ ] 6.1 Create AnthropicTranslator class
    - Create `src/core/domain/translators/anthropic_translator.py`
    - Extract `anthropic_to_domain_request` logic from Translation class
    - Extract `anthropic_to_domain_response` logic from Translation class
    - Extract `from_domain_to_anthropic_request` logic from Translation class
    - Extract `anthropic_to_domain_stream_chunk` logic from Translation class
    - Implement StreamingTranslatorMixin methods
    - _Requirements: 1.2, 6.1, 6.2_

  - [ ] 6.2 Write property test for Anthropic translator backward compatibility
    - **Property 3: Backward Compatibility Equivalence**
    - **Validates: Requirements 5.2**

  - [ ] 6.3 Write property test for Anthropic translator correctness
    - **Property 1: Translator Module Existence and Correctness**
    - **Validates: Requirements 1.2**

  - [ ] 6.4 Run test suite after Anthropic translator
    - Run `./.venv/Scripts/python.exe -m pytest -k "anthropic or translation"` to verify Anthropic-related tests pass
    - Verify new translator produces identical output to original
    - _Requirements: 5.2, 7.5_

- [ ] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Implement Gemini translator
  - [ ] 8.1 Create GeminiTranslator class
    - Create `src/core/domain/translators/gemini_translator.py`
    - Extract `gemini_to_domain_request` logic from Translation class
    - Extract `gemini_to_domain_response` logic from Translation class
    - Extract `from_domain_to_gemini_request` logic from Translation class
    - Extract `gemini_to_domain_stream_chunk` logic from Translation class
    - Implement StreamingTranslatorMixin methods
    - _Requirements: 1.3, 6.1, 6.2_

  - [ ] 8.2 Write property test for Gemini translator backward compatibility
    - **Property 3: Backward Compatibility Equivalence**
    - **Validates: Requirements 5.1**

  - [ ] 8.3 Write property test for Gemini translator correctness
    - **Property 1: Translator Module Existence and Correctness**
    - **Validates: Requirements 1.3**

  - [ ] 8.4 Run test suite after Gemini translator
    - Run `./.venv/Scripts/python.exe -m pytest -k "gemini or translation"` to verify Gemini-related tests pass
    - Verify new translator produces identical output to original
    - _Requirements: 5.1, 7.5_

- [ ] 9. Implement Responses API translator
  - [ ] 9.1 Create ResponsesTranslator class
    - Create `src/core/domain/translators/responses_translator.py`
    - Extract `responses_to_domain_request` logic from Translation class
    - Extract `responses_to_domain_response` logic from Translation class
    - Extract `from_domain_to_responses_request` logic from Translation class
    - Extract `from_domain_to_responses_response` logic from Translation class
    - Extract `responses_to_domain_stream_chunk` logic from Translation class
    - Implement StreamingTranslatorMixin methods
    - _Requirements: 1.4, 6.1, 6.2_

  - [ ] 9.2 Write property test for Responses translator backward compatibility
    - **Property 3: Backward Compatibility Equivalence**
    - **Validates: Requirements 5.3, 5.4**

  - [ ] 9.3 Write property test for Responses translator correctness
    - **Property 1: Translator Module Existence and Correctness**
    - **Validates: Requirements 1.4**

  - [ ] 9.4 Run test suite after Responses translator
    - Run `./.venv/Scripts/python.exe -m pytest -k "responses or translation"` to verify Responses-related tests pass
    - Verify new translator produces identical output to original
    - _Requirements: 5.3, 5.4, 7.5_

- [ ] 10. Implement Code Assist translator
  - [ ] 10.1 Create CodeAssistTranslator class
    - Create `src/core/domain/translators/code_assist_translator.py`
    - Extract `code_assist_to_domain_request` logic from Translation class
    - Extract `code_assist_to_domain_response` logic from Translation class
    - Extract `code_assist_to_domain_stream_chunk` logic from Translation class
    - Implement StreamingTranslatorMixin methods
    - _Requirements: 1.5, 6.1, 6.2_

  - [ ] 10.2 Write property test for Code Assist translator correctness
    - **Property 1: Translator Module Existence and Correctness**
    - **Validates: Requirements 1.5**

  - [ ] 10.3 Run test suite after Code Assist translator
    - Run `./.venv/Scripts/python.exe -m pytest -k "code_assist or translation"` to verify Code Assist-related tests pass
    - Verify new translator produces identical output to original
    - _Requirements: 7.5_

- [ ] 11. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. Implement additional translators
  - [ ] 12.1 Create OpenRouterTranslator class
    - Create `src/core/domain/translators/openrouter_translator.py`
    - Extract `openrouter_to_domain_request` logic from Translation class
    - _Requirements: 1.1_

  - [ ] 12.2 Create RawTextTranslator class
    - Create `src/core/domain/translators/raw_text_translator.py`
    - Extract `raw_text_to_domain_request`, `raw_text_to_domain_response`, `raw_text_to_domain_stream_chunk` logic
    - _Requirements: 1.1_

  - [ ] 12.3 Run full test suite after all translators implemented
    - Run `./.venv/Scripts/python.exe -m pytest` to verify all tests pass
    - All translators must work correctly before proceeding to facade refactoring
    - _Requirements: 7.5_

- [ ] 13. Refactor Translation class to facade
  - [ ] 13.1 Initialize TranslatorRegistry with all translators
    - Create initialization code that registers all translators
    - Support lazy loading via factories for performance
    - _Requirements: 3.1, 3.4_

  - [ ] 13.2 Update Translation static methods to delegate
    - Update `gemini_to_domain_request` to delegate to GeminiTranslator
    - Update `anthropic_to_domain_response` to delegate to AnthropicTranslator
    - Update `openai_to_domain_stream_chunk` to delegate to OpenAITranslator
    - Update all other methods to delegate to appropriate translators
    - _Requirements: 9.1, 9.2, 9.3_

  - [ ] 13.3 Remove extracted code from Translation class
    - Remove method implementations that are now in specialized translators
    - Keep only delegation logic and backward-compatible static methods
    - Verify Translation class is under 500 lines
    - _Requirements: 8.4, 9.4_

  - [ ] 13.4 Write property test for Translation facade delegation
    - **Property 5: Format-Based Routing Correctness**
    - **Validates: Requirements 9.1, 9.2, 9.3**

  - [ ] 13.5 Run full test suite after facade refactoring
    - Run `./.venv/Scripts/python.exe -m pytest` to verify all tests pass
    - Critical checkpoint: facade must maintain 100% backward compatibility
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 7.5_

- [ ] 14. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 15. Refactor TranslationService
  - [ ] 15.1 Update TranslationService to use TranslatorRegistry
    - Inject TranslatorRegistry via constructor
    - Update converter mappings to use registry
    - Remove duplicated delegation code
    - _Requirements: 3.1, 3.2_

  - [ ] 15.2 Simplify TranslationService methods
    - Reduce code duplication with Translation class
    - Use registry for all translator lookups
    - _Requirements: 8.4_

  - [ ] 15.3 Write property test for TranslationService routing
    - **Property 5: Format-Based Routing Correctness**
    - **Validates: Requirements 4.3**

  - [ ] 15.4 Run full test suite after TranslationService refactoring
    - Run `./.venv/Scripts/python.exe -m pytest` to verify all tests pass
    - Service layer must maintain identical behavior
    - _Requirements: 5.3, 5.4, 7.5_

- [ ] 16. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 17. Edge case handling verification
  - [ ] 17.1 Verify malformed JSON handling
    - Test that malformed JSON in tool arguments is handled gracefully
    - Compare behavior with original implementation
    - _Requirements: 10.1_

  - [ ] 17.2 Write property test for edge case handling
    - **Property 6: Edge Case Handling Preservation**
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5**

  - [ ] 17.3 Verify multimodal content handling
    - Test image content conversion across all translators
    - Compare behavior with original implementation
    - _Requirements: 10.2_

  - [ ] 17.4 Verify reasoning/thinking content handling
    - Test extended thinking content preservation
    - Test thought signature preservation
    - Compare behavior with original implementation
    - _Requirements: 10.3, 10.4_

- [ ] 18. Backward compatibility verification
  - [ ] 18.1 Verify anthropic_converters.py exports
    - Ensure all existing exports are maintained
    - Update imports if necessary to use new modules
    - _Requirements: 5.5_

  - [ ] 18.2 Verify gemini_converters.py exports
    - Ensure all existing exports are maintained
    - Update imports if necessary to use new modules
    - _Requirements: 5.5_

  - [ ] 18.3 Write property test for backward compatibility
    - **Property 3: Backward Compatibility Equivalence**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5**

- [ ] 19. Cleanup and documentation
  - [ ] 19.1 Remove dead code
    - Remove any unused methods from Translation class
    - Remove any unused imports
    - _Requirements: 8.4_

  - [ ] 19.2 Update module docstrings
    - Add docstrings to all new modules
    - Update existing docstrings to reflect new architecture
    - _Requirements: 8.1, 8.2, 8.3_

  - [ ] 19.3 Verify line count reduction
    - Confirm Translation class is reduced by at least 80%
    - Confirm all new modules are under 500 lines
    - _Requirements: 8.4, 9.4_

- [ ] 20. Final verification and regression testing
  - [ ] 20.1 Run full test suite
    - Run `./.venv/Scripts/python.exe -m pytest` to verify all tests pass
    - Zero test failures required
    - _Requirements: 7.5_

  - [ ] 20.2 Run integration tests
    - Run `./.venv/Scripts/python.exe -m pytest -m integration` to verify integration tests pass
    - Verify end-to-end translation flows work correctly
    - _Requirements: 7.5_

  - [ ] 20.3 Verify no regressions in existing functionality
    - Compare test coverage before and after refactoring
    - Ensure no functionality was accidentally removed
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 7.5_

- [ ] 21. Final Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
