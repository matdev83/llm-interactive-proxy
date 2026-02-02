# Requirements Document

## Project Description (Input)

Introduce two runtime proxy access modes:
- **Single User Mode**: Default mode for local development with optional authentication, allows OAuth-based connectors
- **Multi User Mode**: Production mode for shared/remote deployments with mandatory authentication, blocks OAuth-based connectors

Add related CLI flags to control the above modes.

**Rules/constraints/behaviors:**

Default access mode: Single User Mode if not explicitly specified and unless overridden.

In Single User Mode:
- Proxy can only be started if bound to the 127.0.0.1 IP address and no other, refuse to start otherwise
- User has the ability to use OAuth-based connectors
- Proxy can be started with authentication disabled

In Multi User Mode:
- Proxy can be bound to any IP address, but if it is bound to anything other than 127.0.0.1, authentication (API key or SSO) must be enabled (otherwise refuse to start)
- User cannot use any OAuth-based connectors. Such connectors are not even loaded at the proxy startup
- If user provides override flags to enable specific OAuth connectors (e.g., `--enable-gemini-oauth-auto-backend-debugging-override` or `--enable-opencode-zen-backend-debugging-override` or any similar), proxy should refuse to start
- `--allow-oauth-auto-replacement` cannot be specified, otherwise refuse to start

## Initial Context (Non-Exhaustive)

Key current touchpoints (for discovery/design phases):
- `src/core/cli.py` - CLI entry point and argument parsing
- `src/core/cli_support/argument_parser_builder.py` - CLI argument construction
- `src/core/cli_support/cli_args_validator.py` - CLI argument validation
- `src/core/config/app_config.py` - Application configuration model
- `src/connectors/__init__.py` - Backend connector auto-discovery and loading
- `src/core/services/backend_registry.py` - Backend registration
- OAuth-based connectors: `gemini-oauth-*`, `anthropic-oauth`, `qwen-oauth`, `openai-codex`, etc.

## Requirements

## Introduction

**Project Context**: Universal LLM Proxy - a FastAPI-based gateway for LLM APIs providing intelligent routing, failover, and observability. The proxy supports both local development scenarios (single developer) and production deployments (multiple users).

**Problem Statement**: The proxy currently lacks explicit access mode controls that enforce security boundaries appropriate to deployment context. Local development requires flexibility (optional auth, OAuth connectors), while production deployments require strict security (mandatory auth, no personal OAuth credentials). Without explicit modes, operators must manually configure multiple settings correctly, increasing risk of misconfiguration.

**Stakeholders**:
- Developers using the proxy locally for development and testing
- DevOps/Platform teams deploying the proxy for team or organization use
- Security teams ensuring proper authentication and credential isolation
- End users relying on secure, properly configured proxy instances

## Glossary

| Term | Definition |
|------|------------|
| Access Mode | The operational security posture of the proxy: Single User Mode or Multi User Mode |
| Single User Mode | Default mode for local development; allows OAuth connectors, optional authentication, localhost-only binding |
| Multi User Mode | Production mode for shared deployments; blocks OAuth connectors, requires authentication for non-localhost, allows any IP binding |
| OAuth-based connector | Backend connector that uses personal OAuth credentials (e.g., `gemini-oauth-auto`, `anthropic-oauth`, `qwen-oauth`, `openai-codex`) |
| Static credential connector | Backend connector that uses API keys or service account credentials (e.g., `openai`, `anthropic`, `gemini`) |
| Localhost binding | Binding the proxy server to 127.0.0.1 IP address only |
| Remote binding | Binding the proxy server to any IP address other than 127.0.0.1 (e.g., 0.0.0.0, specific network interface) |
| OAuth debugging override flag | CLI flag that enables specific OAuth connectors for debugging (e.g., `--enable-gemini-oauth-auto-backend-debugging-override`) |
| OAuth auto-replacement | Feature that automatically replaces backend selections with OAuth variants |

## Requirements

