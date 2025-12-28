# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

### Added

- Implemented Kiro spec archiving system with documentation updates
- Added archive functionality and allowlist for completed specifications
- Added test execution reminder functionality
- Implemented vendor model dynamic routing capabilities
- Added SSO authentication integration
- Added random model replacement feature with DI wiring, configuration options, and metrics docs
- **Context Compaction**: Max tokens overflow warnings (Req 3.2) - operators now receive warnings when compaction cannot reduce tokens below configured maximum, enabling proactive capacity planning
- **Context Compaction**: Metrics export via structured logging (Req 4.1) - all compaction operations now emit detailed metrics for observability, including messages compacted, bytes saved, and estimated token savings
- **Context Compaction**: Configurable resource identifier redaction (Req 4.5) - optional redaction of file paths and commands in compaction stubs for security-sensitive environments (default: OFF for debuggability)
- **Documentation**: Comprehensive user guide for context compaction feature with configuration examples, troubleshooting, and best practices

### Changed

- Improved type safety in ToolArgumentsParser with proper TelemetryRecorder typing
- Added race condition prevention with sequential execution for mypy validation tests
- Enhanced test coverage for tool call deduplicator and stream buffer adapter
- Refactored backend completion flow with improved availability checking
- Enhanced resilience layer architecture with better error handling
- Fixed concurrency issues in usage accounting and streaming metrics
- Updated configuration schemas and documentation
- Cleaned up completed specifications by moving to archive directory
- **Context Compaction**: Enhanced logging to include both observability context and metrics in structured format

### Fixed

- **Context Compaction**: Completed all P1 observability and safety requirements per specification
- **Tests**: Fixed redaction test API key patterns to match expected regex format
