# Design Document: SSO Authentication

## Overview

This design describes the implementation of Single Sign-On (SSO) authentication for the LLM Proxy server. The system replaces static Bearer API keys with a secure, two-phase authentication model:

1. **SSO Authentication**: Users authenticate via OAuth2/OIDC with supported identity providers (Google, Microsoft, GitHub, LinkedIn, AWS IAM Identity Center)
2. **Authorization**: Access is granted via confirmation code (single-user mode) or external authorization API (enterprise mode)
3. **Agent Token**: Upon successful auth+authz, users receive a long-lived token to configure in their AI agents

The design prioritizes security (no token storage in plaintext, sandbox isolation, timing-attack resistance) while maintaining compatibility with stateless HTTP clients that only support Bearer token authentication.

**Note on SAML**: SAML support is not currently implemented. All supported identity providers use OAuth2/OIDC protocols. AWS IAM Identity Center is supported via its OIDC interface.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              LLM Proxy Server                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐    ┌──────────────────┐    ┌─────────────────────────┐   │
│  │   Request    │───>│  Auth Middleware │───>│   Request Router        │   │
│  │   Handler    │    │                  │    │   (normal proxy flow)   │   │
│  └──────────────┘    └────────┬─────────┘    └─────────────────────────┘   │
│                               │                                              │
│                               │ unauthenticated                              │
│                               v                                              │
│                      ┌──────────────────┐                                   │
│                      │  Sandbox Handler │──> Login Banner Response          │
│                      └──────────────────┘                                   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                        SSO Web Interface                              │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │  │
│  │  │  /auth/     │  │ /auth/      │  │ /auth/      │  │ /auth/      │ │  │
│  │  │  login      │  │ callback    │  │ confirm     │  │ success     │ │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘ │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                        Core Services                                  │  │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │  │
│  │  │  SSO Service    │  │  Token Service  │  │  Authorization      │  │  │
│  │  │  (authlib)      │  │  (Argon2id)     │  │  Service            │  │  │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                        Storage Layer                                  │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐ │  │
│  │  │                    SQLite Database                               │ │  │
│  │  │  - agent_tokens (hash, user_id, status, timestamps)             │ │  │
│  │  │  - pending_authorizations (sso_state, confirmation_code, etc.)  │ │  │
│  │  │  - rate_limits (ip, attempts, backoff_until)                    │ │  │
│  │  └─────────────────────────────────────────────────────────────────┘ │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ OAuth2/SAML
                                    v
                    ┌───────────────────────────────┐
                    │     Identity Providers        │
                    │  Google, Microsoft, GitHub,   │
                    │  LinkedIn, AWS IAM IC         │
                    └───────────────────────────────┘
```

### Authentication Flow Sequence

```
┌──────┐     ┌─────────┐     ┌──────────┐     ┌─────┐     ┌────────────┐
│Agent │     │  Proxy  │     │SSO WebUI │     │ IdP │     │ Auth API   │
└──┬───┘     └────┬────┘     └────┬─────┘     └──┬──┘     └─────┬──────┘
   │              │               │              │               │
   │ Request (no token)          │              │               │
   │─────────────>│               │              │               │
   │              │               │              │               │
   │ Sandbox Response (login URL)│              │               │
   │<─────────────│               │              │               │
   │              │               │              │               │
   │    User opens login URL in browser         │               │
   │──────────────────────────────>│             │               │
   │              │               │              │               │
   │              │               │ Redirect to IdP              │
   │              │               │─────────────>│               │
   │              │               │              │               │
   │              │               │ User authenticates           │
   │              │               │<─────────────│               │
   │              │               │              │               │
   │              │  [Single-user mode]         │               │
   │              │  Log confirmation code      │               │
   │              │<──────────────│              │               │
   │              │               │              │               │
   │              │  User enters code           │               │
   │              │───────────────>│             │               │
   │              │               │              │               │
   │              │  [Enterprise mode]          │               │
   │              │               │──────────────────────────────>│
   │              │               │              │  Query authz  │
   │              │               │<──────────────────────────────│
   │              │               │              │  Response     │
   │              │               │              │               │
   │              │  Generate token, show success page          │
   │              │<──────────────│              │               │
   │              │               │              │               │
   │ User copies token to agent config          │               │
   │              │               │              │               │
   │ Request (with valid token)  │              │               │
   │─────────────>│               │              │               │
   │              │               │              │               │
   │ Normal proxy response       │              │               │
   │<─────────────│               │              │               │
