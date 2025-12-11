# Implementation Plan

- [x] 1. Set up project structure and dependencies

  - [x] 1.1 Add authlib and argon2-cffi dependencies to pyproject.toml

    - Add `authlib>=1.3.0` for OAuth2/SAML support
    - Add `argon2-cffi>=23.1.0` for secure password hashing
    - Add `aiosqlite>=0.19.0` for async SQLite operations
    - _Requirements: 11.1, 11.2_

  - [x] 1.2 Create SSO authentication module structure

    - Create `src/core/auth/sso/` directory
    - Create `__init__.py`, `config.py`, `models.py`, `exceptions.py`
    - _Requirements: 1.1_

- [x] 2. Implement configuration and data models

  - [x] 2.1 Create SSO configuration models

    - Implement `SSOConfig`, `ProviderConfig`, `AuthorizationConfig` dataclasses
    - Support CLI flag, environment variable, and config file loading
    - _Requirements: 1.1, 12.6_
  - [x] 2.2 Write property test for IdP configuration schema

    - **Property 27: IdP Configuration Schema**
    - **Validates: Requirements 12.6**
  - [x] 2.3 Create token and authorization data models

    - Implement `TokenRecord`, `PendingAuthorization`, `RateLimitRecord` dataclasses
    - _Requirements: 8.2_
  - [x] 2.4 Write property test for token record completeness

    - **Property 23: Token Record Completeness**
    - **Validates: Requirements 8.2**

- [x] 3. Implement SQLite database layer

  - [x] 3.1 Create database schema and migrations

    - Implement `agent_tokens`, `pending_authorizations`, `rate_limits` tables
    - Set restrictive file permissions on database file
    - _Requirements: 8.1, 8.3_
  - [x] 3.2 Implement TokenRepository

    - Implement `store_token`, `find_by_hash`, `update_auth_status`, `revoke_token`
    - Use constant-time comparison for hash lookups
    - _Requirements: 3.5, 8.4_
  - [x] 3.3 Write property test for token soft delete

    - **Property 24: Token Soft Delete**
    - **Validates: Requirements 8.5**
  - [x] 3.4 Write property test for database status synchronization
    - **Property 14: Database Status Synchronization**
    - **Validates: Requirements 5.4**

- [x] 4. Implement TokenService with Argon2id hashing

  - [x] 4.1 Implement secure token generation

    - Generate 256-bit entropy tokens using `secrets` module
    - Encode as base64url for Bearer token compatibility
    - _Requirements: 3.2_
  - [x] 4.2 Write property test for token entropy sufficiency

    - **Property 7: Token Entropy Sufficiency**
    - **Validates: Requirements 3.2**
  - [x] 4.3 Implement Argon2id hashing and verification

    - Use recommended 2025 parameters (memory >= 64MB, iterations >= 3, parallelism >= 4)
    - Implement constant-time verification
    - _Requirements: 4.4, 3.5_
  - [x] 4.4 Write property test for Argon2id hash format

    - **Property 11: Argon2id Hash Format**
    - **Validates: Requirements 4.4**
  - [x] 4.5 Write property test for token storage security

    - **Property 8: Token Storage Security**
    - **Validates: Requirements 3.4**
  - [x] 4.6 Write property test for token generation uniqueness

    - **Property 6: Token Generation Uniqueness**
    - **Validates: Requirements 3.1**

- [x] 5. Checkpoint - Ensure all tests pass

  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement SandboxHandler

  - [x] 6.1 Implement login banner generation

    - Create sandbox response with auth URL and instructions
    - Include note about configuring agent with Bearer token after auth
    - _Requirements: 2.1, 10.3_
  - [x] 6.2 Implement OpenAI-compatible response formatting

    - Format sandbox message as valid chat completion response
    - Ensure compatibility with standard clients
    - _Requirements: 2.4_
  - [x] 6.3 Write property test for sandbox response format validity

    - **Property 5: Sandbox Response Format Validity**
    - **Validates: Requirements 2.4**
  - [x] 6.4 Implement sandbox history detection

    - Detect login banner in conversation history
    - Return True if sandbox content found
    - _Requirements: 10.2_
  - [x] 6.5 Write property test for sandbox session isolation

    - **Property 26: Sandbox Session Isolation**
    - **Validates: Requirements 10.1, 10.2, 10.4, 10.5**

