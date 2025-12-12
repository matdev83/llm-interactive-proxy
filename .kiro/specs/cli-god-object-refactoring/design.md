# Design Document: CLI God Object Refactoring

## Overview

This design document describes the refactoring of `src/core/cli.py` from a 3.1k LOC monolithic "God Object" into a modular, layered architecture following SOLID principles, DRY, proper dependency injection, and OOP design patterns. The refactoring extracts distinct responsibilities into specialized services while maintaining 100% backward compatibility with existing public APIs.

## Architecture

The refactored architecture follows a layered design with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────────────┐
│                    src/core/cli.py (Facade)                     │
│         Thin entry point delegating to specialized services     │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                 src/core/cli_support/ Package                   │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ ArgumentParser  │  │ Configuration   │  │ ServerLifecycle │  │
│  │    Builder      │  │   Applicator    │  │    Manager      │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │   Privilege     │  │    Logging      │  │     Error       │  │
│  │    Checker      │  │  Configurator   │  │    Handler      │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │              Domain Applicators (Strategy Pattern)          ││
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌───────┐ ││
│  │  │ Server  │ │ Logging │ │ Backend │ │ Session │ │ Auth  │ ││
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └───────┘ ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### Design Patterns Applied

1. **Facade Pattern**: `cli.py` becomes a thin facade exposing the same public API while delegating to internal services
2. **Strategy Pattern**: Domain applicators implement a common interface for applying configuration
3. **Builder Pattern**: `ArgumentParserBuilder` constructs the complex ArgumentParser step-by-step
4. **Template Method Pattern**: `ConfigurationApplicator` defines the skeleton for applying arguments
5. **Dependency Injection**: All services receive dependencies through constructor injection

### Naming and Packaging Constraints

- Python cannot safely support both `src/core/cli.py` (module) and `src/core/cli/` (package) at the same import path (`src.core.cli`) without import ambiguity and runtime breakage.
- Therefore, all extracted implementation code MUST live under a non-conflicting package such as `src/core/cli_support/`, while `src/core/cli.py` remains the stable public facade.
- The existing `src/core/cli_v2.py` compatibility layer must continue to work by delegating to `src/core/cli.py`.

## Invariants and Gotchas to Preserve

These are concrete behaviors from the current `src/core/cli.py` implementation and its tests. Treat them as regression targets while extracting services.

### CLI Surface and Imports

- `src/core/cli.py` remains the canonical implementation; `src/core/cli_v2.py` remains a thin compatibility layer delegating to it.
- No `src/core/cli/` package directory is created (module/package name collision).

### Argument Parser

- `build_cli_parser()` must preserve the full flag set (guarded by `tests/unit/test_cli_flag_snapshot.py` and `tests/test_cli_flags_documentation.py`).
- Backend choices for `--default-backend`/`--backend` remain dynamically populated from `backend_registry.get_registered_backends()`.
- Hidden/suppressed flags (e.g., `--backend` with `argparse.SUPPRESS`) remain hidden.
- Compatibility aliases remain accepted where present (e.g., both `--reasoning-injection-probability` and `--reasoning_injection_probability`).

### Parsed-Args Validation

- `parse_cli_args()` continues to run non-argparse validation (e.g., LLM loop assessment config) and raises stable, testable exceptions with the same messages.

### Configuration Application (`apply_cli_args`)

- Configuration loading continues via `load_config(config_path, resolution=res)` and all CLI-applied values record `ParameterResolution` entries with the correct path and origin flag.
- Default log file behavior remains: if neither CLI nor config provides a log file, set `./var/logs/proxy.log` and ensure directories exist.
- Environment variable side effects remain (examples: `PROXY_PORT`, `COMMAND_PREFIX`, `FORCE_CONTEXT_WINDOW`, `THINKING_BUDGET`, `DISABLE_*` toggles).
- Merge semantics remain: apply `cli_overrides` onto `cfg.model_dump(mode="json")` via `_merge_dicts`, then `AppConfig.model_validate(...)`.
- `command_prefix` is never left as `None` after merging (fallback to `DEFAULT_COMMAND_PREFIX`) and is validated via `validate_command_prefix`.
- Return-type behavior remains: default returns `AppConfig`; with `return_resolution=True` returns `(AppConfig, ParameterResolution)`.

### Startup (`main`)

