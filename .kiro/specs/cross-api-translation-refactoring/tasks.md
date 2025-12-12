# Implementation Plan

## Safety Practices

This refactoring follows incremental development practices to prevent codebase destabilization:

1. **Incremental Extraction**: Each utility/translator is extracted and tested independently before moving to the next
2. **Parallel Implementation**: New code is added alongside existing code, not replacing it until verified
3. **Backward Compatibility Layer**: Original static methods remain functional throughout, delegating to new implementations
4. **Frequent Checkpoints**: Test suite runs after each sub-phase to catch regressions early
5. **Rollback Strategy**: Each phase can be reverted independently if issues arise
6. **Feature Flag Pattern**: New translators can be enabled/disabled via registry without code changes
7. **TDD / Characterization First**: Add/extend tests that lock current behavior before moving code; treat tests as the refactor contract
8. **Green Gate Policy**: Do not proceed to the next subtask unless targeted tests and the full `pytest` run are green
9. **Mechanical Moves First**: Prefer copy/move without logic changes; refactor for structure only after equivalence is proven
10. **No Mass Formatting**: Avoid sweeping reformatting or unrelated cleanups that increase diff size and risk
11. **Static Checks on Touched Files**: Run `ruff`, `black`, and `mypy` for changed files after each subtask that edits Python code
12. **Revert-Friendly Checkpoints**: Keep changes small and checkpoint frequently (e.g., separate PRs/commits per phase)
13. **Baseline First**: Start from green (`./.venv/Scripts/python.exe -m pytest`) before any refactor steps

---

- [ ] 1. Extract shared utility modules from Translation class (TDD)
  - [ ] 1.1 Create translation_utils directory structure
    - Create `src/core/domain/translation_utils/__init__.py`
    - Create directory for shared utility modules
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 8.2_

  - [ ] 1.2 Write tests for JSON utilities (characterize current behavior)
    - **Property 2: Shared Utility Output Validity**
    - **Validates: Requirements 2.1**
    - _Requirements: 2.1, 7.4_

  - [ ] 1.3 Extract JSON utilities to json_utils.py
    - Extract `_is_json_serializable`, `_sanitize_dict_for_json`, `_sanitize_list_for_json` from Translation class
    - Create `src/core/domain/translation_utils/json_utils.py`
    - Update imports in Translation class to use new module
    - _Requirements: 2.1, 8.2_

  - [ ] 1.4 Phase gate: run tests after JSON utility extraction
    - Run `./.venv/Scripts/python.exe -m pytest -k "sanitize or json_utils or translation"`
    - Run `./.venv/Scripts/python.exe -m pytest`
    - _Requirements: 7.5_

  - [ ] 1.5 Write tests for tool utilities (characterize current behavior)
    - **Property 2: Shared Utility Output Validity**
    - **Validates: Requirements 2.2**
    - _Requirements: 2.2, 7.4_

  - [ ] 1.6 Extract tool utilities to tool_utils.py
    - Extract `_normalize_tool_arguments`, `_process_gemini_function_call` from Translation class
    - Create `src/core/domain/translation_utils/tool_utils.py`
    - Update imports in Translation class
    - _Requirements: 2.2, 8.2_

  - [ ] 1.7 Phase gate: run tests after tool utility extraction
    - Run `./.venv/Scripts/python.exe -m pytest -k "tool_utils or tool_call or translation"`
    - Run `./.venv/Scripts/python.exe -m pytest`
    - _Requirements: 7.5_

  - [ ] 1.8 Write tests for media utilities (characterize current behavior)
    - **Property 2: Shared Utility Output Validity**
    - **Validates: Requirements 2.4**
    - _Requirements: 2.4, 7.4_

  - [ ] 1.9 Extract media utilities to media_utils.py
    - Extract `_detect_image_mime_type`, `_process_gemini_image_part` from Translation class
    - Create `src/core/domain/translation_utils/media_utils.py`
    - Update imports in Translation class
    - _Requirements: 2.4, 8.2_

  - [ ] 1.10 Phase gate: run tests after media utility extraction
    - Run `./.venv/Scripts/python.exe -m pytest -k "media or multimodal or translation"`
    - Run `./.venv/Scripts/python.exe -m pytest`
    - _Requirements: 7.5_

  - [ ] 1.11 Write tests for content utilities (characterize current behavior)
    - **Property 2: Shared Utility Output Validity**
    - **Validates: Requirements 2.5**
    - _Requirements: 2.5, 7.4_

  - [ ] 1.12 Extract content utilities to content_utils.py
    - Extract `_safe_string`, `_coerce_reasoning_text`, `_collect_reasoning_lines` from Translation class
    - Create `src/core/domain/translation_utils/content_utils.py`
    - Update imports in Translation class
    - _Requirements: 2.5, 8.2_

  - [ ] 1.13 Phase gate: run tests after content utility extraction
    - Run `./.venv/Scripts/python.exe -m pytest -k "reasoning or content_utils or translation"`
    - Run `./.venv/Scripts/python.exe -m pytest`
    - _Requirements: 7.5_

  - [ ] 1.14 Write tests for usage utilities (characterize current behavior)
    - **Property 7: Usage Metadata Normalization Consistency**
    - **Validates: Requirements 2.3**
    - _Requirements: 2.3, 7.4_

  - [ ] 1.15 Extract usage utilities to usage_utils.py
    - Extract `_normalize_usage_metadata` from Translation class
    - Create `src/core/domain/translation_utils/usage_utils.py`
    - Update imports in Translation class
    - _Requirements: 2.3, 8.2_

  - [ ] 1.16 Phase gate: run tests after usage utility extraction
    - Run `./.venv/Scripts/python.exe -m pytest -k "usage or usage_utils or translation"`
    - Run `./.venv/Scripts/python.exe -m pytest`
    - _Requirements: 7.5_

  - [ ] 1.17 Final gate: run full test suite after all utility extraction
    - Run `./.venv/Scripts/python.exe -m pytest` to verify no regressions
    - All existing tests must pass before proceeding
    - _Requirements: 7.5_