```

## Components and Interfaces

### 1. AuthMiddleware

Intercepts all incoming requests and determines authentication status.

```python
class AuthMiddleware:
    """Middleware that validates Bearer tokens and enforces authentication."""
    
    async def __call__(self, request: Request) -> Response | None:
        """
        Process incoming request for authentication.
        
        Returns:
            None if authenticated (continue to next handler)
            Response if unauthenticated (sandbox response)
        """
        pass
    
    def extract_bearer_token(self, request: Request) -> str | None:
        """Extract Bearer token from Authorization header."""
        pass
    
    async def validate_token(self, token: str) -> TokenValidationResult:
        """
        Validate token against stored hashes.
        
        Returns TokenValidationResult with:
            - is_valid: bool
            - user_id: str | None
            - is_authenticated: bool (SSO session active)
            - token_id: str | None (for session linking)
        """
        pass
    
    def detect_sandbox_history(self, messages: list[dict]) -> bool:
        """
        Check if conversation history contains sandbox login banner.
        Returns True if sandbox content detected (session must be rejected).
        """
        pass
```

### 2. SandboxHandler

Generates restricted responses for unauthenticated users.

```python
class SandboxHandler:
    """Handles requests from unauthenticated users."""
    
    def generate_login_banner(self, auth_url: str) -> dict:
        """
        Generate a chat completion response containing login instructions.
        
        The banner includes:
            - Welcome message
            - Authentication URL
            - Instructions to configure agent after auth
            - Note that session cannot continue after auth
        """
        pass
    
    def format_as_completion_response(self, message: str) -> dict:
        """Format message as OpenAI-compatible chat completion response."""
        pass
```

### 3. SSOService

Handles OAuth2 and SAML authentication flows using authlib.

```python
class SSOService:
    """Manages SSO authentication with identity providers."""
    
    def __init__(self, config: SSOConfig):
        """Initialize with IdP configuration."""
        pass
    
    async def create_authorization_url(self, provider: str, state: str) -> str:
        """Generate OAuth2/SAML authorization URL for the specified provider."""
        pass
    
    async def handle_callback(
        self, provider: str, code: str, state: str
    ) -> SSOResult:
        """
        Process OAuth2/SAML callback.
        
        Returns SSOResult with:
            - success: bool
            - user_id: str (email or unique ID)
            - user_email: str
            - provider: str
            - error: str | None
        """
        pass
    
    def get_enabled_providers(self) -> list[str]:
        """
        Return list of enabled and configured identity providers.
        
        A provider is included if:
        - It has valid configuration (client_id, client_secret, discovery_url)
        - It is not explicitly disabled (enabled: false)
        """
        pass
    
    def is_provider_enabled(self, provider: str) -> bool:
        """Check if a specific provider is enabled and configured."""
        pass
```

### 4. TokenService

Manages agent token generation, hashing, and verification.

```python
class TokenService:
    """Secure token generation and verification using Argon2id."""
    
    def generate_token(self) -> tuple[str, str]:
        """
        Generate a new agent token.
        
        Returns:
            (plaintext_token, token_hash)
            
        Token is 256-bit entropy, base64url encoded.
        Hash uses Argon2id with 2025-recommended parameters.
        """
        pass
    
    def verify_token(self, token: str, stored_hash: str) -> bool:
        """
        Verify token against stored hash using constant-time comparison.
        
        Returns True if token matches hash.
        """
        pass
    
    def hash_token(self, token: str) -> str:
        """Hash a token using Argon2id."""
        pass
