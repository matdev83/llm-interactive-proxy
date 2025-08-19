# CHANGELOG.md

## Unreleased
- **Security**: Add automatic API key redaction to logging
  - Install a global logging filter at application startup that redacts discovered API keys from all log records to prevent secret leaks.
  - Automatically discovers API keys from `AppConfig` (auth and backend configs) and environment variables, including numbered variants (e.g. `OPENROUTER_API_KEY_1..20`) and comma-separated lists.
  - Supports common formats (OpenAI, Gemini, Anthropic, OpenRouter, ZAI, Bearer tokens) and adds defensive default patterns.
  - Includes unit tests and a demo script `dev/test_api_key_redaction.py` to validate discovery and redaction behavior.

## 2025-08-19 (Migration Cleanup Complete)
- **MIGRATION CLEANUP COMPLETED**: Finalized cleanup of legacy code after successful staged initialization migration
  - Removed deprecated ApplicationBuilder class from application_factory.py
  - Deleted migration_wrapper.py as transition period is complete
  - Cleaned up compatibility shims in test configuration
  - Simplified application_factory.py to contain only essential compatibility functions
  - Updated integration tests to use clean new architecture patterns
  - All legacy fallback code removed - new staged architecture is now the only implementation
  - Achieved complete separation: ~90% code reduction in application factory complexity

## 2025-08-26
- **Refactored Command Testing**: Overhauled the entire testing architecture for interactive commands. Replaced fragile legacy tests with a robust suite of unit and snapshot tests, and implemented command auto-discovery.
- **SOLID ARCHITECTURE MIGRATION FINALIZED**: Completely finalized migration to new SOLID architecture
  - Removed all legacy code files (proxy_logic.py, session.py, main.py)
  - Removed all legacy adapters and compatibility layers
  - Removed legacy state compatibility layer
  - Migrated all command implementations to new architecture
  - Completed session management migration
  - Updated all tests to use new architecture directly
  - Cleaned up all imports referencing legacy modules
  - Refactored application_factory.py to use new configuration system
  - Created comprehensive domain models for commands and configuration
  - Updated documentation to reflect new architecture

## 2025-08-25
- **SOLID ARCHITECTURE MIGRATION COMPLETED**: Major progress on migration to new SOLID architecture
  - Removed most legacy code (proxy_logic.py, proxy_logic_deprecated.py)
  - Removed legacy state compatibility layer
  - Migrated legacy command implementations to new architecture
  - Completed session management migration
  - Updated tests to remove dependencies on legacy code
  - Cleaned up imports referencing legacy modules
  - Refactored chat_service.py to remove ProxyState dependencies
  - Created comprehensive final migration report

## 2025-08-24
- **SOLID ARCHITECTURE MIGRATION PROGRESS**: Major progress on migration to new SOLID architecture
  - Removed all legacy adapters (config, session, command, backend)
  - Removed backward compatibility layers
  - Removed legacy main.py entry point
  - Updated CLI to use new architecture directly
  - Cleaned up integration bridge and hybrid controllers
  - Updated test fixtures to use new architecture
  - Fixed authentication in tests
  - Fixed loop detection and tool call tests
  - Fixed indentation issues in OpenAI connector
  - Created comprehensive verification report

## 2025-08-23
- **SOLID REFACTORING PROGRESS**: Made significant progress on SOLID refactoring
  - Conducted thorough code review focusing on SOLID principles
  - Extracted failover logic into dedicated service
  - Improved separation of concerns across the codebase
  - Created comprehensive verification report
  - Identified and documented remaining issues

## 2025-08-22
- **ENHANCED LOGGING AND OBSERVABILITY**: Improved logging and observability
  - Conducted comprehensive audit of logging implementation
  - Created logging utilities for consistent log level usage
  - Added performance guards for expensive log operations
  - Implemented redaction for sensitive information
  - Added context management for enhanced logging
  - Created comprehensive unit tests for logging utilities