- [ ] 2. Checkpoint - Ensure all tests pass
  - Run `./.venv/Scripts/python.exe -m pytest`
  - Do not proceed unless green
  - _Requirements: 7.5_

- [ ] 3. Create translator infrastructure
  - [ ] 3.1 Write tests for TranslatorRegistry routing and alias support (TDD)
    - **Property 5: Format-Based Routing Correctness**
    - Include coverage for format aliases (e.g., `openai-responses` → Responses translator)
    - _Requirements: 4.3, 4.4_

  - [ ] 3.2 Create TranslatorProtocol interface
    - Create `src/core/interfaces/translator_protocol.py`
    - Define TranslatorProtocol with to_domain_request, from_domain_request, to_domain_response, from_domain_response
    - Define StreamingTranslatorProtocol with to_domain_stream_chunk, from_domain_stream_chunk
    - _Requirements: 4.1, 4.2, 8.3_

  - [ ] 3.3 Create BaseFormatTranslator abstract base class
    - Create `src/core/domain/translators/__init__.py`
    - Create `src/core/domain/translators/base.py`
    - Implement BaseFormatTranslator ABC with abstract methods
    - Implement StreamingTranslatorMixin
    - _Requirements: 4.1, 4.2, 8.1_

  - [ ] 3.4 Create TranslatorRegistry
    - Create `src/core/domain/translators/registry.py`
    - Implement register, register_factory, get, has methods
    - Support lazy translator creation via factories
    - Ensure format alias support (e.g., `openai-responses` → Responses translator)
    - _Requirements: 3.1, 3.2, 4.3, 4.4, 8.1_

  - [ ] 3.5 Run full test suite after infrastructure creation
    - Run `./.venv/Scripts/python.exe -m pytest` to verify no regressions
    - New infrastructure must not break existing functionality
    - _Requirements: 7.5_

- [ ] 4. Checkpoint - Ensure all tests pass
  - Run `./.venv/Scripts/python.exe -m pytest`
  - Do not proceed unless green
  - _Requirements: 7.5_

- [ ] 5. Implement OpenAI translator (TDD)
  - [ ] 5.1 Write property/unit tests for OpenAI translator backward compatibility
    - **Property 3: Backward Compatibility Equivalence**
    - **Validates: Requirements 5.1, 5.2**
    - _Requirements: 5.1, 5.2, 7.1, 7.2, 7.3_

  - [ ] 5.2 Write property/unit tests for OpenAI translator correctness
    - **Property 1: Translator Module Existence and Correctness**
    - **Validates: Requirements 1.1**
    - _Requirements: 1.1, 7.1, 7.2, 7.3_

  - [ ] 5.3 Create OpenAITranslator class
    - Create `src/core/domain/translators/openai_translator.py`
    - Extract `openai_to_domain_request` logic from Translation class
    - Extract `openai_to_domain_response` logic from Translation class
    - Extract `from_domain_to_openai_request` logic from Translation class
    - Implement StreamingTranslatorMixin methods
    - _Requirements: 1.1, 6.1, 6.2, 6.3_

  - [ ] 5.4 Run targeted tests after OpenAI translator
    - Run `./.venv/Scripts/python.exe -m pytest -k "openai or translation"`
    - _Requirements: 7.5_

  - [ ] 5.5 Phase gate: run full test suite after OpenAI translator
    - Run `./.venv/Scripts/python.exe -m pytest`
    - _Requirements: 7.5_

