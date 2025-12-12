# Requirements Document

## Introduction

This document specifies the requirements for refactoring `src/core/cli.py`, a 3.1k LOC "God Object" that violates multiple architectural principles. The CLI entry point currently contains significant business logic that should be distributed across specialized services following SOLID principles, DRY, proper DI container usage, and OOP design patterns. The refactoring must preserve all public APIs and maintain 100% backward compatibility while achieving a modular, layered architecture with strong separation of concerns.

## Glossary

- **CLI_Module**: The `src/core/cli.py` module serving as the command-line entry point for the LLM proxy server
- **AppConfig**: The application configuration object (`src/core/config/app_config.py`) that holds all runtime settings
- **ParameterResolution**: A tracking mechanism for recording the source of configuration parameters (CLI, env, config file)
- **ArgumentParser**: The `argparse.ArgumentParser` instance that defines and parses CLI arguments
- **ConfigurationApplicator**: A proposed service responsible for applying parsed CLI arguments to AppConfig
- **ServerLifecycleManager**: A proposed service responsible for server startup, shutdown, and daemon mode handling
- **PrivilegeChecker**: A proposed service responsible for cross-platform privilege/admin detection
- **LoggingConfigurator**: A proposed service responsible for configuring logging based on AppConfig
- **ErrorHandler**: A proposed service responsible for user-friendly error message formatting

## Requirements

### Requirement 1

**User Story:** As a developer, I want the CLI argument parsing to be separated from configuration application, so that I can test and maintain each concern independently.

#### Acceptance Criteria

1. WHEN the CLI_Module parses arguments THEN the ArgumentParser SHALL be constructed by a dedicated `ArgumentParserBuilder` class
2. WHEN CLI arguments are parsed THEN the CLI_Module SHALL delegate to a `ConfigurationApplicator` service for applying arguments to AppConfig
3. WHEN the `ConfigurationApplicator` applies arguments THEN the service SHALL record parameter sources via ParameterResolution
4. WHEN argument validation fails THEN the CLI_Module SHALL receive a structured error from the validation service
5. WHEN a new CLI argument is added THEN the developer SHALL only need to modify the `ArgumentParserBuilder` and `ConfigurationApplicator`

### Requirement 2

**User Story:** As a developer, I want server lifecycle management extracted into a dedicated service, so that startup, shutdown, and daemon mode logic are testable in isolation.

#### Acceptance Criteria

1. WHEN the server starts THEN the ServerLifecycleManager SHALL coordinate port availability checks, privilege verification, and uvicorn startup
2. WHEN daemon mode is requested THEN the ServerLifecycleManager SHALL handle platform-specific daemonization (Unix fork, Windows subprocess)
3. WHEN the server encounters a startup error THEN the ServerLifecycleManager SHALL delegate to ErrorHandler for user-friendly messages
4. WHEN multiple servers start (main + Anthropic) THEN the ServerLifecycleManager SHALL coordinate their concurrent execution
5. WHEN the server shuts down THEN the ServerLifecycleManager SHALL ensure graceful cleanup of all resources

### Requirement 3

**User Story:** As a developer, I want privilege checking extracted into a dedicated service, so that cross-platform admin detection is reusable and testable.

#### Acceptance Criteria

1. WHEN privilege checking is invoked THEN the PrivilegeChecker SHALL detect admin/root status on Windows, Linux, and macOS
2. WHEN running as admin without `--allow-admin` THEN the PrivilegeChecker SHALL raise a structured exception
3. WHEN the platform lacks privilege functionality THEN the PrivilegeChecker SHALL return a safe default without crashing
4. WHEN privilege checking is tested THEN the PrivilegeChecker SHALL accept injectable platform detection for mocking

### Requirement 4

**User Story:** As a developer, I want logging configuration extracted into a dedicated service, so that log setup is consistent and testable.

#### Acceptance Criteria

