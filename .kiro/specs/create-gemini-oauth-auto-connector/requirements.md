# Requirements Document

## Introduction

**Feature**: Create Gemini OAuth Auto-Connector (`gemini-oauth-auto`)

This feature introduces a new backend connector in the `gemini-oauth*` family that autonomously handles OAuth2 authentication with Google's Gemini API. Unlike existing connectors (`gemini-oauth-free`, `gemini-oauth-plan`) which depend on the external `gemini-cli` application to manage and refresh tokens, this connector will:

1. **Self-contained OAuth2 flow**: Handle the complete OAuth2 authorization code flow, including token refresh, without external dependencies.
2. **Multi-account support**: Store and manage credentials for multiple Google accounts simultaneously.
3. **Local credential storage**: Persist OAuth tokens securely within the project's `var/` directory.
4. **Standalone account management script**: Provide a dedicated script in `scripts/` for managing stored accounts (list, add, update, remove).

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:

- Developers integrating LLM capabilities via unified API who want streamlined Google Gemini authentication
- Operators managing backend configurations who need multi-account flexibility
- End-users who want to use their personal Google accounts without installing `gemini-cli`

---

## Technical Context (from Gap Analysis)

### OAuth Configuration (from gemini-cli reference implementation)

The following OAuth parameters are derived from the official gemini-cli implementation and are approved for use in installed/desktop applications per Google's OAuth2 documentation:

| Parameter | Value |
|-----------|-------|
| **Client ID** | `[REDACTED]...apps.googleusercontent.com` |
| **Client Secret** | `[REDACTED]` |
| **Auth URL** | `https://accounts.google.com/o/oauth2/v2/auth` |
| **Token URL** | `https://oauth2.googleapis.com/token` |
| **User Info URL** | `https://www.googleapis.com/oauth2/v2/userinfo` |

### OAuth Scopes

| Scope | Purpose |
|-------|---------|
| `https://www.googleapis.com/auth/cloud-platform` | Access to Google Cloud Platform APIs (required for Gemini) |
| `https://www.googleapis.com/auth/userinfo.email` | Retrieve user's email address for account identification |
| `https://www.googleapis.com/auth/userinfo.profile` | Retrieve user's profile information |

### Token Format

Credentials follow the Google OAuth2 Credentials format with extended fields:

```json
{
  "account_id": "personal-gmail",
  "email": "user@gmail.com",
  "access_token": "ya29.xxx...",
  "refresh_token": "1//xxx...",
  "token_type": "Bearer",
  "scope": "https://www.googleapis.com/auth/cloud-platform ...",
  "expiry_date": 1737417600000,
  "created_at": "2026-01-20T23:55:51+01:00",
  "updated_at": "2026-01-20T23:55:51+01:00",
  "last_used": null
}
```

**Note**: `expiry_date` is in **milliseconds** since epoch (consistent with gemini-cli).

---

## Requirements

### Requirement 1: OAuth2 Authorization Flow

**Objective:** As a developer, I want the `gemini-oauth-auto` connector to handle OAuth2 authorization independently, so that I don't need the `gemini-cli` application installed or running.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1. When a user initiates account registration via the management script, the OAuth Management Service shall start a temporary local HTTP server on a dynamically allocated port (or configurable fixed port).
2. When the HTTP callback server starts, the OAuth Management Service shall generate a cryptographically random `state` parameter for CSRF protection.
3. When the HTTP callback server starts, the OAuth Management Service shall construct the Google OAuth2 authorization URL with the following parameters:
   - `client_id`: The embedded OAuth client ID
   - `redirect_uri`: `http://localhost:{port}/oauth2callback`
   - `response_type`: `code`
   - `scope`: The three required OAuth scopes
   - `access_type`: `offline` (to receive refresh_token)
   - `state`: The generated CSRF token
4. The OAuth Management Service shall print the authorization URL to the console for manual access.
5. The OAuth Management Service shall attempt to automatically open the authorization URL in the user's default browser using Python's `webbrowser` module.
6. When Google redirects to the callback URL with an authorization code, the OAuth Management Service shall validate the `state` parameter matches the expected value.
7. When the state is valid, the OAuth Management Service shall exchange the authorization code for tokens by POSTing to `https://oauth2.googleapis.com/token`.
8. When tokens are received, the OAuth Management Service shall fetch the user's email from `https://www.googleapis.com/oauth2/v2/userinfo` to identify the account.
9. When authentication completes successfully, the OAuth Management Service shall redirect the user's browser to `https://developers.google.com/gemini-code-assist/auth_success_gemini`.
10. If the authorization code exchange fails, the OAuth Management Service shall redirect the browser to `https://developers.google.com/gemini-code-assist/auth_failure_gemini` and display a clear error message in the console.
11. If the user cancels the OAuth flow or the callback times out (default: 120 seconds), the OAuth Management Service shall terminate gracefully with an informative message.

