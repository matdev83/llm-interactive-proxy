# Gap Analysis: create-gemini-oauth-auto-connector

**Analyzed**: 2026-01-20T23:49:19+01:00  
**Updated**: 2026-01-20T23:55:51+01:00 (Added gemini-cli OAuth investigation)  
**Status**: Brownfield analysis for extension of existing gemini-oauth infrastructure

---

## 1. Current State Investigation

### 1.1 Domain-Related Assets

#### Existing Gemini OAuth Infrastructure

| Asset | Location | Purpose | Reusability |
|-------|----------|---------|-------------|
| **GeminiOAuthBaseConnector** | `src/connectors/gemini_base/connector.py` | Base class for all gemini-oauth* connectors (2,641 lines) | ✅ Extend directly |
| **GeminiOAuthFreeConnector** | `src/connectors/gemini_oauth_free.py` | Free-tier connector using gemini-cli tokens | ✅ Reference for structure |
| **GeminiOAuthPlanConnector** | `src/connectors/gemini_oauth_plan.py` | Paid-tier connector | ✅ Reference for structure |
| **CredentialCoordinator** | `src/connectors/gemini_base/credential_coordinator.py` | Credential lifecycle management | ⚠️ Designed for single-account CLI-based flow |
| **CredentialLoader** | `src/connectors/gemini_base/credential_loader.py` | Load/save credentials from file | ✅ Reuse file loading patterns |
| **TokenManager** | `src/connectors/gemini_base/token_manager.py` | Token expiry checking, CLI-based refresh | ⚠️ Tightly coupled to gemini-cli subprocess |
| **FileWatcher** | `src/connectors/gemini_base/file_watcher.py` | Watch credential file for changes | ✅ Reuse for multi-account |
| **GeminiOAuthCredentials** | `src/connectors/gemini_base/models.py` | Pydantic model for credentials | ✅ Extend for additional fields |

#### Storage Infrastructure