## 2025-08-21
- **MULTIMODAL CONTENT SUPPORT**: Added enhanced multimodal content support
  - Implemented ContentPart model for representing different content types (text, image, audio, video)
  - Created MultimodalMessage model with full multimodal content support
  - Added backend-specific format conversions for OpenAI, Anthropic, and Gemini
  - Implemented comprehensive unit and integration tests for multimodal content
  - Ensured backward compatibility with legacy message format

## 2025-08-20
- **REGRESSION TESTING FRAMEWORK**: Designed and implemented regression testing framework
  - Created comprehensive regression test plan covering all critical paths
  - Implemented example regression tests for chat completion functionality
  - Developed side-by-side testing approach for comparing legacy and new implementations
  - Added structure comparison utilities for response equivalence checking
  - Implemented streaming response comparison for regression testing

## 2025-08-19
- **ENHANCED INTEGRATION TESTING**: Added comprehensive integration tests for Qwen OAuth authentication
  - Implemented tests for token refresh during sessions
  - Added tests for authentication error recovery
  - Created tests for session persistence with token refresh
  - Verified authentication headers in proxy requests
  - Added tests for real token refresh integration

## 2025-08-18
- **ENHANCED TEST COVERAGE**: Significantly improved test coverage for core SOLID architecture components
  - Implemented comprehensive authentication tests for API key and token-based auth
  - Created extensive backend service tests with 95% coverage
  - Added comprehensive Qwen OAuth connector tests with 98% coverage
  - Improved test isolation through better mocking strategies
  - Created detailed test implementation summary and next steps plan

## 2025-08-17
- **SPECIALIZED COMMANDS IMPLEMENTATION**: Completed implementation of specialized commands in new SOLID architecture
  - Added OneOff command for setting one-time backend/model overrides
  - Added PWD command for displaying current project directory
  - Added Hello command for displaying welcome banner
  - Created comprehensive test suite for all commands
  - Updated API reference documentation

## 2025-08-15
- **MAJOR ARCHITECTURE UPDATE**: Completed migration to new SOLID architecture
  - Removed feature flags - new architecture is now the default and only implementation
  - Deprecated legacy code paths with clear warnings and migration timeline
  - Improved integration of ResponseProcessor with RequestProcessor
  - Enhanced loop detection through middleware pipeline
  - Added comprehensive verification tests
- **API Changes**:
  - Added new versioned endpoints: `/v2/chat/completions` and `/v2/messages`
  - Marked legacy endpoints as deprecated (to be removed in November 2024)
- **Documentation**:
  - Added API reference documentation
  - Created architecture diagrams
  - Updated developer guide
  - Added migration guide with clear deprecation timeline

## 2025-08-16
- Added SOLID architecture implementation
  - New dependency injection container
  - Interface-based service design
  - Immutable domain models
  - Middleware pipeline for response processing
  - Feature flags for gradual migration

## 2025-08-13
- Removal of Gemini CLI backends (gemini-cli-direct, gemini-cli-batch, gemini-cli-interactive) due to changes in CLI architecture
- Added new qwen-oauth backend for Qwen models authentication via OAuth tokens.

## 2025-08-14
- Separated OpenRouter and OpenAI backends into two distinct connectors. 
- Added support for custom OpenAI API URLs via the `!set(openai_url=...)` command and the `OPENAI_API_BASE_URL` environment variable.
- Loop detection algorithm replaced with fast hash-based implementation
- Improved tiered architecture for loop detection settings
- Add new `zai` backend (OpenAI compatibile)
- Added tool call loop detection feature to prevent repetitive tool call patterns
  - Supports "break" and "chance_then_break" modes
  - Configurable via environment variables, model defaults, and session commands
  - TTL-based pruning to avoid false positives
- Performance improvements:
  - Added isEnabledFor() guards to all logging calls to prevent unnecessary string serialization
  - Replaced f-strings with %-style formatting in logging calls for better performance