- [ ] 6. Implement Anthropic translator (TDD)
  - [ ] 6.1 Write property/unit tests for Anthropic translator backward compatibility
    - **Property 3: Backward Compatibility Equivalence**
    - **Validates: Requirements 5.1, 5.2**
    - _Requirements: 5.1, 5.2, 7.1, 7.2, 7.3_

  - [ ] 6.2 Write property/unit tests for Anthropic translator correctness
    - **Property 1: Translator Module Existence and Correctness**
    - **Validates: Requirements 1.2**
    - _Requirements: 1.2, 7.1, 7.2, 7.3_

  - [ ] 6.3 Create AnthropicTranslator class
    - Create `src/core/domain/translators/anthropic_translator.py`
    - Extract `anthropic_to_domain_request` logic from Translation class
    - Extract `anthropic_to_domain_response` logic from Translation class
    - Extract `from_domain_to_anthropic_request` logic from Translation class
    - Extract `anthropic_to_domain_stream_chunk` logic from Translation class
    - Implement StreamingTranslatorMixin methods
    - _Requirements: 1.2, 6.1, 6.2, 6.3_

  - [ ] 6.4 Run targeted tests after Anthropic translator
    - Run `./.venv/Scripts/python.exe -m pytest -k "anthropic or translation"`
    - _Requirements: 7.5_

  - [ ] 6.5 Phase gate: run full test suite after Anthropic translator
    - Run `./.venv/Scripts/python.exe -m pytest`
    - _Requirements: 7.5_

- [ ] 7. Checkpoint - Ensure all tests pass
  - Run `./.venv/Scripts/python.exe -m pytest`
  - Do not proceed unless green
  - _Requirements: 7.5_

- [ ] 8. Implement Gemini translator (TDD)
  - [ ] 8.1 Write property/unit tests for Gemini translator backward compatibility
    - **Property 3: Backward Compatibility Equivalence**
    - **Validates: Requirements 5.1, 5.2**
    - _Requirements: 5.1, 5.2, 7.1, 7.2, 7.3_

  - [ ] 8.2 Write property/unit tests for Gemini translator correctness
    - **Property 1: Translator Module Existence and Correctness**
    - **Validates: Requirements 1.3**
    - _Requirements: 1.3, 7.1, 7.2, 7.3_

  - [ ] 8.3 Create GeminiTranslator class
    - Create `src/core/domain/translators/gemini_translator.py`
    - Extract `gemini_to_domain_request` logic from Translation class
    - Extract `gemini_to_domain_response` logic from Translation class
    - Extract `from_domain_to_gemini_request` logic from Translation class
    - Extract `gemini_to_domain_stream_chunk` logic from Translation class
    - Implement StreamingTranslatorMixin methods
    - _Requirements: 1.3, 6.1, 6.2, 6.3_

  - [ ] 8.4 Run targeted tests after Gemini translator
    - Run `./.venv/Scripts/python.exe -m pytest -k "gemini or translation"`
    - _Requirements: 7.5_

  - [ ] 8.5 Phase gate: run full test suite after Gemini translator
    - Run `./.venv/Scripts/python.exe -m pytest`
    - _Requirements: 7.5_

- [ ] 9. Implement Responses API translator (TDD)
  - [ ] 9.1 Write property/unit tests for Responses translator backward compatibility
    - **Property 3: Backward Compatibility Equivalence**
    - Include coverage for `openai-responses` alias routing
    - **Validates: Requirements 5.1, 5.2**
    - _Requirements: 5.1, 5.2, 7.1, 7.2, 7.3_

  - [ ] 9.2 Write property/unit tests for Responses translator correctness
    - **Property 1: Translator Module Existence and Correctness**
    - **Validates: Requirements 1.4**
    - _Requirements: 1.4, 7.1, 7.2, 7.3_

  - [ ] 9.3 Create ResponsesTranslator class
    - Create `src/core/domain/translators/responses_translator.py`
    - Extract `responses_to_domain_request` logic from Translation class
    - Extract `responses_to_domain_response` logic from Translation class
    - Extract `from_domain_to_responses_request` logic from Translation class
    - Extract `from_domain_to_responses_response` logic from Translation class
    - Extract `responses_to_domain_stream_chunk` logic from Translation class
    - Implement StreamingTranslatorMixin methods
    - _Requirements: 1.4, 6.1, 6.2, 6.3_

  - [ ] 9.4 Run targeted tests after Responses translator
    - Run `./.venv/Scripts/python.exe -m pytest -k "responses or translation"`
    - _Requirements: 7.5_

  - [ ] 9.5 Phase gate: run full test suite after Responses translator
    - Run `./.venv/Scripts/python.exe -m pytest`
    - _Requirements: 7.5_

