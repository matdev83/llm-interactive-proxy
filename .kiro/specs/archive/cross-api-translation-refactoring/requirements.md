# Requirements Document

## Introduction

This document specifies the requirements for refactoring the Cross-API Translation service/middleware, which currently exhibits "God Object" anti-pattern characteristics. The primary target is the `Translation` class in `src/core/domain/translation.py` (~4.4k lines, 51 methods) and related components including `TranslationService` in `src/core/services/translation_service.py` (~1k lines), plus the compatibility modules `src/anthropic_converters.py` (~1k lines) and `src/gemini_converters.py` (~650 lines).

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

1.1 WHEN a developer needs to modify OpenAI translation logic THEN the system SHALL provide a dedicated OpenAI translator module that contains only OpenAI-specific conversion code
1.2 WHEN a developer needs to modify Anthropic translation logic THEN the system SHALL provide a dedicated Anthropic translator module that contains only Anthropic-specific conversion code
1.3 WHEN a developer needs to modify Gemini translation logic THEN the system SHALL provide a dedicated Gemini translator module that contains only Gemini-specific conversion code
1.4 WHEN a developer needs to modify Responses API translation logic (format keys `responses` and `openai-responses`) THEN the system SHALL provide a dedicated Responses translator module that contains only Responses API-specific conversion code
1.5 WHEN a developer needs to modify Code Assist translation logic THEN the system SHALL provide a dedicated Code Assist translator module that contains only Code Assist-specific conversion code
1.6 WHEN a developer needs to modify OpenRouter translation logic THEN the system SHALL provide a dedicated OpenRouter translator module that contains only OpenRouter-specific conversion code
1.7 WHEN a developer needs to modify Raw Text translation logic THEN the system SHALL provide a dedicated Raw Text translator module that contains only Raw Text-specific conversion code

### Requirement 2

**User Story:** As a developer, I want shared utility functions extracted into reusable modules, so that I can avoid code duplication and maintain consistency across translators.

#### Acceptance Criteria

2.1 WHEN multiple translators need JSON sanitization functionality THEN the system SHALL provide a shared JSON utilities module containing `_sanitize_dict_for_json`, `_sanitize_list_for_json`, and `_is_json_serializable`
2.2 WHEN multiple translators need tool argument normalization THEN the system SHALL provide a shared tool utilities module containing `_normalize_tool_arguments` and related functions
2.3 WHEN multiple translators need usage metadata normalization THEN the system SHALL provide a shared usage utilities module containing `_normalize_usage_metadata`
2.4 WHEN multiple translators need image processing functionality THEN the system SHALL provide a shared media utilities module containing `_detect_image_mime_type` and `_process_gemini_image_part`
2.5 WHEN multiple translators need text content normalization THEN the system SHALL provide a shared content utilities module containing `_safe_string` and text coercion functions

### Requirement 3

**User Story:** As a developer, I want the translation system to use dependency injection, so that I can easily swap implementations and write unit tests with mocks.

#### Acceptance Criteria

3.1 WHEN the application starts THEN the system SHALL register translator components and the translator registry in the DI container
3.2 WHEN the TranslationService is instantiated THEN the system SHALL obtain translator dependencies via DI (factory or injected registry), not by constructing them inline in business logic
3.3 WHEN unit testing a specific translator or the TranslationService THEN the system SHALL allow injection of mock translators and/or a test registry for isolated testing
3.4 WHEN a new API format translator is needed THEN the system SHALL allow registration of new translators without modifying existing translator dispatch logic (open/closed)

### Requirement 4

**User Story:** As a developer, I want each translator to implement a common interface, so that I can add new API format support without modifying existing code.

#### Acceptance Criteria

4.1 WHEN a new translator is created THEN the system SHALL require implementation of a translator protocol defining `to_domain_request`, `from_domain_request`, `to_domain_response`, `from_domain_response`
4.2 WHEN a streaming translator is created THEN the system SHALL require implementation of a streaming translator protocol defining `to_domain_stream_chunk` and `from_domain_stream_chunk`
4.3 WHEN the TranslationService receives a request/response/stream chunk THEN the system SHALL dispatch to the appropriate translator based on the format key, including known aliases (e.g., `openai-responses` → Responses translator)
4.4 WHEN a translator is registered THEN the system SHALL validate that the translator implements the required protocol

