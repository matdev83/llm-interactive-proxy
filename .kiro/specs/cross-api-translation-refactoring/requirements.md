# Requirements Document

## Introduction

This document specifies the requirements for refactoring the Cross-API Translation service/middleware, which currently exhibits "God Object" anti-pattern characteristics. The primary target is the `Translation` class in `src/core/domain/translation.py` (4447 lines, 51 methods) and related components including `TranslationService` (993 lines), `anthropic_converters.py` (1052 lines), and `gemini_converters.py` (600+ lines).

The refactoring aims to decompose these monolithic components into a modular, layered architecture that respects SOLID principles, DRY principle, proper DI container usage, and appropriate OOP design patterns while maintaining full backward compatibility with existing public APIs.

## Glossary

- **Translation**: The main class responsible for converting requests/responses between different LLM API formats (OpenAI, Anthropic, Gemini, Code Assist, OpenRouter, Responses API)
- **TranslationService**: A service layer that orchestrates translation operations using the Translation class
- **Canonical Format**: The internal standardized format (CanonicalChatRequest, CanonicalChatResponse) used as an intermediate representation
- **Domain Model**: Pydantic models representing the internal data structures (ChatMessage, ToolCall, etc.)
- **Converter**: A component responsible for translating between a specific API format and the canonical format
- **God Object**: An anti-pattern where a single class knows too much or does too much
- **SRP**: Single Responsibility Principle - a class should have only one reason to change
- **OCP**: Open/Closed Principle - open for extension, closed for modification
- **DI**: Dependency Injection - a technique for achieving Inversion of Control

## Requirements

### Requirement 1

**User Story:** As a developer, I want the translation logic to be organized into separate, focused modules, so that I can understand, maintain, and test each API format's translation independently.

#### Acceptance Criteria

1. WHEN a developer needs to modify OpenAI translation logic THEN the Translation_System SHALL provide a dedicated OpenAI translator module that contains only OpenAI-specific conversion code
2. WHEN a developer needs to modify Anthropic translation logic THEN the Translation_System SHALL provide a dedicated Anthropic translator module that contains only Anthropic-specific conversion code
3. WHEN a developer needs to modify Gemini translation logic THEN the Translation_System SHALL provide a dedicated Gemini translator module that contains only Gemini-specific conversion code
4. WHEN a developer needs to modify Responses API translation logic THEN the Translation_System SHALL provide a dedicated Responses translator module that contains only Responses API-specific conversion code
5. WHEN a developer needs to modify Code Assist translation logic THEN the Translation_System SHALL provide a dedicated Code Assist translator module that contains only Code Assist-specific conversion code

### Requirement 2

**User Story:** As a developer, I want shared utility functions extracted into reusable modules, so that I can avoid code duplication and maintain consistency across translators.

#### Acceptance Criteria

1. WHEN multiple translators need JSON sanitization functionality THEN the Translation_System SHALL provide a shared JSON utilities module containing _sanitize_dict_for_json, _sanitize_list_for_json, and _is_json_serializable functions
2. WHEN multiple translators need tool argument normalization THEN the Translation_System SHALL provide a shared tool utilities module containing _normalize_tool_arguments and related functions
3. WHEN multiple translators need usage metadata normalization THEN the Translation_System SHALL provide a shared usage utilities module containing _normalize_usage_metadata function
4. WHEN multiple translators need image processing functionality THEN the Translation_System SHALL provide a shared media utilities module containing _detect_image_mime_type and _process_gemini_image_part functions
5. WHEN multiple translators need text content normalization THEN the Translation_System SHALL provide a shared content utilities module containing _safe_string and text coercion functions

### Requirement 3

**User Story:** As a developer, I want the translation system to use dependency injection, so that I can easily swap implementations and write unit tests with mocks.

#### Acceptance Criteria

1. WHEN the TranslationService is instantiated THEN the Translation_System SHALL accept translator implementations via constructor injection
2. WHEN a new API format translator is needed THEN the Translation_System SHALL allow registration of new translators without modifying existing code
3. WHEN unit testing a specific translator THEN the Translation_System SHALL allow injection of mock dependencies for isolated testing
4. WHEN the application starts THEN the Translation_System SHALL use the DI container to resolve translator dependencies

### Requirement 4

**User Story:** As a developer, I want each translator to implement a common interface, so that I can add new API format support without modifying existing code.

#### Acceptance Criteria