- [x] 7. Implement AuthMiddleware

  - [x] 7.1 Implement Bearer token extraction

    - Extract token from Authorization header
    - Handle missing/malformed headers gracefully
    - _Requirements: 2.1_
  - [x] 7.2 Implement token validation logic

    - Verify token against stored hashes
    - Check authentication status and expiry
    - _Requirements: 3.5, 4.1_
  - [x] 7.3 Write property test for unauthenticated request sandbox response

    - **Property 4: Unauthenticated Request Sandbox Response**
    - **Validates: Requirements 2.1, 2.2, 2.3**
  - [x] 7.4 Write property test for unknown token rejection

    - **Property 9: Unknown Token Rejection**
    - **Validates: Requirements 4.1**
  - [x] 7.5 Write property test for token response indistinguishability

    - **Property 10: Token Response Indistinguishability**
    - **Validates: Requirements 4.2**
  - [x] 7.6 Implement session expiry handling

    - Check auth_expires_at timestamp
    - Return sandbox with re-auth URL for expired sessions
    - _Requirements: 5.2, 9.1_
  - [x] 7.7 Write property test for expired session sandbox response

    - **Property 25: Expired Session Sandbox Response**
    - **Validates: Requirements 9.1, 9.2**
  - [x] 7.8 Write property test for session expiry status change

    - **Property 13: Session Expiry Status Change**
    - **Validates: Requirements 5.2**

- [x] 8. Checkpoint - Ensure all tests pass

  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Implement RateLimitService

  - [x] 9.1 Implement rate limit checking and recording

    - Track failed attempts per identifier
    - Calculate exponential backoff
    - _Requirements: 6.6_
  - [x] 9.2 Write property test for exponential backoff enforcement

    - **Property 17: Exponential Backoff Enforcement**
    - **Validates: Requirements 6.6**

- [x] 10. Implement AuthorizationService (Single-User Mode)

  - [x] 10.1 Implement confirmation code generation
    - Generate 6-digit codes using secure random
    - Hash codes before storage
    - _Requirements: 6.1_
  - [x] 10.2 Implement confirmation code logging
    - Log WARNING with user email and code
    - _Requirements: 6.1_
  - [x] 10.3 Implement confirmation code verification
    - Verify code, decrement attempts on failure
    - Require re-auth after 3 failures
    - _Requirements: 6.3, 6.4, 6.5_
  - [x] 10.4 Write property test for confirmation code attempt decrement
    - **Property 15: Confirmation Code Attempt Decrement**
    - **Validates: Requirements 6.3**
  - [x] 10.5 Write property test for correct confirmation code success
    - **Property 16: Correct Confirmation Code Success**
    - **Validates: Requirements 6.5**

- [x] 11. Implement AuthorizationService (Enterprise Mode)

  - [x] 11.1 Implement authorization API client

    - Send POST request with user identity and IP
    - Handle timeouts and errors
    - _Requirements: 7.1, 7.2_
  - [x] 11.2 Write property test for authorization API invocation

    - **Property 18: Authorization API Invocation**
    - **Validates: Requirements 7.1**
  - [x] 11.3 Write property test for authorization API request payload

    - **Property 19: Authorization API Request Payload**
    - **Validates: Requirements 7.2**
  - [x] 11.4 Implement authorization API response handling

    - Handle true/false responses
    - Handle errors and timeouts
    - _Requirements: 7.3, 7.4, 7.5_
  - [x] 11.5 Write property test for authorization API success path

    - **Property 20: Authorization API Success Path**
    - **Validates: Requirements 7.3**
  - [x] 11.6 Write property test for authorization API denial path

    - **Property 21: Authorization API Denial Path**
    - **Validates: Requirements 7.4**
  - [x] 11.7 Write property test for authorization API error handling

    - **Property 22: Authorization API Error Handling**
    - **Validates: Requirements 7.5**
  - [x] 11.8 Create example authorization API script

    - Simple Flask/FastAPI script for testing
    - Document usage in README
    - _Requirements: 7.6_