1. WHEN logging is configured THEN the LoggingConfigurator SHALL apply log level, file path, and color settings from AppConfig
2. WHEN log file paths need timestamp suffixes THEN the LoggingConfigurator SHALL apply them consistently
3. WHEN logging configuration fails THEN the LoggingConfigurator SHALL provide clear error messages
4. WHEN the LoggingConfigurator is tested THEN it SHALL accept injectable logging handlers for verification

### Requirement 5

**User Story:** As a developer, I want error handling extracted into a dedicated service, so that user-friendly error messages are consistent and maintainable.

#### Acceptance Criteria

1. WHEN an application build error occurs THEN the ErrorHandler SHALL format a user-friendly message with actionable guidance
2. WHEN OAuth token expiration is detected THEN the ErrorHandler SHALL provide specific re-authentication instructions
3. WHEN API key errors occur THEN the ErrorHandler SHALL list required environment variables
4. WHEN an unknown error occurs THEN the ErrorHandler SHALL provide generic troubleshooting guidance
5. WHEN error messages are displayed THEN the ErrorHandler SHALL write to stderr with consistent formatting

### Requirement 6

**User Story:** As a developer, I want the `apply_cli_args` function decomposed into smaller, focused functions, so that each configuration domain is handled independently.

#### Acceptance Criteria

1. WHEN CLI arguments are applied THEN the ConfigurationApplicator SHALL delegate to domain-specific applicators (server, logging, backends, session, auth, etc.)
2. WHEN a domain applicator processes arguments THEN it SHALL only modify its relevant configuration section
3. WHEN environment variables are set THEN the domain applicator SHALL handle them within its scope
4. WHEN a new configuration domain is added THEN the developer SHALL create a new domain applicator without modifying existing ones
5. WHEN domain applicators are tested THEN each SHALL be testable in isolation with mock AppConfig

### Requirement 7

**User Story:** As a developer, I want the refactored CLI to maintain 100% backward compatibility, so that existing scripts and integrations continue to work.

#### Acceptance Criteria

1. WHEN the refactored CLI is invoked THEN all existing command-line arguments SHALL be accepted with identical behavior
2. WHEN the refactored CLI produces output THEN log messages and error formats SHALL match the original implementation
3. WHEN the refactored CLI is tested THEN all existing CLI tests SHALL pass without modification
4. WHEN the `main()` function is called THEN its signature and behavior SHALL remain unchanged
5. WHEN `parse_cli_args()` or `apply_cli_args()` are called externally THEN their signatures and return types SHALL remain unchanged

### Requirement 8

**User Story:** As a developer, I want the refactored code to follow proper dependency injection patterns, so that services are loosely coupled and testable.

#### Acceptance Criteria

1. WHEN services are instantiated THEN they SHALL receive dependencies through constructor injection
2. WHEN services need configuration THEN they SHALL receive AppConfig or relevant subsections through injection
3. WHEN services are tested THEN mock dependencies SHALL be injectable without modifying production code
4. WHEN the DI container is used THEN services SHALL be registered and resolved through the container

### Requirement 9

**User Story:** As a developer, I want the refactored code to have comprehensive test coverage, so that regressions are caught early.

#### Acceptance Criteria

1. WHEN new services are created THEN each SHALL have unit tests covering its public methods
2. WHEN the refactoring is complete THEN the full test suite SHALL pass with zero regressions
3. WHEN edge cases are identified THEN property-based tests SHALL verify behavior across input ranges
4. WHEN integration points are modified THEN integration tests SHALL verify end-to-end behavior

### Requirement 10

**User Story:** As a developer, I want the refactored code organized into a clear module structure, so that related functionality is easy to locate.

#### Acceptance Criteria

1. WHEN the refactoring is complete THEN new services SHALL reside in `src/core/cli/` subdirectory
2. WHEN the CLI module is imported THEN the public API SHALL be exposed through `src/core/cli/__init__.py`
3. WHEN a developer looks for CLI-related code THEN the module structure SHALL clearly indicate each service's purpose
4. WHEN the original `cli.py` is retained THEN it SHALL serve as a thin facade delegating to the new services