### Requirement 1: Access Mode Selection
**Objective:** As an operator, I want to explicitly select between Single User Mode and Multi User Mode, so that the proxy enforces appropriate security boundaries for my deployment context.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1.1 WHEN the proxy starts without an explicit access mode flag THEN the system SHALL default to Single User Mode.
1.2 WHEN the operator specifies `--single-user-mode` flag THEN the system SHALL operate in Single User Mode.
1.3 WHEN the operator specifies `--multi-user-mode` flag THEN the system SHALL operate in Multi User Mode.
1.4 WHEN both `--single-user-mode` and `--multi-user-mode` flags are specified THEN the system SHALL refuse to start with a clear error message indicating mutual exclusivity.
1.5 WHEN the access mode is determined THEN the system SHALL log the selected mode at INFO level during startup.

#### Technical Constraints
- The access mode selection shall occur early in the startup sequence before backend loading
- The mode shall be immutable after startup (no runtime mode switching)

### Requirement 2: Single User Mode - Localhost Binding Enforcement
**Objective:** As a security-conscious developer, I want Single User Mode to enforce localhost-only binding, so that my local development proxy cannot be accidentally exposed to the network.

**Priority:** P0 (Critical)

#### Acceptance Criteria
2.1 WHEN operating in Single User Mode and the host is set to 127.0.0.1 THEN the system SHALL start successfully.
2.2 WHEN operating in Single User Mode and the host is set to any value other than 127.0.0.1 THEN the system SHALL refuse to start with a clear error message.
2.3 WHEN the system refuses to start due to non-localhost binding in Single User Mode THEN the error message SHALL indicate that Single User Mode requires 127.0.0.1 binding.
2.4 WHEN the system refuses to start due to non-localhost binding in Single User Mode THEN the error message SHALL suggest using Multi User Mode for remote access.

#### Technical Constraints
- The validation shall occur after configuration loading but before server initialization
- The validation shall apply to both the main proxy port and the Anthropic-specific port

### Requirement 3: Single User Mode - OAuth Connector Support
**Objective:** As a developer, I want to use OAuth-based connectors in Single User Mode, so that I can leverage my personal credentials for development and testing.

**Priority:** P0 (Critical)

#### Acceptance Criteria
3.1 WHEN operating in Single User Mode THEN the system SHALL load and register OAuth-based connectors during startup.
3.2 WHEN operating in Single User Mode THEN the system SHALL allow requests to OAuth-based connectors.
3.3 WHEN operating in Single User Mode THEN the system SHALL allow OAuth debugging override flags to be specified.
3.4 WHEN operating in Single User Mode THEN the system SHALL allow the `--allow-oauth-auto-replacement` flag to be specified.

#### Technical Constraints
- OAuth connector loading shall follow the existing auto-discovery mechanism in `src/connectors/__init__.py`

### Requirement 4: Single User Mode - Optional Authentication
**Objective:** As a developer, I want to optionally disable authentication in Single User Mode, so that I can simplify local development workflows.

**Priority:** P0 (Critical)

#### Acceptance Criteria
4.1 WHEN operating in Single User Mode with authentication disabled THEN the system SHALL start successfully.
4.2 WHEN operating in Single User Mode with authentication enabled THEN the system SHALL start successfully.
4.3 WHEN operating in Single User Mode THEN the system SHALL allow the `--disable-auth` flag to be specified.

#### Technical Constraints
- The authentication configuration shall be independent of access mode selection
- Existing authentication enforcement logic shall remain unchanged

### Requirement 5: Multi User Mode - IP Binding and Authentication Enforcement
**Objective:** As a platform operator, I want Multi User Mode to enforce authentication when bound to non-localhost addresses, so that remote access is always authenticated.

**Priority:** P0 (Critical)

#### Acceptance Criteria
5.1 WHEN operating in Multi User Mode and the host is set to 127.0.0.1 with authentication disabled THEN the system SHALL start successfully.
5.2 WHEN operating in Multi User Mode and the host is set to 127.0.0.1 with authentication enabled THEN the system SHALL start successfully.
5.3 WHEN operating in Multi User Mode and the host is set to any value other than 127.0.0.1 with authentication enabled THEN the system SHALL start successfully.
5.4 WHEN operating in Multi User Mode and the host is set to any value other than 127.0.0.1 with authentication disabled THEN the system SHALL refuse to start with a clear error message.
5.5 WHEN the system refuses to start due to missing authentication in Multi User Mode THEN the error message SHALL indicate that Multi User Mode requires authentication for non-localhost binding.
5.6 WHEN the system refuses to start due to missing authentication in Multi User Mode THEN the error message SHALL indicate which authentication methods are available (API key or SSO).