- [ ] 10. Implement Code Assist translator (TDD)
  - [ ] 10.1 Write property/unit tests for Code Assist translator backward compatibility
    - **Property 3: Backward Compatibility Equivalence**
    - **Validates: Requirements 5.1**
    - _Requirements: 5.1, 7.1, 7.2, 7.3_

  - [ ] 10.2 Write property/unit tests for Code Assist translator correctness
    - **Property 1: Translator Module Existence and Correctness**
    - **Validates: Requirements 1.5**
    - _Requirements: 1.5, 7.1, 7.2, 7.3_

  - [ ] 10.3 Create CodeAssistTranslator class
    - Create `src/core/domain/translators/code_assist_translator.py`
    - Extract `code_assist_to_domain_request` logic from Translation class
    - Extract `code_assist_to_domain_response` logic from Translation class
    - Extract `code_assist_to_domain_stream_chunk` logic from Translation class
    - Implement StreamingTranslatorMixin methods
    - _Requirements: 1.5, 6.1, 6.2, 6.3_

  - [ ] 10.4 Run targeted tests after Code Assist translator
    - Run `./.venv/Scripts/python.exe -m pytest -k "code_assist or translation"`
    - _Requirements: 7.5_

  - [ ] 10.5 Phase gate: run full test suite after Code Assist translator
    - Run `./.venv/Scripts/python.exe -m pytest`
    - _Requirements: 7.5_

- [ ] 11. Checkpoint - Ensure all tests pass
  - Run `./.venv/Scripts/python.exe -m pytest`
  - Do not proceed unless green
  - _Requirements: 7.5_

- [ ] 12. Implement additional translators (TDD)
  - [ ] 12.1 Write property/unit tests for OpenRouter translator
    - **Property 1: Translator Module Existence and Correctness**
    - **Validates: Requirements 1.6**
    - _Requirements: 1.6, 5.1, 7.1_

  - [ ] 12.2 Create OpenRouterTranslator class
    - Create `src/core/domain/translators/openrouter_translator.py`
    - Extract `openrouter_to_domain_request` logic from Translation class
    - _Requirements: 1.6, 5.1_

  - [ ] 12.3 Run targeted tests after OpenRouter translator
    - Run `./.venv/Scripts/python.exe -m pytest -k "openrouter or translation"`
    - _Requirements: 7.5_

  - [ ] 12.4 Phase gate: run full test suite after OpenRouter translator
    - Run `./.venv/Scripts/python.exe -m pytest`
    - _Requirements: 7.5_

  - [ ] 12.5 Write property/unit tests for Raw Text translator
    - **Property 1: Translator Module Existence and Correctness**
    - **Validates: Requirements 1.7**
    - _Requirements: 1.7, 5.1, 7.1, 7.2, 7.3_

  - [ ] 12.6 Create RawTextTranslator class
    - Create `src/core/domain/translators/raw_text_translator.py`
    - Extract `raw_text_to_domain_request`, `raw_text_to_domain_response`, `raw_text_to_domain_stream_chunk` logic
    - _Requirements: 1.7, 5.1, 6.1, 6.2, 6.3_

  - [ ] 12.7 Run targeted tests after Raw Text translator
    - Run `./.venv/Scripts/python.exe -m pytest -k "raw_text or translation"`
    - _Requirements: 7.5_

  - [ ] 12.8 Phase gate: run full test suite after Raw Text translator
    - Run `./.venv/Scripts/python.exe -m pytest`
    - _Requirements: 7.5_

  - [ ] 12.9 Final gate: run full test suite after all translators implemented
    - Run `./.venv/Scripts/python.exe -m pytest` to verify all tests pass
    - All translators must work correctly before proceeding to facade refactoring
    - _Requirements: 7.5_

