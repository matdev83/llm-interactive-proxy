# Requirements Document

## Introduction

This document specifies requirements for adding Single Sign-On (SSO) authentication support to the LLM Proxy server. The feature enables user authentication via OAuth2 and SAML protocols, replacing static Bearer API keys with a secure, enterprise-ready authentication flow. The system uses long-lived device tokens (agent tokens) combined with short-lived SSO sessions to provide seamless authentication for AI coding agents that lack cookie/session support.

## Glossary

- **Agent Token**: A long-lived, server-generated unique identifier that acts as a "device ID" for an AI coding agent. Stored in agent configuration as a Bearer token.
- **SSO**: Single Sign-On - authentication mechanism allowing users to authenticate once with an identity provider.
- **OAuth2**: Open standard authorization protocol enabling secure delegated access.
- **SAML**: Security Assertion Markup Language - XML-based standard for exchanging authentication data.
- **IdP**: Identity Provider - the external service that authenticates users (e.g., Okta, Azure AD, Google).
- **Sandbox Mode**: Restricted proxy state where unauthenticated users receive only a login banner message.
- **Authorization API**: External HTTP endpoint that determines if an authenticated user is permitted to use the proxy.
- **Confirmation Code**: A one-time code displayed in server logs for single-user mode authorization.
- **Authlib**: Python library for OAuth and OpenID Connect client and server implementations.
- **Supported IdPs**: Google, Microsoft (Azure AD/Entra ID), GitHub, LinkedIn, AWS IAM Identity Center (formerly AWS SSO).

## Requirements

### Requirement 1

**User Story:** As a proxy administrator, I want to enable SSO authentication mode, so that users must authenticate via corporate identity providers instead of using static API keys.

#### Acceptance Criteria

1. WHEN the proxy starts with SSO authentication enabled via CLI flag, environment variable, or config file THEN the Proxy SHALL require SSO authentication for all incoming requests.
2. WHEN SSO mode is enabled THEN the Proxy SHALL disable the legacy static Bearer key authentication mechanism.
3. WHEN no authentication mode is configured AND the proxy binds to 127.0.0.1 THEN the Proxy SHALL allow unauthenticated access.
4. WHEN no authentication mode is configured AND the proxy binds to a non-loopback address THEN the Proxy SHALL reject startup and log an error message.
5. WHEN SSO mode is enabled THEN the Proxy SHALL support both OAuth2 and SAML protocols for identity provider integration.

### Requirement 2

**User Story:** As an unauthenticated user, I want to receive clear instructions on how to authenticate, so that I can complete the SSO process and use the proxy.

#### Acceptance Criteria

1. WHEN an unauthenticated request arrives (no token or unknown token) THEN the Proxy SHALL return a sandbox response containing only an authentication URL and instructions.
2. WHEN a user sends a chat completion request without valid authentication THEN the Proxy SHALL return the login banner message instead of routing to inference backends.
3. WHEN a user attempts any proxy feature (interactive commands, model listing, etc.) without valid authentication THEN the Proxy SHALL return the login banner message.
4. WHEN the sandbox response is generated THEN the Proxy SHALL format it as a valid chat completion response to maintain agent compatibility.

### Requirement 3

**User Story:** As a user, I want to authenticate once and receive a long-lived agent token, so that I do not need to reconfigure my AI agent frequently.

#### Acceptance Criteria

1. WHEN a user completes SSO authentication AND passes authorization (confirmation code in single-user mode OR authorization API approval in enterprise mode) THEN the Proxy SHALL generate a unique agent token.
2. WHEN generating an agent token THEN the Proxy SHALL use cryptographically secure random generation with sufficient entropy (minimum 256 bits).
3. WHEN an agent token is generated THEN the Proxy SHALL display a success page containing: the plaintext token, clear instructions to copy it to the agent's API key configuration field, and a note that this token will not be shown again.
4. WHEN an agent token is generated THEN the Proxy SHALL store a salted hash of the token in the SQLite database (not the plaintext token).
5. WHEN a user provides a Bearer token THEN the Proxy SHALL verify it against stored hashes using constant-time comparison.
6. WHEN displaying the agent token THEN the Proxy SHALL provide a "copy to clipboard" button for user convenience.