- `main()` remains `async`, accepts `argv` and optional `build_app_fn`, and continues delegating application build to `build_app_async(cfg)` (or `build_app_fn(cfg)` in tests).
- Daemon mode behavior remains: requires `--log`/`cfg.logging.log_file`; Windows uses a detached subprocess; Unix uses fork-based daemonization.
- Privilege check behavior remains: `--allow-admin` bypasses; otherwise refuse elevated privileges via `SystemExit`.
- When auth is disabled, host binding is forced to `127.0.0.1` for safety.
- Port checks remain for both main `cfg.port` and optional `cfg.anthropic_port`.
- When `cfg.anthropic_port` is enabled, startup creates the Anthropic app via `create_anthropic_app_async(cfg, built_app=app)` and runs both uvicorn servers concurrently.

## Components and Interfaces

### 1. ArgumentParserBuilder

**Location**: `src/core/cli_support/argument_parser_builder.py`

**Responsibility**: Constructs the `argparse.ArgumentParser` with all CLI arguments organized by domain.

```python
class ArgumentParserBuilder:
    """Builder for constructing the CLI argument parser."""
    
    def __init__(self) -> None:
        self._parser: argparse.ArgumentParser | None = None
    
    def build(self) -> argparse.ArgumentParser:
        """Build and return the complete argument parser."""
        ...
    
    def _add_server_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add server-related arguments (host, port, timeout, etc.)."""
        ...
    
    def _add_backend_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add backend selection and configuration arguments."""
        ...
    
    def _add_logging_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add logging and capture arguments."""
        ...
    
    def _add_session_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add session and feature flag arguments."""
        ...
    
    def _add_auth_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add authentication and security arguments."""
        ...
    
    def _add_assessment_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add LLM assessment arguments."""
        ...
    
    def _add_memory_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add ProxyMem arguments."""
        ...
    
    def _add_failure_handling_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add failure handling arguments."""
        ...
```

### 1b. CliArgsValidator

**Location**: `src/core/cli_support/cli_args_validator.py`

**Responsibility**: Performs non-argparse validation on already-parsed arguments (e.g., validating LLM loop assessment configuration) and raises stable, testable exceptions on failure.

```python
class CliArgsValidator:
    """Validates parsed CLI args beyond argparse's built-in checks."""

    def validate(self, args: argparse.Namespace) -> None:
        """Raise ValueError/SystemExit with stable messages when invalid."""
        ...
```

### 2. ConfigurationApplicator

**Location**: `src/core/cli_support/configuration_applicator.py`

**Responsibility**: Coordinates applying parsed CLI arguments to AppConfig using domain-specific applicators.

```python
from abc import ABC, abstractmethod
from typing import Protocol

class DomainApplicator(Protocol):
    """Protocol for domain-specific configuration applicators."""
    
    def apply(
        self,
        args: argparse.Namespace,
        config_dict: dict[str, Any],
        resolution: ParameterResolution,
    ) -> None:
        """Apply domain-specific arguments to config dict."""
        ...

class ConfigurationApplicator:
    """Coordinates applying CLI arguments to AppConfig."""
    
    def __init__(
        self,
        domain_applicators: list[DomainApplicator] | None = None,
    ) -> None:
        self._applicators = domain_applicators or self._default_applicators()
    
    def apply(
        self,
        args: argparse.Namespace,
        base_config: AppConfig,
        resolution: ParameterResolution,
    ) -> AppConfig:
        """Apply all CLI arguments to configuration."""
        ...
    
    def _default_applicators(self) -> list[DomainApplicator]:
        """Return default set of domain applicators."""
        ...
```

### 3. Domain Applicators

**Location**: `src/core/cli_support/applicators/`

Each domain applicator handles a specific configuration section:

```python
# src/core/cli_support/applicators/server_applicator.py
class ServerApplicator:
    """Applies server-related CLI arguments."""
    
    def apply(
        self,
        args: argparse.Namespace,
        config_dict: dict[str, Any],
        resolution: ParameterResolution,
    ) -> None:
        """Apply host, port, timeout, command_prefix, etc."""
        ...

# src/core/cli_support/applicators/logging_applicator.py
class LoggingApplicator:
    """Applies logging-related CLI arguments."""
    
    def apply(
        self,
        args: argparse.Namespace,
        config_dict: dict[str, Any],
        resolution: ParameterResolution,
    ) -> None:
        """Apply log_file, log_level, capture settings, etc."""
        ...

# src/core/cli_support/applicators/backend_applicator.py
class BackendApplicator:
    """Applies backend-related CLI arguments."""
    
    def apply(
        self,
        args: argparse.Namespace,
        config_dict: dict[str, Any],
        resolution: ParameterResolution,
    ) -> None:
        """Apply default_backend, API keys, debugging overrides, etc."""
        ...

# Additional applicators: SessionApplicator, AuthApplicator, 
# AssessmentApplicator, MemoryApplicator, FailureHandlingApplicator, etc.
```