- [ ] 13. Refactor Translation class to facade
  - [ ] 13.1 Write property/unit tests for Translation facade delegation (TDD)
    - **Property 5: Format-Based Routing Correctness**
    - **Validates: Requirements 9.1, 9.2, 9.3**
    - _Requirements: 9.1, 9.2, 9.3_

  - [ ] 13.2 Initialize TranslatorRegistry with all translators
    - Create initialization code that registers all translators
    - Support lazy loading via factories for performance
    - _Requirements: 3.1, 3.4_

  - [ ] 13.3 Update Translation static methods to delegate
    - Update `gemini_to_domain_request` to delegate to GeminiTranslator
    - Update `anthropic_to_domain_response` to delegate to AnthropicTranslator
    - Update `openai_to_domain_stream_chunk` to delegate to OpenAITranslator
    - Update all other methods to delegate to appropriate translators
    - _Requirements: 9.1, 9.2, 9.3_

  - [ ] 13.4 Remove extracted code from Translation class
    - Remove method implementations that are now in specialized translators
    - Keep only delegation logic and backward-compatible static methods
    - Verify Translation class is under 500 lines
    - _Requirements: 8.4, 9.4_

  - [ ] 13.5 Run full test suite after facade refactoring
    - Run `./.venv/Scripts/python.exe -m pytest` to verify all tests pass
    - Critical checkpoint: facade must maintain 100% backward compatibility
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 7.5_

- [ ] 14. Checkpoint - Ensure all tests pass
  - Run `./.venv/Scripts/python.exe -m pytest`
  - Do not proceed unless green
  - _Requirements: 7.5_

- [ ] 15. Refactor TranslationService
  - [ ] 15.1 Write property/unit tests for TranslationService routing (TDD)
    - **Property 5: Format-Based Routing Correctness**
    - **Validates: Requirements 4.3**
    - _Requirements: 3.3, 4.3_

  - [ ] 15.2 Update TranslationService to use TranslatorRegistry
    - Inject TranslatorRegistry via constructor
    - Update converter mappings to use registry
    - Remove duplicated delegation code
    - _Requirements: 3.1, 3.2_

  - [ ] 15.3 Simplify TranslationService methods
    - Reduce code duplication with Translation class
    - Use registry for all translator lookups
    - _Requirements: 8.4_

  - [ ] 15.4 Run full test suite after TranslationService refactoring
    - Run `./.venv/Scripts/python.exe -m pytest` to verify all tests pass
    - Service layer must maintain identical behavior
    - _Requirements: 5.3, 5.4, 7.5_

- [ ] 16. Checkpoint - Ensure all tests pass
  - Run `./.venv/Scripts/python.exe -m pytest`
  - Do not proceed unless green
  - _Requirements: 7.5_

- [ ] 17. Edge case handling verification
  - [ ] 17.1 Write property/unit tests for edge case handling preservation (TDD)
    - **Property 6: Edge Case Handling Preservation**
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5**
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [ ] 17.2 Verify malformed JSON handling
    - Test that malformed JSON in tool arguments is handled gracefully
    - Compare behavior with original implementation
    - _Requirements: 10.1_

  - [ ] 17.3 Verify multimodal content handling
    - Test image content conversion across all translators
    - Compare behavior with original implementation
    - _Requirements: 10.2_

  - [ ] 17.4 Verify reasoning/thinking content handling
    - Test extended thinking content preservation
    - Test thought signature preservation
    - Compare behavior with original implementation
    - _Requirements: 10.3, 10.4_

  - [ ] 17.5 Phase gate: run full test suite after edge case verification
    - Run `./.venv/Scripts/python.exe -m pytest`
    - _Requirements: 7.5_

- [ ] 18. Backward compatibility verification
  - [ ] 18.1 Write property/unit tests for backward compatibility (TDD)
    - **Property 3: Backward Compatibility Equivalence**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5**
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ] 18.2 Verify anthropic_converters.py exports
    - Ensure all existing exports are maintained
    - Update imports if necessary to use new modules
    - _Requirements: 5.5_

  - [ ] 18.3 Verify gemini_converters.py exports
    - Ensure all existing exports are maintained
    - Update imports if necessary to use new modules
    - _Requirements: 5.5_

  - [ ] 18.4 Phase gate: run full test suite after compatibility verification
    - Run `./.venv/Scripts/python.exe -m pytest`
    - _Requirements: 7.5_

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
    - Confirm `src/core/domain/translation.py` is ≤ 500 lines
    - Confirm all new modules are under 500 lines
    - _Requirements: 8.4, 9.4_

  - [ ] 19.4 Phase gate: run full test suite after cleanup
    - Run `./.venv/Scripts/python.exe -m pytest`
    - _Requirements: 7.5_

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
  - Run `./.venv/Scripts/python.exe -m pytest`
  - Run `./.venv/Scripts/python.exe -m pytest -m integration`
  - Do not consider the refactor complete unless green
  - _Requirements: 7.5_
