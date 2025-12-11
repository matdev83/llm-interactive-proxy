# Requirements Document

## Project Description (Input)
Create a new backend connector: `opencode-zen`. It should be based on a similar idea how `qwen-oauth` and `cline` backend connectors are working - you can view them to find more details. Idea is simple - we implement this as OpenAI chat completions subclass with modified auth process. Instead of API key, we use auth credentials from the credentials file created by the `opencode` app. You are provided with a source code of the `opencode` inside ./dev/thrdparty/ respective folder - you can analyze `opencode`'s source code to find out how it authenticates to its own `Zen` gateway and where it stores credentials file and in what format

## Analysis Summary

### OpenCode Authentication System
Based on analysis of `./dev/thrdparty/opencode/packages/opencode/src/auth/index.ts`:

**Credentials File Location:**
- Path: `~/.local/share/opencode/auth.json` (XDG data directory on Linux/macOS)
- Windows equivalent: `%LOCALAPPDATA%/opencode/auth.json` or similar XDG-compliant path

**Credentials Format (Zod schema):**
```typescript
// OAuth type - used for Zen gateway authentication
{
  type: "oauth",
  refresh: string,  // Refresh token
  access: string,   // Access token for API calls
  expires: number   // Expiry timestamp (Unix ms or seconds)
}

// API key type (alternative)
{
  type: "api",
  key: string
}

// WellKnown type (alternative)  
{
  type: "wellknown",
  key: string,
  token: string
}
```

**Provider Key:** The credentials are stored keyed by provider ID (e.g., "opencode" for the Zen gateway)

### Zen Gateway Details
Based on analysis of `./dev/thrdparty/opencode/cloud/function/src/gateway.ts`:

**Gateway Endpoint:** `https://api.gateway.opencode.ai/v1/chat/completions`

**Authentication:** Bearer token in Authorization header using the `access` token from OAuth credentials

**Supported Models:**
- `anthropic/claude-sonnet-4`
- `openai/gpt-4.1`
- `zhipuai/glm-4.5-flash`

### Reference Implementations
- **qwen-oauth connector**: Uses OAuth credentials from `~/.qwen/oauth_creds.json`, implements token refresh, file watching
- **cline connector**: Uses auth tokens from Cline's secrets storage, implements auth mixin pattern

## Requirements

### REQ-1: Connector Class Structure
**Priority:** High
**Description:** Create `OpencodeZenConnector` class extending `OpenAIConnector` following the pattern established by `QwenOAuthConnector` and `ClineConnector`.

**Acceptance Criteria:**
- [ ] Class extends `OpenAIConnector`
- [ ] Backend type is `"opencode-zen"`
- [ ] Registered in backend registry

### REQ-2: Credentials File Reading (Cross-Platform)
**Priority:** High
**Description:** Read and parse OpenCode authentication credentials using OS-agnostic path resolution that works correctly on Windows, Linux, and macOS.

**Acceptance Criteria:**
- [ ] **Cross-Platform Path Resolution (CRITICAL):**
  - [ ] Use Python's `Path.home()` for reliable home directory detection on all platforms
  - [ ] On **Linux**: Use `$XDG_DATA_HOME` if set, otherwise `~/.local/share/opencode/auth.json`
  - [ ] On **macOS**: Use `$XDG_DATA_HOME` if set, otherwise `~/.local/share/opencode/auth.json`
  - [ ] On **Windows**: Use `%LOCALAPPDATA%\opencode\auth.json` (via `os.environ.get("LOCALAPPDATA")`)
  - [ ] Fallback to `Path.home() / ".local" / "share" / "opencode" / "auth.json"` if environment variables not set
  - [ ] Use `pathlib.Path` for all path operations (not string concatenation)
  - [ ] Use forward slashes or `Path` objects to avoid Windows backslash issues
- [ ] Parse JSON and extract provider-specific credentials (keyed by "opencode")
- [ ] Support OAuth type credentials: `{type: "oauth", access, refresh, expires}`
- [ ] Handle file not found gracefully with clear error message
- [ ] Handle malformed JSON gracefully