#### Technical Constraints

- Async compatibility: Use `aiohttp` or Python stdlib for local HTTP server
- Token exchange must use `httpx` async HTTP client
- The callback server must listen on localhost only (127.0.0.1)
- Port selection: Dynamic by default (bind to port 0), with `--port` override option
- State parameter: 32 random bytes encoded as hex string

---

### Requirement 2: Token Storage and Persistence

**Objective:** As an operator, I want OAuth tokens stored securely on disk, so that accounts persist across proxy restarts and tokens can be refreshed automatically.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1. When tokens are obtained (initial or refreshed), the Token Storage Service shall persist them to a JSON file in `var/gemini_oauth_accounts/`.
2. The Token Storage Service shall store each account in a separate file named `{account_id}.json`.
3. The Token Storage Service shall store the following fields per account:
   - `account_id`: User-specified or auto-generated identifier
   - `email`: Google account email (retrieved from userinfo endpoint)
   - `access_token`: Current OAuth access token
   - `refresh_token`: Long-lived refresh token
   - `token_type`: Token type (typically "Bearer")
   - `scope`: Space-separated list of granted scopes
   - `expiry_date`: Token expiry timestamp in **milliseconds** since epoch
   - `created_at`: ISO 8601 timestamp of initial account registration
   - `updated_at`: ISO 8601 timestamp of last token update
   - `last_used`: ISO 8601 timestamp of last API request (or null)
4. When the proxy starts, the Token Storage Service shall load all previously stored accounts from disk.
5. If a stored token file is corrupted or unreadable, the Token Storage Service shall log a warning and skip that account (fail-open for individual accounts).
6. The Token Storage Service shall use file-based atomic writes (write to temp file, then rename) to prevent corruption.
7. The Token Storage Service shall set restrictive file permissions (600 on POSIX, best-effort on Windows) on token files to protect credentials.

#### Technical Constraints

- Storage location: `var/gemini_oauth_accounts/` (auto-created if missing)
- File format: JSON with indentation for readability
- Must handle concurrent access safely (file locking or atomic operations)
- Account ID validation: alphanumeric, hyphens, underscores only (max 64 chars)

---

### Requirement 3: Automatic Token Refresh

**Objective:** As a developer, I want the connector to automatically refresh expired tokens, so that API requests don't fail due to token expiration.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1. While an access token is within 5 minutes of expiry (300,000 ms before `expiry_date`), the Token Refresh Service shall proactively refresh the token before the next API request.
2. When refreshing a token, the Token Refresh Service shall POST to `https://oauth2.googleapis.com/token` with:
   - `client_id`: The embedded OAuth client ID
   - `client_secret`: The embedded OAuth client secret
   - `refresh_token`: The stored refresh token
   - `grant_type`: `refresh_token`
3. When an API request receives a 401 Unauthorized response, the Token Refresh Service shall attempt to refresh the token and retry the request once.
4. If token refresh fails due to invalid/revoked refresh token (HTTP 400 with `invalid_grant`), the Token Refresh Service shall mark the account as requiring re-authorization by setting a `needs_reauth` flag.
5. When a token is successfully refreshed, the Token Storage Service shall immediately persist the new tokens to disk with updated `expiry_date` and `updated_at`.
6. The Token Refresh Service shall prevent concurrent refresh attempts for the same account using an async lock.

#### Technical Constraints

- Async compatibility: Use `asyncio.Lock` for refresh coordination
- Expiry buffer: Configurable (default: 300 seconds / 5 minutes / 300,000 ms)
- Retry with exponential backoff on network failures (3 attempts, 1s/2s/4s delays)

---

### Requirement 4: Multi-Account Support

**Objective:** As an operator, I want to register and use multiple Google accounts, so that I can distribute load or use different accounts for different purposes.

**Priority:** P1 (High)

#### Acceptance Criteria