### Requirement 4

**User Story:** As a security administrator, I want the proxy to reject arbitrary Bearer tokens, so that attackers cannot use fabricated tokens to probe the system.

#### Acceptance Criteria

1. WHEN a request contains a Bearer token not matching any stored hash THEN the Proxy SHALL treat it as unauthenticated and return the sandbox response.
2. WHEN an unknown Bearer token is received THEN the Proxy SHALL NOT provide any indication whether the token format is valid or invalid.
3. WHEN a user attempts to authenticate with an unknown token THEN the Proxy SHALL require the user to clear the token and perform SSO with no Bearer token.
4. WHEN storing token hashes THEN the Proxy SHALL use Argon2id hashing algorithm with recommended parameters for 2025 security standards.

### Requirement 5

**User Story:** As a user, I want my SSO session to be linked to my agent token, so that I can re-authenticate without reconfiguring my agent.

#### Acceptance Criteria

1. WHEN a user with an existing agent token completes SSO THEN the Proxy SHALL update the authentication status for that token.
2. WHEN an SSO session expires THEN the Proxy SHALL mark the associated agent token as unauthenticated.
3. WHEN a user with an unauthenticated token completes SSO THEN the Proxy SHALL restore authenticated status without generating a new token.
4. WHEN authentication status changes THEN the Proxy SHALL update the SQLite database record with the new status and timestamp.

### Requirement 6

**User Story:** As a single-user/open-source deployer, I want a simple authorization mechanism, so that I can control access without setting up external authorization infrastructure.

#### Acceptance Criteria

1. WHEN single-user authorization mode is enabled AND a user completes SSO THEN the Proxy SHALL log a WARNING message containing the user email and a confirmation code.
2. WHEN the confirmation code prompt is displayed THEN the Proxy SHALL show a form requesting the code from server console.
3. WHEN a user enters an incorrect confirmation code THEN the Proxy SHALL decrement the remaining attempts counter.
4. WHEN a user exhausts confirmation code attempts (maximum 3) THEN the Proxy SHALL require a new SSO authentication.
5. WHEN a user enters the correct confirmation code THEN the Proxy SHALL generate and display the agent token.
6. WHEN confirmation code attempts fail repeatedly THEN the Proxy SHALL enforce an increasing grace period between SSO attempts (exponential backoff).

### Requirement 7

**User Story:** As an enterprise administrator, I want to integrate with our internal authorization API, so that access control follows our organization's policies.

#### Acceptance Criteria

1. WHEN enterprise authorization mode is enabled THEN the Proxy SHALL query the configured authorization API URL after successful SSO.
2. WHEN querying the authorization API THEN the Proxy SHALL send the user's SSO identity (email or ID) and client IP address.
3. WHEN the authorization API returns true/1 THEN the Proxy SHALL authorize the user and generate/activate the agent token.
4. WHEN the authorization API returns false/0 THEN the Proxy SHALL deny access and display an "access denied" message.
5. WHEN the authorization API is unreachable or returns an error THEN the Proxy SHALL deny access and log the error.
6. WHEN enterprise mode is configured THEN the Proxy SHALL provide an example authorization API script for testing purposes.

### Requirement 8

**User Story:** As a proxy administrator, I want secure token storage, so that compromised database contents do not expose valid tokens.

#### Acceptance Criteria

1. WHEN the proxy initializes THEN the Proxy SHALL create or migrate the SQLite database schema for token storage.
2. WHEN storing a token record THEN the Proxy SHALL store: token hash, salt, user identity, authentication status, creation timestamp, last authentication timestamp, and expiration timestamp.
3. WHEN the database file is accessed THEN the Proxy SHALL set restrictive file permissions (owner read/write only).
4. WHEN token verification occurs THEN the Proxy SHALL use constant-time comparison to prevent timing attacks.
5. WHEN a token is revoked or expires THEN the Proxy SHALL mark it as inactive rather than deleting the record (for audit purposes).