#### Technical Constraints
- The validation shall occur after configuration loading but before server initialization
- The validation shall apply to both the main proxy port and the Anthropic-specific port
- Authentication shall be considered enabled if either API key authentication or SSO is configured

### Requirement 6: Multi User Mode - OAuth Connector Blocking
**Objective:** As a platform operator, I want Multi User Mode to block OAuth-based connectors, so that personal credentials cannot be used in shared deployments.

**Priority:** P0 (Critical)

#### Acceptance Criteria
6.1 WHEN operating in Multi User Mode THEN the system SHALL NOT load or register OAuth-based connectors during startup.
6.2 WHEN operating in Multi User Mode THEN the system SHALL skip OAuth-based connector modules during auto-discovery.
6.3 WHEN operating in Multi User Mode and an OAuth-based connector is explicitly configured THEN the system SHALL log a warning indicating the connector is being skipped.
6.4 WHEN operating in Multi User Mode THEN the system SHALL NOT include OAuth-based connectors in the backend registry.
6.5 WHEN operating in Multi User Mode THEN requests to OAuth-based connectors SHALL fail with a clear error indicating the connector is not available in Multi User Mode.

#### Technical Constraints
- OAuth connector detection shall be based on connector naming patterns (e.g., `-oauth-`, `-oauth`) and the `has_static_credentials` property (returns `False` for OAuth connectors)
- The blocking shall occur during the connector loading phase before registration
- The system shall maintain a list of known OAuth connector patterns for detection
- OAuth connectors include: `gemini-oauth-*`, `anthropic-oauth`, `qwen-oauth`, `openai-codex`, and any connector with `has_static_credentials = False`

### Requirement 7: Multi User Mode - OAuth Override Flag Rejection
**Objective:** As a platform operator, I want Multi User Mode to reject OAuth debugging override flags, so that developers cannot bypass OAuth connector restrictions.

**Priority:** P0 (Critical)

#### Acceptance Criteria
7.1 WHEN operating in Multi User Mode and any OAuth debugging override flag is specified THEN the system SHALL refuse to start with a clear error message.
7.2 WHEN the system refuses to start due to OAuth override flags in Multi User Mode THEN the error message SHALL list the conflicting flags.
7.3 WHEN the system refuses to start due to OAuth override flags in Multi User Mode THEN the error message SHALL indicate that OAuth connectors are not allowed in Multi User Mode.
7.4 WHEN operating in Multi User Mode THEN the system SHALL validate all CLI arguments for OAuth override flags before backend loading.

#### Technical Constraints
- The validation shall detect all OAuth debugging override flags (e.g., `--enable-gemini-oauth-auto-backend-debugging-override`, `--enable-anthropic-oauth-backend-debugging-override`, `--enable-openai-codex-backend-debugging-override`, etc.)
- The validation shall occur early in the startup sequence

### Requirement 8: Multi User Mode - OAuth Auto-Replacement Rejection
**Objective:** As a platform operator, I want Multi User Mode to reject the OAuth auto-replacement flag, so that automatic OAuth backend selection cannot occur.

**Priority:** P0 (Critical)

#### Acceptance Criteria
8.1 WHEN operating in Multi User Mode and the `--allow-oauth-auto-replacement` flag is specified THEN the system SHALL refuse to start with a clear error message.
8.2 WHEN the system refuses to start due to `--allow-oauth-auto-replacement` in Multi User Mode THEN the error message SHALL indicate that OAuth auto-replacement is not allowed in Multi User Mode.
8.3 WHEN operating in Multi User Mode THEN the system SHALL validate the `--allow-oauth-auto-replacement` flag before backend loading.

#### Technical Constraints
- The validation shall occur early in the startup sequence

### Requirement 9: Multi User Mode - Desktop Notifications Rejection
**Objective:** As a platform operator, I want Multi User Mode to reject desktop notifications, so that server deployments don't attempt to use desktop-specific features.

**Priority:** P0 (Critical)