```

### 5. AuthorizationService

Handles post-SSO authorization (confirmation code or API).

```python
class AuthorizationService:
    """Manages authorization after successful SSO authentication."""
    
    def __init__(self, mode: AuthorizationMode, config: AuthorizationConfig):
        """Initialize with authorization mode and configuration."""
        pass
    
    # Single-user mode methods
    def generate_confirmation_code(self) -> str:
        """Generate a 6-digit confirmation code."""
        pass
    
    def log_confirmation_request(self, user_email: str, code: str) -> None:
        """Log WARNING with user email and confirmation code."""
        pass
    
    async def verify_confirmation_code(
        self, session_id: str, code: str
    ) -> ConfirmationResult:
        """
        Verify user-entered confirmation code.
        
        Returns ConfirmationResult with:
            - success: bool
            - attempts_remaining: int
            - must_reauthenticate: bool
        """
        pass
    
    # Enterprise mode methods
    async def query_authorization_api(
        self, user_id: str, user_email: str, client_ip: str
    ) -> AuthorizationResult:
        """
        Query external authorization API.
        
        Returns AuthorizationResult with:
            - authorized: bool
            - error: str | None
        """
        pass
```

### 6. TokenRepository

Database operations for token storage.

```python
class TokenRepository:
    """SQLite repository for agent token storage."""
    
    async def initialize_schema(self) -> None:
        """Create or migrate database schema."""
        pass
    
    async def store_token(self, token_record: TokenRecord) -> None:
        """Store a new token record."""
        pass
    
    async def find_by_hash(self, token_hash: str) -> TokenRecord | None:
        """Find token record by hash (uses constant-time comparison)."""
        pass
    
    async def update_auth_status(
        self, token_id: str, authenticated: bool, expiry: datetime | None
    ) -> None:
        """Update authentication status for a token."""
        pass
    
    async def revoke_token(self, token_id: str) -> None:
        """Mark token as revoked (soft delete)."""
        pass
    
    async def get_all_token_hashes(self) -> list[str]:
        """Get all active token hashes for verification."""
        pass
```

### 7. RateLimitService

Manages brute-force protection for confirmation codes.

```python
class RateLimitService:
    """Rate limiting for confirmation code attempts."""
    
    async def check_rate_limit(self, identifier: str) -> RateLimitResult:
        """
        Check if identifier is rate limited.
        
        Returns RateLimitResult with:
            - allowed: bool
            - retry_after: int (seconds until retry allowed)
        """
        pass
    
    async def record_failed_attempt(self, identifier: str) -> None:
        """Record a failed attempt and update backoff."""
        pass
    
    async def reset_rate_limit(self, identifier: str) -> None:
        """Reset rate limit after successful authorization."""
        pass
```

## Data Models

### TokenRecord

```python
@dataclass
class TokenRecord:
    """Database record for an agent token."""
    
    id: str                          # UUID
    token_hash: str                  # Argon2id hash
    user_id: str                     # SSO user identifier
    user_email: str                  # User email from SSO
    provider: str                    # IdP that authenticated user
    is_authenticated: bool           # Current SSO session status
    is_active: bool                  # False if revoked
    created_at: datetime             # Token creation time
    last_authenticated_at: datetime  # Last successful SSO
    auth_expires_at: datetime | None # SSO session expiry
```

### PendingAuthorization

```python
@dataclass
class PendingAuthorization:
    """Tracks pending authorization requests (single-user mode)."""
    
    id: str                    # UUID
    sso_state: str             # OAuth2 state parameter
    user_email: str            # Email from SSO
    user_id: str               # User ID from SSO
    provider: str              # IdP name
    confirmation_code: str     # 6-digit code (hashed)
    attempts_remaining: int    # Starts at 3
    created_at: datetime       # Request creation time
    expires_at: datetime       # Code expiry (e.g., 10 minutes)
    client_ip: str             # For audit logging
```

### SSOConfig

```python
@dataclass
class SSOConfig:
    """Configuration for SSO authentication."""
    
    enabled: bool
    authorization_mode: Literal["single_user", "enterprise"]
    session_lifetime_hours: int  # How long SSO session is valid
    
    # OAuth2/OIDC providers
    providers: dict[str, ProviderConfig]
    
    # Enterprise mode
    authorization_api_url: str | None
    authorization_api_timeout: int  # seconds
    
    # Single-user mode
    confirmation_code_expiry_minutes: int
    max_confirmation_attempts: int
    