**Platform-Specific Path Examples:**
| Platform | Environment Variable | Default Path |
|----------|---------------------|--------------|
| Linux | `$XDG_DATA_HOME/opencode/auth.json` | `~/.local/share/opencode/auth.json` |
| macOS | `$XDG_DATA_HOME/opencode/auth.json` | `~/.local/share/opencode/auth.json` |
| Windows | `%LOCALAPPDATA%\opencode\auth.json` | `C:\Users\{user}\AppData\Local\opencode\auth.json` |

### REQ-3: OAuth Token Management
**Priority:** High
**Description:** Implement OAuth token lifecycle management including expiry detection and refresh.

**Acceptance Criteria:**
- [ ] Detect token expiry based on `expires` field
- [ ] Implement token refresh mechanism before API calls
- [ ] Use access token for Bearer authentication
- [ ] Cache tokens in memory to avoid repeated file reads
- [ ] Handle token refresh failures gracefully

### REQ-4: Zen Gateway Integration
**Priority:** High
**Description:** Configure connector to communicate with OpenCode's Zen gateway.

**Acceptance Criteria:**
- [ ] Default API base URL: `https://api.gateway.opencode.ai/v1`
- [ ] Support configurable endpoint override
- [ ] Pass Authorization header with Bearer access token
- [ ] Support streaming and non-streaming responses

### REQ-5: Model Routing
**Priority:** Medium
**Description:** Support model routing for available Zen gateway models.

**Acceptance Criteria:**
- [ ] Define available models list (anthropic/claude-sonnet-4, openai/gpt-4.1, zhipuai/glm-4.5-flash)
- [ ] Support vendor-prefixed model names (e.g., "opencode-zen/anthropic/claude-sonnet-4")
- [ ] Strip prefix before sending to gateway

### REQ-6: Initialization and Health Check
**Priority:** High
**Description:** Implement proper initialization and health check mechanisms.

**Acceptance Criteria:**
- [ ] Validate credentials exist and are readable during initialization
- [ ] Validate token format and expiry during initialization
- [ ] Set `is_functional` flag appropriately
- [ ] Implement health check that verifies credential validity

### REQ-7: Credentials File Watching (Optional)
**Priority:** Low
**Description:** Optionally watch for credentials file changes to support token updates.

**Acceptance Criteria:**
- [ ] Use watchdog or similar for file monitoring
- [ ] Reload credentials when file changes
- [ ] Handle file deletion gracefully

### REQ-8: Error Handling
**Priority:** High
**Description:** Implement comprehensive error handling with clear error messages.

**Acceptance Criteria:**
- [ ] Raise `AuthenticationError` for missing/invalid credentials
- [ ] Raise `BackendError` for API communication failures
- [ ] Provide actionable error messages (e.g., "Run 'opencode auth login' to authenticate")
- [ ] Log appropriate debug/info messages during operation

### REQ-9: Configuration Support
**Priority:** Medium
**Description:** Support configuration through app config and environment variables.

**Acceptance Criteria:**
- [ ] Allow custom credentials path via config or environment variable
- [ ] Support timeout configuration
- [ ] Support debug/override flags similar to qwen-oauth

### REQ-10: Unit Tests
**Priority:** High
**Description:** Create comprehensive unit tests for the connector.

**Acceptance Criteria:**
- [ ] Test credentials file parsing
- [ ] Test token expiry detection
- [ ] Test authentication flow
- [ ] Test error scenarios
- [ ] Mock external dependencies appropriately
- [ ] **Cross-Platform Path Tests (CRITICAL):**
  - [ ] Test path resolution on Windows (mock `os.name == "nt"` and `LOCALAPPDATA`)
  - [ ] Test path resolution on Linux (mock `os.name == "posix"` and `XDG_DATA_HOME`)
  - [ ] Test path resolution on macOS (mock `os.name == "posix"` without XDG)
  - [ ] Test fallback when environment variables are not set
  - [ ] Test `Path.home()` based fallback