1. WHEN a new translator is created THEN the Translation_System SHALL require implementation of a BaseTranslator protocol defining to_domain_request, from_domain_request, to_domain_response, from_domain_response methods
2. WHEN a streaming translator is created THEN the Translation_System SHALL require implementation of a StreamingTranslator protocol defining to_domain_stream_chunk and from_domain_stream_chunk methods
3. WHEN the TranslationService receives a request THEN the Translation_System SHALL dispatch to the appropriate translator based on the source format
4. WHEN a translator is registered THEN the Translation_System SHALL validate that the translator implements the required protocol

### Requirement 5

**User Story:** As a developer, I want the existing public APIs to remain unchanged, so that no calling code breaks after the refactoring.

#### Acceptance Criteria

1. WHEN external code calls Translation.gemini_to_domain_request THEN the Translation_System SHALL return the same result as before refactoring
2. WHEN external code calls Translation.anthropic_to_domain_response THEN the Translation_System SHALL return the same result as before refactoring
3. WHEN external code calls TranslationService.to_domain_request THEN the Translation_System SHALL return the same result as before refactoring
4. WHEN external code calls TranslationService.from_domain_request THEN the Translation_System SHALL return the same result as before refactoring
5. WHEN external code imports from anthropic_converters or gemini_converters THEN the Translation_System SHALL maintain backward-compatible exports

### Requirement 6

**User Story:** As a developer, I want streaming translation logic separated from non-streaming logic, so that I can maintain and optimize each independently.

#### Acceptance Criteria

1. WHEN processing a streaming request THEN the Translation_System SHALL use dedicated streaming translator components
2. WHEN processing a non-streaming request THEN the Translation_System SHALL use dedicated non-streaming translator components
3. WHEN a translator handles both streaming and non-streaming THEN the Translation_System SHALL separate the logic into distinct methods or classes

### Requirement 7

**User Story:** As a developer, I want the refactored code to have comprehensive test coverage, so that I can verify correctness and prevent regressions.

#### Acceptance Criteria

1. WHEN a translator module is created THEN the Translation_System SHALL have unit tests covering request translation
2. WHEN a translator module is created THEN the Translation_System SHALL have unit tests covering response translation
3. WHEN a translator module is created THEN the Translation_System SHALL have unit tests covering stream chunk translation
4. WHEN shared utilities are created THEN the Translation_System SHALL have unit tests covering edge cases and error conditions
5. WHEN the refactoring is complete THEN the Translation_System SHALL pass all existing tests with zero regressions

### Requirement 8

**User Story:** As a developer, I want the code organized following clean architecture principles, so that the codebase is maintainable and extensible.

#### Acceptance Criteria

1. WHEN organizing translator code THEN the Translation_System SHALL place translator implementations in src/core/domain/translators/ directory
2. WHEN organizing shared utilities THEN the Translation_System SHALL place utility modules in src/core/domain/translation_utils/ directory
3. WHEN organizing interfaces THEN the Translation_System SHALL place protocol definitions in src/core/interfaces/ directory
4. WHEN a module has more than 500 lines THEN the Translation_System SHALL split it into smaller focused modules

### Requirement 9

**User Story:** As a developer, I want the Translation class to delegate to specialized translators, so that it becomes a thin facade rather than a God Object.

#### Acceptance Criteria

1. WHEN Translation.gemini_to_domain_request is called THEN the Translation_System SHALL delegate to GeminiTranslator.to_domain_request
2. WHEN Translation.anthropic_to_domain_response is called THEN the Translation_System SHALL delegate to AnthropicTranslator.to_domain_response
3. WHEN Translation.openai_to_domain_stream_chunk is called THEN the Translation_System SHALL delegate to OpenAITranslator.to_domain_stream_chunk
4. WHEN the Translation class is refactored THEN the Translation_System SHALL reduce its line count by at least 80%

### Requirement 10

**User Story:** As a developer, I want the refactoring to preserve all existing functionality including edge case handling, so that production behavior remains unchanged.

#### Acceptance Criteria

1. WHEN processing malformed JSON in tool arguments THEN the Translation_System SHALL handle the error gracefully as before
2. WHEN processing multimodal content with images THEN the Translation_System SHALL convert formats correctly as before
3. WHEN processing extended thinking/reasoning content THEN the Translation_System SHALL preserve reasoning data as before
4. WHEN processing tool calls with thought signatures THEN the Translation_System SHALL preserve signatures as before
5. WHEN processing empty or null content THEN the Translation_System SHALL handle edge cases as before