@dataclass
class ProviderConfig:
    """Configuration for a single identity provider."""
    
    type: Literal["oauth2", "saml"]
    enabled: bool                  # Default: True
    client_id: str
    client_secret: str
    discovery_url: str | None      # For OIDC
    metadata_url: str | None       # For SAML
    authorize_url: str | None      # Manual OAuth2
    token_url: str | None          # Manual OAuth2
    userinfo_url: str | None       # Manual OAuth2
    scopes: list[str]
```

### RateLimitRecord

```python
@dataclass
class RateLimitRecord:
    """Tracks rate limiting for brute-force protection."""
    
    identifier: str           # IP address or session ID
    failed_attempts: int      # Consecutive failures
    last_attempt_at: datetime # Last attempt timestamp
    blocked_until: datetime | None  # Exponential backoff
```

### Database Schema

```sql
-- Agent tokens table
CREATE TABLE agent_tokens (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    user_email TEXT NOT NULL,
    provider TEXT NOT NULL,
    is_authenticated INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_authenticated_at TEXT,
    auth_expires_at TEXT,
    
    INDEX idx_token_hash (token_hash),
    INDEX idx_user_id (user_id),
    INDEX idx_is_active (is_active)
);

-- Pending authorizations (single-user mode)
CREATE TABLE pending_authorizations (
    id TEXT PRIMARY KEY,
    sso_state TEXT NOT NULL UNIQUE,
    user_email TEXT NOT NULL,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    confirmation_code_hash TEXT NOT NULL,
    attempts_remaining INTEGER NOT NULL DEFAULT 3,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    client_ip TEXT NOT NULL,
    
    INDEX idx_sso_state (sso_state)
);

