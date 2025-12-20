# Analysis: Automated Antigravity Credentials Management

## Executive Summary

The current `gemini-oauth-antigravity` backend in `llm-interactive-proxy` is a **passive consumer** that relies on an external application (VS Code with the Antigravity extension) to perform authentication and maintain valid tokens.

The `oh-my-opencode` project implements an **active OAuth client** that replicates the Antigravity authentication flow. It operates independently of VS Code, handling the full OAuth 2.0 PKCE lifecycle including initial authorization, token exchange, and automatic refreshing.

Porting this logic to `llm-interactive-proxy` is **highly feasible** and recommended. It would eliminate the dependency on VS Code running in the background and enable robust, multi-account support directly within the proxy.

## Comparison

| Feature | Current `gemini-oauth-antigravity` | `oh-my-opencode` Implementation |
| :--- | :--- | :--- |
| **Dependency** | **High**: Requires VS Code + Antigravity extension running. | **None**: Standalone implementation. |
| **Auth Flow** | **Passive**: Reads `state.vscdb` (SQLite) for existing tokens. | **Active**: Implements OAuth 2.0 PKCE flow. |
| **Token Refresh** | **External**: Fails if VS Code hasn't refreshed the token. | **Internal**: Automatically refreshes using `refresh_token`. |
| **Multi-Account** | **Limited**: Single account (whatever is active in VS Code). | **Flexible**: Can manage multiple token sets independently. |
| **Reliability** | **Flaky**: Prone to "token expired" errors if VS Code idles. | **Robust**: Self-healing via auto-refresh. |

## Technical Deep Dive

### Current Implementation (`llm-interactive-proxy`)
*   **File**: `src/connectors/gemini_oauth_antigravity.py`
*   **Strategy**: `AntigravitySQLiteCredentialProvider` reads the `antigravityAuthStatus` key from `state.vscdb`.
*   **Limitation**: It treats the token as a static bearer token. It has no access to the `client_secret` or logic to perform a refresh exchange.

### `oh-my-opencode` Implementation
*   **Language**: TypeScript
*   **Core Logic**: `src/auth/antigravity/{oauth.ts, token.ts, constants.ts}`
*   **OAuth Flow**:
    1.  Generates PKCE verifier/challenge.
    2.  Constructs Google OAuth URL with Antigravity scopes and Client ID.
    3.  Starts a local HTTP server (port 51121) to capture the callback.
    4.  Exchanges the authorization code for `access_token` and `refresh_token`.
*   **Constants**:
    *   **Client ID**: `1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com`
    *   **Client Secret**: `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` (Standard for this app type).
    *   **Scopes**: `cloud-platform`, `userinfo.email`, `cclog`, etc.

## Proposed Architecture for `llm-interactive-proxy`

We should implement a new backend flavor, likely named `gemini-oauth-antigravity-active`, or enhance the existing one with a new `CredentialProvider` strategy.

### 1. New Credential Provider: `AntigravityOAuthCredentialProvider`
Instead of reading SQLite, this provider will:
*   **Store**: Save tokens (access + refresh) in a local JSON file (e.g., `var/auth/antigravity_tokens.json`).
*   **Load**: Read valid tokens from the JSON file.
*   **Refresh**: If the access token is near expiry, use the `refresh_token` and the Client ID/Secret to fetch a new one immediately.
*   **Authorize**: If no valid tokens exist, trigger the CLI-based OAuth flow (print URL, spin up temporary callback server).

### 2. Multi-Account Support
The storage format can support multiple accounts:
```json
{
  "active_account": "user@example.com",
  "accounts": {
    "user@example.com": {
      "access_token": "...",
      "refresh_token": "...",
      "expiry": 1234567890
    },
    "work@example.com": { ... }
  }
}
```
The backend configuration in `config.yaml` can specify which account to use, or the proxy can implement rotation strategies.

## Implementation Plan

1.  **Port Constants**: Copy Client ID, Secret, and Scopes to a Python constants file.
2.  **Implement OAuth Utilities**: Create Python equivalents for `generatePKCE`, `buildAuthURL`, and `exchangeCode`.
3.  **Implement Callback Server**: Use `aiohttp` or `http.server` to create a transient callback listener.
4.  **Create Provider**: Implement `AntigravityOAuthCredentialProvider` matching the `CredentialProvider` interface.
5.  **Integrate**: Register the new provider in the backend factory, optionally controlled by a config flag (e.g., `auth_mode: auto` vs `auth_mode: vscode`).

## Security Considerations
*   **Token Storage**: Tokens will be stored on disk. Ensure the file permissions are restricted (0600) to the user only. This is no less secure than the current `state.vscdb` approach (which is also just a file on disk).
*   **Client Secret**: The "Client Secret" for installed applications (like VS Code extensions) is public knowledge and embedded in the code. It is safe to include in our project as it identifies the *application*, not the *user*.

## Conclusion
Porting this feature is a low-risk, high-reward task that significantly improves the usability of the Antigravity backend.