1. The Token Storage Service shall support storing credentials for multiple distinct Google accounts (one file per account).
2. When configuring the `gemini-oauth-auto` backend, the operator shall be able to specify which account(s) to use via configuration (list of account IDs or `"all"`).
3. If multiple accounts are configured, the Account Selection Service shall rotate between them for load distribution (round-robin by default).
4. If a specific account is requested by session or configuration, the Account Selection Service shall use that account exclusively.
5. When an account's quota is exhausted (HTTP 429), the Account Selection Service shall automatically rotate to the next available account within 100ms.
6. When an account is marked as `needs_reauth`, the Account Selection Service shall skip it during rotation and log a warning.

#### Technical Constraints

- Account selection strategy: Round-robin (default), configurable
- Config format: list of account IDs or `"all"` keyword
- DI integration: Account selection via composable service

---

### Requirement 5: Account Management Script - List Accounts

**Objective:** As an operator, I want to list all registered accounts, so that I can see what accounts are available and their status.

**Priority:** P1 (High)

#### Acceptance Criteria

1. When the user invokes `python scripts/manage_gemini_accounts.py list`, the script shall display all registered accounts.
2. The list output shall include: account_id, email, token status (valid/expired/needs_reauth), expiry time, and last_used timestamp.
3. If no accounts are registered, the script shall display a message indicating no accounts found with instructions to add one.
4. The script shall support `--json` flag to output in machine-readable JSON format.

#### Technical Constraints

- Output format: Table for terminal (default), JSON with `--json` flag
- Must work standalone without starting the proxy server
- Script location: `scripts/manage_gemini_accounts.py`

---

### Requirement 6: Account Management Script - Add Account

**Objective:** As an operator, I want to add a new Google account via the management script, so that I can register accounts for the connector to use.

**Priority:** P1 (High)

#### Acceptance Criteria

1. When the user invokes `python scripts/manage_gemini_accounts.py add`, the script shall initiate the OAuth2 authorization flow.
2. The script shall print the Google authorization URL to the console with clear instructions.
3. The script shall attempt to automatically open the URL in the user's default browser.
4. When the user completes login on Google's page and grants permission, the callback shall capture the authorization code.
5. When authorization completes successfully, the script shall display a success message with the account email and assigned account_id.
6. If the account email is already registered, the script shall prompt for confirmation to update the existing tokens (unless `--force` is provided).
7. The script shall support `--account-id <id>` to specify a custom identifier for the account.
8. The script shall support `--no-browser` flag to disable automatic browser opening (print URL only).
9. The script shall support `--port <port>` to override the default dynamic port selection.
10. The script shall support `--timeout <seconds>` to override the default 120-second timeout.

#### Technical Constraints

- Async compatibility: Use `asyncio.run()` wrapper for script entry
- Timeout: default 120 seconds for user to complete authorization
- Script must be runnable directly: `python scripts/manage_gemini_accounts.py add`

---

### Requirement 7: Account Management Script - Update Account

**Objective:** As an operator, I want to re-authorize an existing account, so that I can fix expired or revoked credentials.

**Priority:** P2 (Medium)

#### Acceptance Criteria

1. When the user invokes `python scripts/manage_gemini_accounts.py update <account-id>`, the script shall initiate re-authorization for that account.
2. If the specified account does not exist, the script shall display an error with available account IDs.
3. When re-authorization completes, the script shall update the stored tokens, clear the `needs_reauth` flag, and display success.
4. The script shall preserve the original `account_id` and `created_at` values while updating tokens.

#### Technical Constraints

- Reuse the same OAuth flow from `add` command
- Preserve account metadata (account_id, created_at) while updating tokens

---

### Requirement 8: Account Management Script - Remove Account

**Objective:** As an operator, I want to remove a registered account, so that I can clean up unused accounts or revoke access.

**Priority:** P2 (Medium)

#### Acceptance Criteria

1. When the user invokes `python scripts/manage_gemini_accounts.py remove <account-id>`, the script shall delete the account's stored credentials file.
2. The script shall prompt for confirmation before deletion unless `--force` flag is provided.
3. If the specified account does not exist, the script shall display an error with available account IDs.
4. When removal completes, the script shall display success and recommend revoking access via Google's security settings at `https://myaccount.google.com/permissions`.

#### Technical Constraints

- File deletion must be atomic (no partial state)
- Log the removal at INFO level for audit trail

---

### Requirement 9: Backend Connector Implementation