| Asset | Location | Purpose |
|-------|----------|---------|
| **var/** | `var/` | Runtime state directory (already exists) |
| **var/db/** | `var/db/` | SQLite storage (usage tracking) |
| **var/state/** | `var/state/` | State files |

#### Script Infrastructure

| Asset | Location | Purpose |
|-------|----------|---------|
| **scripts/** | `scripts/` | User-facing tools (7 scripts) |
| **scripts/list_models.py** | Example | Simple sync script pattern |
| **scripts/inspect_cbor_capture.py** | Example | Complex async script with argparse |

---

## 2. Gemini-CLI OAuth Investigation (CRITICAL FINDINGS)

### 2.1 OAuth Client Credentials

**Source**: `dev/thrdparty/gemini-cli/packages/core/src/code_assist/oauth2.ts`

```typescript
// OAuth Client ID used to initiate OAuth2Client class.
const OAUTH_CLIENT_ID = '681255809395-[REDACTED].apps.googleusercontent.com';

// OAuth Secret value used to initiate OAuth2Client class.
// Note: It's ok to save this in git because this is an installed application
const OAUTH_CLIENT_SECRET = 'GOCSPX-[REDACTED]';
```

**Important**: Google explicitly allows embedding client secrets for "installed applications" (desktop apps). This is documented in Google's OAuth2 documentation.

### 2.2 OAuth Scopes

```typescript
const OAUTH_SCOPE = [
  'https://www.googleapis.com/auth/cloud-platform',
  'https://www.googleapis.com/auth/userinfo.email',
  'https://www.googleapis.com/auth/userinfo.profile',
];
```

### 2.3 OAuth Flow Implementation

**Two methods supported**:

1. **Browser-based (preferred)**: `authWithWeb()` function
   - Starts local HTTP server on dynamic port
   - Generates auth URL with state parameter
   - Opens browser automatically
   - Handles callback at `/oauth2callback`
   - Redirects to success/failure URL after completion

2. **Manual code entry**: `authWithUserCode()` function
   - Uses PKCE with S256 challenge
   - Uses fixed redirect URI: `https://codeassist.google.com/authcode`
   - User manually enters authorization code

### 2.4 Token Exchange Flow (Browser-based)

```typescript
// Key parameters for browser auth
const redirectUri = `http://localhost:${port}/oauth2callback`;
const state = crypto.randomBytes(32).toString('hex');
const authUrl = client.generateAuthUrl({
  redirect_uri: redirectUri,
  access_type: 'offline',  // Required to get refresh_token
  scope: OAUTH_SCOPE,
  state,
});

// Token exchange on callback
const { tokens } = await client.getToken({
  code: qs.get('code')!,
  redirect_uri: redirectUri,
});
```

### 2.5 Credential Storage Format

**File location**: `~/.gemini/oauth_creds.json`

**Format** (from `google-auth-library` Credentials type):

```json
{
  "access_token": "ya29.xxx...",
  "refresh_token": "1//xxx...",
  "token_type": "Bearer",
  "scope": "https://www.googleapis.com/auth/cloud-platform ...",
  "expiry_date": 1737417600000
}
```

**Note**: `expiry_date` is in **milliseconds** since epoch (not seconds).

### 2.6 User Info Endpoint

To get account email after authentication:

```typescript
const response = await fetch(
  'https://www.googleapis.com/oauth2/v2/userinfo',
  {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  },
);
const userInfo = await response.json();
// userInfo.email contains the Google account email
```

### 2.7 Success/Failure Redirect URLs

```typescript
const SIGN_IN_SUCCESS_URL =
  'https://developers.google.com/gemini-code-assist/auth_success_gemini';
const SIGN_IN_FAILURE_URL =
  'https://developers.google.com/gemini-code-assist/auth_failure_gemini';
```

### 2.8 Port Selection

gemini-cli uses dynamic port selection (binding to port 0 and letting OS assign):

```typescript
const server = net.createServer();
server.listen(0, () => {
  const address = server.address()! as net.AddressInfo;
  port = address.port;
});
```

Also supports `OAUTH_CALLBACK_PORT` environment variable for fixed port.

---

## 3. Requirements Feasibility Analysis (Updated)

### 3.1 Technical Needs from Requirements

| Req # | Category | Technical Need | gemini-cli Reference | Gap |
|-------|----------|---------------|---------------------|-----|
| 1 | OAuth Flow | PKCE authorization code flow | `authWithWeb()` | **Implement** - Port logic |
| 1 | OAuth Flow | Local HTTP callback server | `http.createServer()` | **Implement** - Use aiohttp |
| 2 | Storage | Multi-account JSON storage | `oauth_creds.json` | **Extend** - Multiple files |
| 3 | Refresh | Direct HTTP token refresh | `OAuth2Client.getToken()` | **Implement** - Use httpx |
| 4 | Multi-Account | Account rotation/selection | N/A | **New** - Round-robin |
| 5-8 | CLI | Script with list/add/update/remove | N/A | **New** - argparse script |
| 9 | Connector | New connector type | GeminiOAuthBaseConnector | **Extend** - Subclass |
| 10 | Config | YAML schema | config/schemas/*.yaml | **Extend** - New schema |

### 3.2 Complexity Signals (Updated)

| Aspect | Complexity | Notes |
|--------|------------|-------|
| OAuth2 flow | **Low** | gemini-cli provides complete reference |
| Client credentials | **Resolved** | Can use same as gemini-cli |
| Scopes | **Resolved** | Known: cloud-platform, userinfo.* |
| Token format | **Resolved** | Standard Google Credentials format |
| Local HTTP server | Low | Python stdlib + async patterns |
| Token refresh | Low | Standard Google OAuth2 token endpoint |
| Account rotation | Low | Round-robin iterator pattern |

### 3.3 Research Items (Resolved)

| ID | Item | Status | Resolution |
|----|------|--------|------------|
| R1 | Google OAuth client ID/secret | ✅ Resolved | Use gemini-cli credentials |
| R2 | Required OAuth scopes | ✅ Resolved | cloud-platform, userinfo.email/profile |
| R3 | Token endpoint format | ✅ Resolved | Standard Google OAuth2 |
| R4 | Credential storage format | ✅ Resolved | Google Credentials JSON |

---

## 4. Implementation Approach Options

### Option A: Extend Existing Components (Minimal New Files)

**Not recommended** - Risk of regressions in existing connectors.

---

### Option B: Create New Components (Clean Separation) - **RECOMMENDED**

**Approach**: Create dedicated services for self-managed OAuth flow.

**New Files**:

| File | Purpose |
|------|---------|
| `scripts/manage_gemini_accounts.py` | Account management script |
| `src/connectors/gemini_oauth_auto.py` | New connector |
| `src/connectors/gemini_oauth_auto/` | Service package |
| `src/connectors/gemini_oauth_auto/token_storage.py` | Multi-account credential storage |
| `src/connectors/gemini_oauth_auto/token_refresh.py` | HTTP-based token refresh |
| `src/connectors/gemini_oauth_auto/account_selector.py` | Round-robin account selection |
| `src/connectors/gemini_oauth_auto/oauth_flow.py` | OAuth2 browser flow handler |
| `src/connectors/gemini_oauth_auto/models.py` | Extended credential models |
| `config/schemas/gemini_oauth_auto.yaml` | Configuration schema |

**Key Implementation Details**:

1. **OAuth Flow** (`oauth_flow.py`):
   - Use `aiohttp` for local HTTP server (async-compatible)
   - Generate random state for CSRF protection
   - Dynamic port selection or configurable fixed port
   - Auto-open browser with `webbrowser.open()`
   - Handle callback at `/oauth2callback`
   - Exchange code for tokens using `httpx`

2. **Token Refresh** (`token_refresh.py`):
   - POST to `https://oauth2.googleapis.com/token`
   - Include `client_id`, `client_secret`, `refresh_token`, `grant_type=refresh_token`
   - Handle expired refresh tokens (mark account as needs_reauth)

3. **Storage** (`token_storage.py`):
   - Directory: `var/gemini_oauth_accounts/`
   - One file per account: `{account_id}.json`
   - Atomic writes (temp file + rename)
   - Lock file for concurrent access

---

### Option C: Hybrid Approach

Good alternative if file count is a concern. See previous analysis.

---

## 5. Implementation Complexity & Risk Assessment (Updated)

### Overall Effort: **M (Medium, 3-7 days)**

**Justification**:

- OAuth2 flow is fully documented with gemini-cli reference
- Client credentials and scopes are known
- Token format matches existing infrastructure
- Clear extension patterns

### Overall Risk: **Low** (downgraded from Medium)

**Risk Factors**:

| Risk | Severity | Mitigation |
|------|----------|-----------|
| ~~OAuth client ID sourcing~~ | ~~Medium~~ | ✅ Resolved - Use gemini-cli credentials |
| ~~OAuth scope requirements~~ | ~~Medium~~ | ✅ Resolved - Known scopes |
| Token expiry format | Low | Use milliseconds (gemini-cli format) |
| Windows file permissions | Low | Best-effort ACL or document limitation |

---

## 6. Key Implementation Constants

### OAuth Configuration (from gemini-cli)

```python
# OAuth Client Credentials (embedded - allowed per Google policy)
OAUTH_CLIENT_ID = "681255809395-[REDACTED].apps.googleusercontent.com"
OAUTH_CLIENT_SECRET = "GOCSPX-[REDACTED]"

# OAuth Scopes
OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# Endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

# Redirect URLs for browser
SIGN_IN_SUCCESS_URL = "https://developers.google.com/gemini-code-assist/auth_success_gemini"
SIGN_IN_FAILURE_URL = "https://developers.google.com/gemini-code-assist/auth_failure_gemini"
```

### Storage Format

```python
# Account credential file: var/gemini_oauth_accounts/{account_id}.json
{
    "account_id": "personal-gmail",
    "email": "user@gmail.com",
    "access_token": "ya29.xxx...",
    "refresh_token": "1//xxx...",
    "token_type": "Bearer",
    "scope": "https://www.googleapis.com/auth/cloud-platform ...",
    "expiry_date": 1737417600000,  # milliseconds since epoch
    "created_at": "2026-01-20T23:55:51+01:00",
    "updated_at": "2026-01-20T23:55:51+01:00",
    "last_used": "2026-01-20T23:55:51+01:00"
}
```

---

## 7. Recommendations for Design Phase

### Preferred Approach: **Option B (Create New Components)**

### Key Design Decisions (Pre-resolved)

1. **OAuth Client Credentials**: Use gemini-cli's embedded credentials ✅
2. **OAuth Scopes**: Use gemini-cli's scopes ✅
3. **Storage Location**: `var/gemini_oauth_accounts/`
4. **Token Format**: Google Credentials JSON with extended fields
5. **Port Selection**: Dynamic (like gemini-cli) with configurable override

### Implementation Priority

1. **Phase 1**: OAuth flow + single account storage + management script
2. **Phase 2**: Multi-account support + connector implementation
3. **Phase 3**: Account rotation + quota-based failover

---

## Summary

| Metric | Value | Notes |
|--------|-------|-------|
| **Effort** | M (3-7 days) | Clear reference implementation available |
| **Risk** | **Low** | All major unknowns resolved |
| **Preferred Approach** | Option B | Create new components with clean separation |
| **Reusable Assets** | ~60% | Base connector, validators, patterns |
| **New Code** | ~40% | OAuth flow, storage, script, connector |
| **OAuth Credentials** | ✅ Resolved | Use gemini-cli's embedded credentials |
| **OAuth Scopes** | ✅ Resolved | cloud-platform, userinfo.email/profile |
