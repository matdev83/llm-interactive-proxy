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

### Changed

- Improved type safety in ToolArgumentsParser with proper TelemetryRecorder typing
- Added race condition prevention with sequential execution for mypy validation tests
- Enhanced test coverage for tool call deduplicator and stream buffer adapter
- Refactored backend completion flow with improved availability checking
- Enhanced resilience layer architecture with better error handling
- Fixed concurrency issues in usage accounting and streaming metrics
- Updated configuration schemas and documentation
- Cleaned up completed specifications by moving to archive directory
