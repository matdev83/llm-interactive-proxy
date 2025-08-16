# CHANGELOG.md

## 2024-07-15
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

## 2024-07-01
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