- [x] 12. Checkpoint - Ensure all tests pass

  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Implement SSOService with authlib

  - [x] 13.1 Implement OAuth2 client setup

    - Configure authlib OAuth2 client
    - Support OIDC discovery endpoints
    - _Requirements: 11.1, 11.3_
  - [x] 13.2 Implement authorization URL generation

    - Generate state parameter
    - Build authorization URL for configured provider
    - _Requirements: 11.3_
  - [x] 13.3 Implement OAuth2 callback handling

    - Exchange code for tokens
    - Extract user identity from ID token or userinfo
    - _Requirements: 11.4_
  - [x] 13.4 Implement ID token signature verification using JWKS

    - Fetch JWKS from provider's jwks_uri endpoint
    - Verify ID token signatures with caching
    - Fall back to unverified decode if JWKS unavailable
    - _Requirements: 11.4_
  - [x] 13.5 SAML support (deferred)

    - Note: SAML support is not currently implemented
    - All supported IdPs use OAuth2/OIDC protocols
    - AWS IAM Identity Center is supported via OIDC interface
    - _Requirements: 11.2 (partial)_

- [x] 14. Implement IdP-specific configurations and provider selection

  - [x] 14.1 Add Google OAuth2/OIDC configuration
    - Factory function `create_google_config()` in `idp_configs.py`
    - Configure discovery URL and scopes
    - _Requirements: 12.1_
  - [x] 14.2 Add Microsoft Azure AD/Entra ID configuration
    - Factory function `create_microsoft_config()` in `idp_configs.py`
    - Configure discovery URL and scopes with tenant support
    - _Requirements: 12.1_
  - [x] 14.3 Add GitHub OAuth2 configuration
    - Factory function `create_github_config()` in `idp_configs.py`
    - Configure authorize/token/userinfo URLs
    - _Requirements: 12.1_
  - [x] 14.4 Add LinkedIn OAuth2 configuration
    - Factory function `create_linkedin_config()` in `idp_configs.py`
    - Configure authorize/token/userinfo URLs
    - _Requirements: 12.1_
  - [x] 14.5 Add AWS IAM Identity Center configuration
    - Factory function `create_aws_iam_identity_center_config()` in `idp_configs.py`
    - Configure OIDC endpoints with region support
    - _Requirements: 12.1_
  - [x] 14.6 Implement provider visibility logic

    - Check if provider has valid configuration (client_id, client_secret, discovery_url)
    - Check if provider is not explicitly disabled (enabled: false)
    - Return list of enabled providers for login page
    - _Requirements: 12.3, 12.4, 12.5_
  - [x] 14.7 Write property test for all providers displayed when configured

    - **Property 28: All Providers Displayed When Configured**
    - **Validates: Requirements 12.1, 12.2**
  - [x] 14.8 Write property test for provider visibility based on configuration

    - **Property 29: Provider Visibility Based on Configuration**
    - **Validates: Requirements 12.4**
  - [x] 14.9 Write property test for explicit disable enforcement

    - **Property 30: Explicit Disable Enforcement**
    - **Validates: Requirements 12.5, 13.1**
  - [x] 14.10 Implement startup validation for at least one provider

    - Reject startup if all providers are disabled or unconfigured
    - _Requirements: 13.4_
  - [x] 14.11 Write property test for at least one provider required

    - **Property 32: At Least One Provider Required**
    - **Validates: Requirements 13.4**