-- Rate limiting
CREATE TABLE rate_limits (
    identifier TEXT PRIMARY KEY,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT NOT NULL,
    blocked_until TEXT
);
```


## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: SSO Mode Activation

*For any* valid SSO configuration provided via CLI flag, environment variable, or config file, the proxy SHALL enter SSO authentication mode and require authentication for all requests.

**Validates: Requirements 1.1**

### Property 2: Legacy Auth Disabled in SSO Mode

*For any* request containing a legacy static Bearer key, when SSO mode is enabled, the proxy SHALL reject the request and return a sandbox response (legacy keys are not valid in SSO mode).

**Validates: Requirements 1.2**

### Property 3: Non-Loopback Startup Rejection

*For any* bind address that is not 127.0.0.1 or ::1, when no authentication mode is configured, the proxy SHALL reject startup with an error.

**Validates: Requirements 1.4**

### Property 4: Unauthenticated Request Sandbox Response

*For any* request without a valid Bearer token (missing, empty, or unknown token), the proxy SHALL return a sandbox response containing the login banner instead of processing the request.

**Validates: Requirements 2.1, 2.2, 2.3**

### Property 5: Sandbox Response Format Validity

*For any* sandbox response generated by the proxy, the response SHALL be a valid OpenAI-compatible chat completion response that can be parsed by standard clients.

**Validates: Requirements 2.4**

### Property 6: Token Generation Uniqueness

*For any* two successful authentication+authorization flows, the generated agent tokens SHALL be distinct (no collisions).

**Validates: Requirements 3.1**

### Property 7: Token Entropy Sufficiency

*For any* generated agent token, the token SHALL have at least 256 bits of entropy (minimum 43 characters in base64url encoding).

**Validates: Requirements 3.2**

### Property 8: Token Storage Security

*For any* agent token stored in the database, the stored value SHALL be a hash that does not equal the plaintext token and cannot be reversed to obtain the plaintext.

**Validates: Requirements 3.4**

### Property 9: Unknown Token Rejection

*For any* Bearer token that does not match any stored token hash, the proxy SHALL treat the request as unauthenticated and return a sandbox response.

**Validates: Requirements 4.1**

### Property 10: Token Response Indistinguishability

*For any* two invalid Bearer tokens (regardless of format, length, or content), the sandbox responses returned SHALL be identical in structure and timing characteristics.

**Validates: Requirements 4.2**

### Property 11: Argon2id Hash Format

*For any* token hash stored in the database, the hash SHALL conform to the Argon2id format with parameters meeting 2025 security recommendations (memory >= 64MB, iterations >= 3, parallelism >= 4).

**Validates: Requirements 4.4**

### Property 12: Re-authentication Status Update

*For any* existing agent token, when the associated user completes SSO re-authentication, the token's authentication status SHALL be updated to authenticated without generating a new token.

**Validates: Requirements 5.1, 5.3, 9.3**

### Property 13: Session Expiry Status Change

*For any* authenticated agent token, when the SSO session expiry time passes, the token's authentication status SHALL change to unauthenticated.

**Validates: Requirements 5.2**

### Property 14: Database Status Synchronization

*For any* authentication status change (authenticated to unauthenticated or vice versa), the SQLite database record SHALL be updated with the new status and a current timestamp.

**Validates: Requirements 5.4**

### Property 15: Confirmation Code Attempt Decrement

*For any* incorrect confirmation code entry in single-user mode, the remaining attempts counter SHALL decrease by exactly 1.

**Validates: Requirements 6.3**

### Property 16: Correct Confirmation Code Success

*For any* correct confirmation code entry in single-user mode, the proxy SHALL generate and return a valid agent token.

**Validates: Requirements 6.5**

### Property 17: Exponential Backoff Enforcement

*For any* sequence of N failed confirmation code attempts, the required wait time before the next SSO attempt SHALL increase exponentially (e.g., 2^N seconds, capped at a maximum).

**Validates: Requirements 6.6**

### Property 18: Authorization API Invocation

*For any* successful SSO authentication in enterprise mode, the proxy SHALL make exactly one HTTP request to the configured authorization API URL.

**Validates: Requirements 7.1**

### Property 19: Authorization API Request Payload

*For any* authorization API request, the request body SHALL contain the user's SSO identity (email or ID) and the client's IP address.

**Validates: Requirements 7.2**

### Property 20: Authorization API Success Path

*For any* authorization API response returning true/1, the proxy SHALL authorize the user and generate a valid agent token.

**Validates: Requirements 7.3**

### Property 21: Authorization API Denial Path

*For any* authorization API response returning false/0, the proxy SHALL deny access and return an "access denied" message without generating a token.

**Validates: Requirements 7.4**

### Property 22: Authorization API Error Handling

*For any* authorization API error (timeout, connection failure, non-2xx response, invalid response format), the proxy SHALL deny access and log the error.

**Validates: Requirements 7.5**

### Property 23: Token Record Completeness

*For any* token record stored in the database, the record SHALL contain all required fields: token hash, user identity, user email, provider, authentication status, active status, creation timestamp, and last authentication timestamp.

**Validates: Requirements 8.2**

### Property 24: Token Soft Delete

*For any* revoked or expired token, the database record SHALL be marked as inactive (is_active=false) rather than deleted.

**Validates: Requirements 8.5**

### Property 25: Expired Session Sandbox Response

*For any* request with a valid but expired agent token (SSO session expired), the proxy SHALL return a sandbox response containing the re-authentication URL.

**Validates: Requirements 9.1, 9.2**

### Property 26: Sandbox Session Isolation

*For any* request containing conversation history with a sandbox login banner message, the proxy SHALL reject the request and return a new sandbox response, regardless of the Bearer token's validity.

**Validates: Requirements 10.1, 10.2, 10.4, 10.5**

### Property 27: IdP Configuration Schema

*For any* supported identity provider configuration, the proxy SHALL accept standard OAuth2/OIDC/SAML parameters (client_id, client_secret, and either discovery_url or metadata_url) without requiring provider-specific fields.

**Validates: Requirements 12.6**

### Property 28: All Providers Displayed When Configured

*For any* SSO login page request, when all five supported providers (Google, Microsoft, GitHub, LinkedIn, AWS IAM Identity Center) have valid configurations and are not explicitly disabled, all five providers SHALL be displayed on the login page.

**Validates: Requirements 12.1, 12.2**

### Property 29: Provider Visibility Based on Configuration

*For any* identity provider without valid configuration (missing client_id, client_secret, or discovery_url), that provider SHALL NOT appear on the SSO login page.

**Validates: Requirements 12.4**

### Property 30: Explicit Disable Enforcement

*For any* identity provider with "enabled: false" in configuration, that provider SHALL NOT appear on the SSO login page regardless of whether credentials are configured.

**Validates: Requirements 12.5, 13.1**

### Property 31: Direct Access to Disabled Provider

*For any* HTTP request to a disabled provider's authentication endpoint, the proxy SHALL return an error response indicating the provider is disabled.

**Validates: Requirements 13.3**

### Property 32: At Least One Provider Required

*For any* SSO configuration where all providers are disabled or unconfigured, the proxy SHALL reject startup with an error message.

**Validates: Requirements 13.4**

## Error Handling

### Authentication Errors

| Error Condition | Response | HTTP Status | Logging |
|----------------|----------|-------------|---------|
| Missing Bearer token | Sandbox response | 200 | DEBUG |
| Unknown Bearer token | Sandbox response | 200 | DEBUG |
| Expired SSO session | Sandbox response with re-auth URL | 200 | INFO |
| Sandbox history detected | Sandbox response | 200 | DEBUG |

### SSO Flow Errors

| Error Condition | Response | HTTP Status | Logging |
|----------------|----------|-------------|---------|
| Invalid OAuth2 state | Error page | 400 | WARNING |
| IdP authentication failed | Error page | 401 | WARNING |
| IdP unreachable | Error page | 502 | ERROR |
| Invalid SAML assertion | Error page | 401 | WARNING |

### Authorization Errors

| Error Condition | Response | HTTP Status | Logging |
|----------------|----------|-------------|---------|
| Wrong confirmation code | Retry form with attempts remaining | 200 | INFO |
| Confirmation code exhausted | Re-authenticate page | 200 | WARNING |
| Rate limited | Wait page with retry time | 429 | WARNING |
| Authorization API denied | Access denied page | 403 | INFO |
| Authorization API error | Error page | 502 | ERROR |

### Database Errors

| Error Condition | Response | HTTP Status | Logging |
|----------------|----------|-------------|---------|
| Database connection failed | 500 error | 500 | CRITICAL |
| Schema migration failed | Startup failure | N/A | CRITICAL |
| Token storage failed | Error page | 500 | ERROR |

## Testing Strategy

### Unit Testing

Unit tests will cover:

1. **TokenService**: Token generation, hashing, and verification
2. **AuthMiddleware**: Token extraction, validation logic, sandbox history detection
3. **SandboxHandler**: Response formatting, banner content
4. **AuthorizationService**: Confirmation code generation/verification, backoff calculation
5. **RateLimitService**: Rate limit checking and recording
6. **Configuration parsing**: CLI, environment, and file config loading

### Property-Based Testing

Property-based tests will use the **Hypothesis** library for Python to verify correctness properties.

Each property-based test MUST:
- Run a minimum of 100 iterations
- Be tagged with a comment referencing the correctness property: `# Feature: sso-authentication, Property N: <property_text>`
- Use smart generators that constrain inputs to valid ranges

Key property tests:

1. **Token uniqueness**: Generate many tokens, verify no collisions
2. **Token entropy**: Verify generated tokens meet entropy requirements
3. **Hash security**: Verify stored hashes don't leak plaintext
4. **Sandbox response format**: Verify all sandbox responses are valid JSON
5. **Response indistinguishability**: Verify invalid token responses are identical
6. **Backoff calculation**: Verify exponential growth with various failure counts
7. **Sandbox isolation**: Verify history detection across various message patterns

### Integration Testing

Integration tests will cover:

1. **Full authentication flow**: SSO -> Authorization -> Token generation
2. **Re-authentication flow**: Expired session -> SSO -> Status update
3. **Database operations**: CRUD operations on token records
4. **IdP integration**: Mock OAuth2/SAML flows with test IdPs

### Test Fixtures

- Mock OAuth2 server for testing OAuth flows
- Mock SAML IdP for testing SAML flows
- Mock authorization API for enterprise mode testing
- Pre-populated SQLite database for token verification tests