#### Acceptance Criteria
9.1 WHEN operating in Multi User Mode and desktop notifications are enabled THEN the system SHALL refuse to start with a clear error message.
9.2 WHEN the system refuses to start due to desktop notifications in Multi User Mode THEN the error message SHALL indicate that desktop notifications are only supported in Single User Mode.
9.3 WHEN the system refuses to start due to desktop notifications in Multi User Mode THEN the error message SHALL indicate that Multi User Mode is for dedicated servers, not desktop computers.
9.4 WHEN operating in Multi User Mode THEN the system SHALL validate the notification configuration before backend loading.
9.5 WHEN operating in Single User Mode THEN the system SHALL allow desktop notifications to be enabled or disabled.

#### Technical Constraints
- The validation shall check the `notifications.enabled` configuration value
- The validation shall occur early in the startup sequence
- Desktop notifications are controlled via `--enable-notifications`/`--disable-notifications` CLI flags or `LLM_PROXY_ENABLE_NOTIFICATIONS` environment variable

### Requirement 10: Configuration Persistence and Observability
**Objective:** As an operator, I want the access mode to be visible in configuration and logs, so that I can verify the proxy is running in the expected mode.

**Priority:** P1 (High)

#### Acceptance Criteria
10.1 WHEN the proxy starts THEN the system SHALL log the selected access mode at INFO level.
10.2 WHEN the proxy starts THEN the system SHALL include the access mode in the startup banner or summary.
10.3 WHEN querying the health endpoint THEN the system SHALL include the access mode in the response.
10.4 WHEN the access mode is Single User Mode THEN the system SHALL log the list of loaded OAuth connectors at DEBUG level.
10.5 WHEN the access mode is Multi User Mode THEN the system SHALL log the count of skipped OAuth connectors at INFO level.

#### Technical Constraints
- The access mode shall be stored in the application configuration model
- The access mode shall be accessible to health check and diagnostic endpoints

### Requirement 11: Error Messages and User Guidance
**Objective:** As an operator, I want clear error messages when startup validation fails, so that I can quickly correct configuration issues.

**Priority:** P1 (High)

#### Acceptance Criteria
11.1 WHEN startup validation fails THEN the system SHALL provide a clear error message indicating the specific validation failure.
11.2 WHEN startup validation fails THEN the system SHALL provide actionable guidance on how to resolve the issue.
11.3 WHEN startup validation fails due to access mode restrictions THEN the error message SHALL reference the relevant CLI flags and configuration options.
11.4 WHEN startup validation fails THEN the system SHALL exit with a non-zero exit code.

#### Technical Constraints
- Error messages shall be formatted for readability in terminal output
- Error messages shall not leak sensitive information (API keys, tokens)

### Requirement 12: Backward Compatibility
**Objective:** As an existing user, I want the proxy to continue working with my current configuration, so that I can upgrade without breaking changes.

**Priority:** P0 (Critical)

#### Acceptance Criteria
12.1 WHEN the proxy starts without any access mode flags THEN the system SHALL default to Single User Mode and SHALL behave identically to the current behavior.
12.2 WHEN existing configurations do not specify an access mode THEN the system SHALL apply Single User Mode defaults.
12.3 WHEN existing CLI invocations do not specify an access mode THEN the system SHALL apply Single User Mode defaults.
12.4 WHEN the proxy starts in Single User Mode THEN all existing features SHALL remain functional.

#### Technical Constraints
- The default behavior shall match the current proxy behavior exactly
- No breaking changes to existing CLI flags or configuration options

### Requirement 13: Documentation and Help Text
**Objective:** As a new user, I want clear documentation on access modes, so that I can choose the appropriate mode for my use case.

**Priority:** P1 (High)

#### Acceptance Criteria
13.1 WHEN running `--help` THEN the system SHALL display help text for `--single-user-mode` and `--multi-user-mode` flags.
13.2 WHEN running `--help` THEN the help text SHALL explain the differences between Single User Mode and Multi User Mode.
13.3 WHEN running `--help` THEN the help text SHALL indicate which mode is the default.
13.4 WHEN the proxy documentation is updated THEN it SHALL include a section on access modes with usage examples.

#### Technical Constraints
- Help text shall be concise and fit within standard terminal width
- Documentation shall include examples for both modes