- [x] 15. Implement SSO Web Interface

  - [x] 15.1 Create /auth/login endpoint
    - Display all enabled providers as clickable buttons/links
    - Query SSOService.get_enabled_providers() to get list
    - Show provider name and icon for each enabled provider
    - Supports optional captcha verification (Cloudflare Turnstile)
    - _Requirements: 12.1, 12.2_
  - [x] 15.2 Implement provider-specific authentication initiation
    - Handle clicks on provider buttons
    - Redirect to provider's authorization URL
    - _Requirements: 12.1_
  - [x] 15.3 Implement disabled provider error handling
    - Return error if user tries to access disabled provider directly
    - _Requirements: 13.3_
  - [x] 15.4 Write property test for direct access to disabled provider
    - **Property 31: Direct Access to Disabled Provider**
    - **Validates: Requirements 13.3**
  - [x] 15.5 Create /auth/callback endpoint
    - Handle OAuth2 callbacks
    - Initiate authorization flow
    - _Requirements: 11.4_
  - [x] 15.6 Create /auth/confirm endpoint (single-user mode)
    - Display confirmation code form
    - Handle code submission
    - _Requirements: 6.2_
  - [x] 15.7 Create /auth/success endpoint
    - Display generated token with copy button
    - Show instructions for agent configuration
    - _Requirements: 3.3, 3.6_

- [x] 16. Implement startup validation and mode switching

  - [x] 16.1 Implement authentication mode detection
    - Check CLI flags, environment variables, config file
    - Determine SSO vs no-auth mode
    - _Requirements: 1.1_
  - [x] 16.2 Write property test for SSO mode activation
    - **Property 1: SSO Mode Activation**
    - **Validates: Requirements 1.1**
  - [x] 16.3 Implement legacy auth disabling in SSO mode
    - Reject static Bearer keys when SSO enabled
    - _Requirements: 1.2_
  - [x] 16.4 Write property test for legacy auth disabled in SSO mode
    - **Property 2: Legacy Auth Disabled in SSO Mode**
    - **Validates: Requirements 1.2**
  - [x] 16.5 Implement non-loopback startup validation
    - Reject startup on non-loopback without auth
    - _Requirements: 1.4_
  - [x] 16.6 Write property test for non-loopback startup rejection
    - **Property 3: Non-Loopback Startup Rejection**
    - **Validates: Requirements 1.4**

- [x] 17. Implement re-authentication flow

  - [x] 17.1 Implement token status update on re-auth
    - Update existing token's auth status
    - Do not generate new token
    - _Requirements: 5.1, 5.3_
  - [x] 17.2 Write property test for re-authentication status update
    - **Property 12: Re-authentication Status Update**
    - **Validates: Requirements 5.1, 5.3, 9.3**

- [x] 18. Integrate SSO authentication into proxy request flow

  - [x] 18.1 Add AuthMiddleware to request processing pipeline

    - Insert before existing request handlers
    - _Requirements: 2.1, 2.2, 2.3_
  - [x] 18.2 Update proxy configuration to support SSO settings

    - Add SSO config section to config file schema
    - _Requirements: 1.1_
  - [x] 18.3 Add CLI flags for SSO mode

    - Add `--sso-enabled`, `--sso-provider`, `--sso-auth-mode` flags
    - _Requirements: 1.1_

- [x] 19. Final Checkpoint - Ensure all tests pass

  - Ensure all tests pass, ask the user if questions arise.

- [x] 20. Write integration tests

  - [x] 20.1 Write integration test for full authentication flow

    - Test SSO -> Authorization -> Token generation
    - _Requirements: 1.1, 3.1, 6.5, 7.3_
  - [x] 20.2 Write integration test for re-authentication flow

    - Test expired session -> SSO -> Status update
    - _Requirements: 5.1, 5.3, 9.3_
  - [x] 20.3 Write integration test for sandbox isolation

    - Test that sandbox sessions cannot continue after auth
    - _Requirements: 10.1, 10.2_