### Requirement 5

**User Story:** As a developer, I want the existing public APIs to remain unchanged, so that no calling code breaks after the refactoring.

#### Acceptance Criteria

5.1 WHEN external code calls any existing `Translation.*_to_domain_*` method for supported formats THEN the system SHALL return results equivalent to the pre-refactor behavior
5.2 WHEN external code calls any existing `Translation.from_domain_to_*` method for supported target formats THEN the system SHALL return results equivalent to the pre-refactor behavior
5.3 WHEN external code calls `TranslationService.to_domain_request`, `TranslationService.to_domain_response`, or `TranslationService.to_domain_stream_chunk` THEN the system SHALL return results equivalent to the pre-refactor behavior
5.4 WHEN external code calls `TranslationService.from_domain_request`, `TranslationService.from_domain_response`, or `TranslationService.from_domain_stream_chunk` THEN the system SHALL return results equivalent to the pre-refactor behavior
5.5 WHEN external code imports from `src/anthropic_converters.py` or `src/gemini_converters.py` THEN the system SHALL maintain backward-compatible exports

### Requirement 6

**User Story:** As a developer, I want streaming translation logic separated from non-streaming logic, so that I can maintain and optimize each independently.

#### Acceptance Criteria

6.1 WHEN processing a streaming request THEN the system SHALL use dedicated streaming translator components
6.2 WHEN processing a non-streaming request THEN the system SHALL use dedicated non-streaming translator components
6.3 WHEN a translator handles both streaming and non-streaming THEN the system SHALL separate the logic into distinct methods or classes

### Requirement 7

**User Story:** As a developer, I want the refactored code to have comprehensive test coverage, so that I can verify correctness and prevent regressions.

#### Acceptance Criteria

7.1 WHEN a translator module is created THEN the system SHALL have tests (unit and/or property-based) covering request translation
7.2 WHEN a translator module is created THEN the system SHALL have tests (unit and/or property-based) covering response translation
7.3 WHEN a translator module is created THEN the system SHALL have tests (unit and/or property-based) covering stream chunk translation
7.4 WHEN shared utilities are created THEN the system SHALL have tests (unit and/or property-based) covering edge cases and error conditions
7.5 WHEN the refactoring is complete THEN the system SHALL pass all existing tests with zero regressions

### Requirement 8

**User Story:** As a developer, I want the code organized following clean architecture principles, so that the codebase is maintainable and extensible.

#### Acceptance Criteria

8.1 WHEN organizing translator code THEN the system SHALL place translator implementations in `src/core/domain/translators/`
8.2 WHEN organizing shared utilities THEN the system SHALL place utility modules in `src/core/domain/translation_utils/`
8.3 WHEN organizing interfaces THEN the system SHALL place protocol definitions in `src/core/interfaces/`
8.4 WHEN a module has more than 500 lines THEN the system SHALL split it into smaller focused modules

### Requirement 9

**User Story:** As a developer, I want the Translation class to delegate to specialized translators, so that it becomes a thin facade rather than a God Object.

#### Acceptance Criteria

9.1 WHEN `Translation.gemini_to_domain_request` is called THEN the system SHALL delegate to the Gemini translator implementation
9.2 WHEN `Translation.anthropic_to_domain_response` is called THEN the system SHALL delegate to the Anthropic translator implementation
9.3 WHEN `Translation.openai_to_domain_stream_chunk` is called THEN the system SHALL delegate to the OpenAI translator implementation
9.4 WHEN the Translation class is refactored THEN `src/core/domain/translation.py` SHALL be reduced to a thin facade (≤ 500 lines)

### Requirement 10

**User Story:** As a developer, I want the refactoring to preserve all existing functionality including edge case handling, so that production behavior remains unchanged.

#### Acceptance Criteria

10.1 WHEN processing malformed JSON in tool arguments THEN the system SHALL handle the error gracefully as before
10.2 WHEN processing multimodal content with images THEN the system SHALL convert formats correctly as before
10.3 WHEN processing extended thinking/reasoning content THEN the system SHALL preserve reasoning data as before
10.4 WHEN processing tool calls with thought signatures THEN the system SHALL preserve signatures as before
10.5 WHEN processing empty or null content THEN the system SHALL handle edge cases as before