### Requirement 9

**User Story:** As a user, I want to initiate re-authentication easily, so that I can restore access when my SSO session expires.

#### Acceptance Criteria

1. WHEN an authenticated token's SSO session expires THEN the Proxy SHALL return a sandbox response with re-authentication instructions.
2. WHEN re-authentication is needed THEN the Proxy SHALL include the authentication URL in the sandbox response.
3. WHEN a user completes re-authentication THEN the Proxy SHALL restore access using the existing agent token.
4. WHEN displaying re-authentication instructions THEN the Proxy SHALL indicate that no agent reconfiguration is needed.

### Requirement 10

**User Story:** As a security administrator, I want sandbox sessions to be completely isolated, so that authentication state cannot leak into unauthenticated conversations.

#### Acceptance Criteria

1. WHEN a user completes SSO authentication and authorization THEN the Proxy SHALL NOT continue the session that was started in sandbox mode.
2. WHEN a sandbox response (login banner) exists in the conversation history THEN the Proxy SHALL reject the request and return a new sandbox response.
3. WHEN the sandbox login banner is displayed THEN the Proxy SHALL include instructions stating that after successful authentication the user must configure their agent with the new Bearer token.
4. WHEN authentication succeeds THEN the Proxy SHALL NOT provide authentication results, status, or instructions within the sandboxed session context.
5. WHEN a user attempts to continue a sandboxed session after authentication THEN the Proxy SHALL treat it as a new unauthenticated request.

### Requirement 11

**User Story:** As a developer integrating with the proxy, I want the SSO flow to work with the authlib library, so that we use a well-maintained and secure implementation.

#### Acceptance Criteria

1. WHEN implementing OAuth2 client functionality THEN the Proxy SHALL use the authlib library.
2. WHEN implementing SAML client functionality THEN the Proxy SHALL use the authlib library or a compatible SAML library.
3. WHEN configuring SSO providers THEN the Proxy SHALL support standard OAuth2/OIDC discovery endpoints.
4. WHEN handling SSO callbacks THEN the Proxy SHALL validate all tokens and assertions according to protocol specifications.

### Requirement 12

**User Story:** As a proxy administrator, I want all popular identity providers enabled by default on the SSO authentication page, so that users can choose their preferred provider without additional configuration.

#### Acceptance Criteria

1. WHEN SSO authentication mode is enabled THEN the Proxy SHALL display all supported identity providers on the login page: Google, Microsoft (Azure AD/Entra ID), GitHub, LinkedIn, and AWS IAM Identity Center.
2. WHEN a user accesses the SSO login page THEN the Proxy SHALL show clickable buttons or links for each enabled identity provider.
3. WHEN an administrator provides configuration for a specific IdP (client ID, client secret, discovery URL) THEN the Proxy SHALL enable that provider for authentication.
4. WHEN an administrator does not provide configuration for a specific IdP THEN the Proxy SHALL hide that provider from the login page.
5. WHEN an administrator explicitly disables a provider via configuration THEN the Proxy SHALL hide that provider from the login page even if credentials are configured.
6. WHEN configuring any supported IdP THEN the Proxy SHALL require only standard OAuth2/OIDC parameters (client ID, client secret, and discovery URL or authorize/token/userinfo URLs).

### Requirement 13

**User Story:** As a proxy administrator, I want to selectively disable specific SSO providers, so that I can restrict authentication methods according to organizational policies.

#### Acceptance Criteria

1. WHEN the configuration file contains a provider with "enabled: false" THEN the Proxy SHALL exclude that provider from the login page.
2. WHEN the configuration file contains a provider with "enabled: true" or no enabled field THEN the Proxy SHALL include that provider on the login page (if credentials are configured).
3. WHEN a disabled provider's authentication URL is accessed directly THEN the Proxy SHALL return an error indicating the provider is disabled.
4. WHEN all providers are disabled THEN the Proxy SHALL reject startup with an error message indicating at least one provider must be enabled.
5. WHEN the configuration is reloaded THEN the Proxy SHALL update the list of available providers on the login page without requiring a restart.