### 4. ServerLifecycleManager

**Location**: `src/core/cli_support/server_lifecycle_manager.py`

**Responsibility**: Manages server startup, shutdown, and daemon mode.

```python
class ServerLifecycleManager:
    """Manages server lifecycle including startup, shutdown, and daemon mode."""
    
    def __init__(
        self,
        privilege_checker: PrivilegeChecker,
        logging_configurator: LoggingConfigurator,
        error_handler: ErrorHandler,
    ) -> None:
        self._privilege_checker = privilege_checker
        self._logging_configurator = logging_configurator
        self._error_handler = error_handler
    
    async def start(
        self,
        app: FastAPI,
        config: AppConfig,
        anthropic_app: FastAPI | None = None,
    ) -> None:
        """Start the server(s) with proper coordination."""
        ...
    
    def handle_daemon_mode(
        self,
        args: argparse.Namespace,
        config: AppConfig,
    ) -> bool:
        """Handle daemon mode if requested. Returns True if should exit."""
        ...
    
    def check_port_availability(self, host: str, port: int) -> None:
        """Check if port is available, raise if not."""
        ...
```

### 5. PrivilegeChecker

**Location**: `src/core/cli_support/privilege_checker.py`

**Responsibility**: Cross-platform privilege/admin detection.

```python
from typing import Protocol

class PlatformDetector(Protocol):
    """Protocol for platform detection (injectable for testing)."""
    
    def is_windows(self) -> bool: ...
    def is_unix(self) -> bool: ...
    def get_euid(self) -> int | None: ...
    def check_windows_admin(self) -> bool: ...

class PrivilegeChecker:
    """Cross-platform privilege checking service."""
    
    def __init__(
        self,
        platform_detector: PlatformDetector | None = None,
    ) -> None:
        self._platform = platform_detector or DefaultPlatformDetector()
    
    def is_admin(self) -> bool:
        """Check if running with elevated privileges."""
        ...
    
    def check_and_enforce(self, allow_admin: bool = False) -> None:
        """Check privileges and raise if admin without permission."""
        ...
```

### 6. LoggingConfigurator

**Location**: `src/core/cli_support/logging_configurator.py`

**Responsibility**: Configure logging based on AppConfig.

```python
class LoggingConfigurator:
    """Configures logging based on application configuration."""
    
    def configure(self, config: AppConfig) -> None:
        """Configure logging with level, file, and color settings."""
        ...
    
    def apply_timestamp_suffix(self, path: str | None) -> str | None:
        """Apply timestamp suffix to log file path."""
        ...
    
    def apply_pid_suffixes(self, config: AppConfig) -> AppConfig:
        """Return config with timestamp-suffixed log and capture files."""
        ...
```

### 7. ErrorHandler

**Location**: `src/core/cli_support/error_handler.py`

**Responsibility**: Format user-friendly error messages.

```python
from enum import Enum
from typing import TextIO

class ErrorType(Enum):
    """Types of errors for specialized handling."""
    OAUTH_EXPIRED = "oauth_expired"
    OAUTH_MISSING = "oauth_missing"
    OAUTH_INVALID = "oauth_invalid"
    API_KEY_MISSING = "api_key_missing"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    PORT_IN_USE = "port_in_use"
    UNKNOWN = "unknown"

class ErrorHandler:
    """Formats user-friendly error messages."""
    
    def __init__(self, output: TextIO | None = None) -> None:
        self._output = output or sys.stderr
    
    def handle_build_error(self, error_msg: str) -> None:
        """Handle application build errors with actionable guidance."""
        ...
    
    def classify_error(self, error_msg: str) -> ErrorType:
        """Classify error message into error type."""
        ...
    
    def format_oauth_expired_message(self, error_msg: str) -> str:
        """Format message for OAuth token expiration."""
        ...
    
    def format_api_key_missing_message(self) -> str:
        """Format message for missing API keys."""
        ...
```

## Data Models

The refactoring does not introduce new data models. It uses existing models:

- `AppConfig` from `src/core/config/app_config.py`
- `ParameterResolution` from `src/core/config/parameter_resolution.py`
- `argparse.Namespace` for parsed arguments

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Argument Parsing Round-Trip Consistency

*For any* valid combination of CLI arguments, parsing with `ArgumentParserBuilder` and applying with `ConfigurationApplicator` SHALL produce an `AppConfig` equivalent to the original `apply_cli_args` function.

**Validates: Requirements 1.1, 1.2, 7.1**

### Property 2: Parameter Source Recording Completeness

*For any* CLI argument that modifies AppConfig, the `ParameterResolution` SHALL contain an entry recording the parameter path, value, and CLI flag origin.

**Validates: Requirements 1.3**

### Property 3: Domain Applicator Isolation

*For any* domain applicator, applying arguments SHALL only modify configuration keys within its designated domain (e.g., `LoggingApplicator` only modifies `logging.*` keys).

**Validates: Requirements 6.2**

### Property 4: Error Classification Consistency

*For any* error message containing known patterns (e.g., "Token expired", "api_key is required"), the `ErrorHandler.classify_error` SHALL return the corresponding `ErrorType`.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4**

### Property 5: Timestamp Suffix Format Validity

*For any* file path, applying `LoggingConfigurator.apply_timestamp_suffix` SHALL produce a path matching the pattern `{stem}-YYYYMMDD_HHMM{suffix}` or return the original if already suffixed.

**Validates: Requirements 4.2**

### Property 6: Privilege Check Enforcement

*For any* platform where `is_admin()` returns True and `allow_admin` is False, `PrivilegeChecker.check_and_enforce` SHALL raise `SystemExit`.

**Validates: Requirements 3.2**

### Property 7: Public API Signature Preservation

*For any* call to `parse_cli_args()` or `apply_cli_args()`, the function signatures and return types SHALL match the original implementation exactly.

**Validates: Requirements 7.4, 7.5**

## Error Handling

### Error Classification Strategy

The `ErrorHandler` classifies errors into categories for specialized handling:

1. **OAuth Errors**: Token expiration, missing credentials, invalid credentials
2. **API Key Errors**: Missing required API keys
3. **Network Errors**: Backend unavailability, connection failures
4. **Resource Errors**: Port in use, file access issues
5. **Unknown Errors**: Fallback with generic guidance

### Error Message Format

All error messages follow a consistent format:
```
============================================================
ERROR: Failed to start LLM Interactive Proxy
============================================================

[Problem description]

DETECTED ISSUE: [Specific issue if identifiable]

To fix this:
  - [Actionable step 1]
  - [Actionable step 2]
  ...

For more help, see the documentation or check your configuration.
============================================================
```

## Testing Strategy

### Unit Testing

Each service will have dedicated unit tests:

- `tests/unit/core/cli_support/test_argument_parser_builder.py`: Test parser construction and argument definitions
- `tests/unit/core/cli_support/test_configuration_applicator.py`: Test argument application with mock applicators
- `tests/unit/core/cli_support/test_domain_applicators.py`: Test each domain applicator in isolation
- `tests/unit/core/cli_support/test_server_lifecycle_manager.py`: Test lifecycle coordination with mocks
- `tests/unit/core/cli_support/test_privilege_checker.py`: Test privilege detection with mock platform detector
- `tests/unit/core/cli_support/test_logging_configurator.py`: Test logging setup with mock handlers
- `tests/unit/core/cli_support/test_error_handler.py`: Test error classification and message formatting

### Property-Based Testing

Using `hypothesis` library for property-based tests:

1. **Argument Parsing Round-Trip**: Generate random valid argument combinations, verify AppConfig equivalence
2. **Parameter Source Recording**: Generate arguments, verify ParameterResolution completeness
3. **Domain Isolation**: Generate arguments, verify each applicator only modifies its domain
4. **Error Classification**: Generate error messages with known patterns, verify classification
5. **Timestamp Suffix**: Generate file paths, verify suffix format

### Integration Testing

- **Backward Compatibility**: Run existing CLI tests without modification
- **End-to-End**: Test full CLI invocation with various argument combinations
- **Regression**: Ensure full test suite passes with zero failures

### Test Configuration

Property-based tests will use:
- Minimum 100 iterations per property
- Explicit test annotations linking to design properties
- Format: `**Feature: cli-god-object-refactoring, Property {N}: {description}**`