**Objective:** As a developer, I want a `gemini-oauth-auto` backend connector that uses locally managed OAuth tokens, so that I can route requests through the proxy without external dependencies.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1. The `gemini-oauth-auto` connector shall extend the existing `GeminiOAuthBaseConnector` class.
2. When chat completions are requested, the connector shall obtain valid credentials from the Token Storage Service.
3. The connector shall use the Account Selection Service to choose which account to use for each request.
4. If no valid accounts are available (all expired/needs_reauth and refresh failed), the connector shall raise a `BackendError` with guidance to run the management script.
5. The connector shall register itself with `backend_registry` using type `"gemini-oauth-auto"`.
6. The connector shall support all existing `gemini-oauth*` features: streaming, non-streaming, graceful degradation, quota handling.
7. When an account is rotated due to quota exhaustion, the connector shall log the rotation at DEBUG level.
8. The connector shall update the `last_used` timestamp for the account after each successful request.

#### Technical Constraints

- DI integration: Compose Token Storage and Account Selection services
- Error hierarchy: Exceptions extend `LLMProxyError`
- Staged initialization: Register in BackendStage
- Override credential loading to use local storage instead of `~/.gemini/oauth_creds.json`

---

### Requirement 10: Configuration Schema

**Objective:** As an operator, I want to configure the `gemini-oauth-auto` connector via YAML, so that I can control its behavior without code changes.

**Priority:** P1 (High)

#### Acceptance Criteria

1. The configuration schema shall support specifying which accounts to use (list of IDs or `"all"`).
2. The configuration schema shall support the OAuth callback port setting (for management script).
3. The configuration schema shall support token refresh buffer (seconds before expiry to trigger refresh).
4. The configuration schema shall support account selection strategy (`round-robin`, `random`, `first-available`).
5. Where configuration is missing, the connector shall use sensible defaults:
   - Accounts: `"all"`
   - Refresh buffer: 300 seconds
   - Selection strategy: `round-robin`
6. The configuration schema shall be documented in `config/schemas/`.

#### Technical Constraints

- Config precedence: CLI > ENV > YAML > defaults
- Schema location: `config/schemas/gemini_oauth_auto.yaml`
- Pydantic validation for config models

---

## Non-Functional Requirements

### NFR 1: Performance

- Token refresh latency: < 2 seconds under normal network conditions
- Account rotation: < 10ms overhead per request
- Startup account loading: < 500ms for up to 10 accounts

### NFR 2: Reliability

- Token file corruption: Graceful recovery (skip corrupted, continue with valid)
- Network failures during refresh: Retry with exponential backoff (3 attempts, 1s/2s/4s delays)
- Quota exhaustion: Automatic failover to next account within 100ms

### NFR 3: Observability

- Logging: All OAuth events at DEBUG, errors at ERROR, security events at WARNING
- Token refresh: Log refresh attempts and outcomes at DEBUG level
- Account rotation: Log rotation decisions at DEBUG level
- Never log `access_token` or `refresh_token` values

### NFR 4: Security

- Token files: Restricted permissions (600 on POSIX, best-effort on Windows)
- Callback server: Bind to localhost only (127.0.0.1), reject non-local connections
- Token display: Never log or display access_token or refresh_token values
- CSRF protection: Validate state parameter on OAuth callback
- Client credentials: Use embedded credentials (approved per Google's installed app policy)

---

## Glossary

| Term | Definition |
|------|------------|
| Backend | LLM provider connector (OpenAI, Anthropic, Gemini, etc.) |
| Wire Capture | CBOR-encoded traffic recording for debugging |
| Staged Init | Sequential initialization phases for services |
| DI Container | Dependency injection via `ServiceCollection` |
| OAuth2 | Open Authorization 2.0 protocol for secure API access |
| Access Token | Short-lived credential for API authentication (~1 hour) |
| Refresh Token | Long-lived credential used to obtain new access tokens |
| gemini-cli | External CLI tool that manages Gemini OAuth tokens (dependency we're eliminating) |
| Callback URL | Local HTTP endpoint that receives the OAuth authorization code |
| State Parameter | Random token for CSRF protection in OAuth flow |
| expiry_date | Token expiry timestamp in milliseconds since epoch |

---

## Out of Scope

1. **Token encryption at rest**: Initial implementation uses plaintext JSON; encryption can be added later.
2. **Service account support**: This feature targets personal Google accounts only.
3. **OAuth for other providers**: Only Google OAuth2 for Gemini is in scope.
4. **GUI for account management**: Script-only interface via `scripts/manage_gemini_accounts.py`.
5. **Token synchronization across machines**: Tokens are local to each installation.
6. **PKCE flow**: Not required since we use the same flow as gemini-cli (with client_secret).
7. **Custom OAuth client credentials**: Initial implementation uses gemini-cli's embedded credentials.