- [x] 21. Create user documentation

  - [x] 21.1 Create SSO authentication overview documentation

    - Create `docs/user_guide/sso-authentication.md`
    - Document the authentication flow and concepts
    - Explain agent token vs SSO session distinction
    - _Requirements: 1.1, 3.1_
  - [x] 21.2 Document SSO configuration options

    - Document CLI flags, environment variables, and config file options
    - See `docs/user_guide/sso-configuration.md`
    - Provide example configurations for each method
    - Document how to enable/disable specific providers
    - Explain that all configured providers are enabled by default
    - _Requirements: 1.1, 12.6, 13.1, 13.2_
  - [x] 21.3 Document identity provider setup guides

    - See `docs/user_guide/sso-idp-setup.md`
    - See `docs/user_guide/sso-idp-overview.md`
    - Document setup for all five providers (Google, Microsoft, GitHub, LinkedIn, AWS)
    - Document how to disable specific providers if needed
    - _Requirements: 12.1, 12.2, 13.1, 13.2_
  - [x] 21.4 Document single-user authorization mode

    - Explain confirmation code flow
    - Document server console interaction
    - Provide troubleshooting tips
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_
  - [x] 21.5 Document enterprise authorization mode

    - Explain authorization API integration
    - Document API request/response format
    - Provide example authorization API implementations
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_
  - [x] 21.6 Document agent configuration guide

    - See `docs/user_guide/sso-agent-setup.md`
    - Explain how to configure popular AI agents with proxy tokens
    - Include examples for Cursor, Continue, Cline, and other agents
    - Document token management best practices
    - _Requirements: 3.3, 3.6_
  - [x] 21.7 Document security considerations

    - See `docs/user_guide/sso-security.md`
    - Explain token storage security (Argon2id)
    - Document sandbox isolation behavior
    - Explain rate limiting and brute-force protection
    - _Requirements: 4.4, 8.2, 8.3, 10.1, 10.2_
  - [x] 21.8 Document troubleshooting guide

    - See `docs/user_guide/sso-troubleshooting.md`
    - Common SSO configuration issues
    - Token expiry and re-authentication
    - Authorization API debugging
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

- [x] 22. Create unit tests for core components

  - [x] 22.1 Write unit tests for TokenService

    - Test token generation
    - Test hashing and verification
    - Test edge cases (empty input, special characters)
    - _Requirements: 3.1, 3.2, 4.4_
  - [x] 22.2 Write unit tests for SandboxHandler

    - Test login banner generation
    - Test response formatting
    - Test history detection
    - _Requirements: 2.1, 2.4, 10.2_
  - [x] 22.3 Write unit tests for AuthMiddleware

    - Test token extraction
    - Test validation logic
    - Test expiry handling
    - _Requirements: 2.1, 3.5, 5.2_
  - [x] 22.4 Write unit tests for AuthorizationService

    - Test confirmation code generation and verification
    - Test authorization API client
    - Test error handling
    - _Requirements: 6.1, 6.3, 7.1, 7.5_
  - [x] 22.5 Write unit tests for RateLimitService

    - Test rate limit checking
    - Test backoff calculation
    - Test reset functionality
    - _Requirements: 6.6_
  - [x] 22.6 Write unit tests for TokenRepository

    - Test CRUD operations
    - Test hash lookups
    - Test status updates
    - _Requirements: 8.2, 8.4, 8.5_
  - [x] 22.7 Write unit tests for configuration loading

    - Test CLI flag parsing
    - Test environment variable loading
    - Test config file parsing
    - _Requirements: 1.1, 12.6_

## Implementation Notes

### SAML Support

SAML support is intentionally not implemented. The design document notes: "Note on SAML: SAML support is not currently implemented. All supported identity providers use OAuth2/OIDC protocols. AWS IAM Identity Center is supported via its OIDC interface."

### Configuration Hot Reload

Configuration hot reload (Requirement 13.5) is not implemented. Server restart is required to update SSO provider configurations. This is documented as a known limitation.

### ID Token Signature Verification

ID token signature verification using JWKS is implemented with the following features:
- JWKS caching (1 hour TTL) to avoid fetching on every request
- Falls back to unverified decoding for non-OIDC providers without JWKS
- Supports RS256, RS384, RS512, ES256, ES384, ES512 algorithms
