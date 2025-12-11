# Design Document: opencode-zen-connector

## Overview

This document describes the technical design for the `opencode-zen` backend connector, which enables the LLM Interactive Proxy to route requests through OpenCode's Zen gateway using credentials stored by the OpenCode application.

## Architecture

### High-Level Design

```
┌─────────────────────────────────────────────────────────────────────┐
│                         LLM Interactive Proxy                        │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │                    OpencodeZenConnector                          │ │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │ │
│  │  │ Credentials     │  │ Token Manager   │  │ OpenAI          │  │ │
│  │  │ Loader          │  │                 │  │ Connector       │  │ │
│  │  │                 │  │ - Expiry check  │  │ (parent class)  │  │ │
│  │  │ - XDG paths     │  │ - Token cache   │  │                 │  │ │
│  │  │ - File parsing  │  │ - Auth headers  │  │ - HTTP client   │  │ │
│  │  │ - File watching │  │                 │  │ - Streaming     │  │ │
│  │  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘  │ │
│  │           │                    │                    │            │ │
│  └───────────┼────────────────────┼────────────────────┼────────────┘ │
│              │                    │                    │              │
│              v                    v                    v              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐   │
│  │ ~/.local/share/ │  │ In-memory       │  │ api.gateway.        │   │
│  │ opencode/       │  │ token cache     │  │ opencode.ai         │   │
│  │ auth.json       │  │                 │  │                     │   │
│  └─────────────────┘  └─────────────────┘  └─────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Component Design

#### 1. OpencodeZenConnector (Main Class)

**Location:** `src/connectors/opencode_zen.py`

**Inheritance:** Extends `OpenAIConnector`

**Purpose:** Main connector class that integrates with OpenCode's Zen gateway using stored OAuth credentials.

```python
class OpencodeZenConnector(OpenAIConnector):
    backend_type: str = "opencode-zen"
    VENDOR_PREFIX: str = "opencode-zen"
    
    # Configuration
    _default_endpoint: str = "https://api.gateway.opencode.ai/v1"
    _credentials_path: Path | None = None
    _provider_key: str = "opencode"  # Key in auth.json
    
    # Token management
    _oauth_credentials: dict[str, Any] | None = None
    _token_lock: asyncio.Lock
    _last_modified: float = 0
    
    # State
    is_functional: bool = False
```

**Key Methods:**
- `initialize(**kwargs)`: Load credentials, validate, set up file watching
- `get_headers(identity)`: Override to use OAuth access token
- `chat_completions(...)`: Ensure token validity before API calls
- `_load_oauth_credentials()`: Load and parse auth.json
- `_is_token_expired()`: Check token expiry
- `get_available_models()`: Return vendor-prefixed model list

#### 2. Credentials Loader Module

**Location:** Inline in connector (similar to qwen_oauth pattern)

**Responsibilities:**
- Determine correct credentials file path (OS-agnostic, cross-platform)
- Parse JSON and extract provider-specific credentials
- Validate credential structure

**Cross-Platform Path Resolution Logic (CRITICAL):**

The path resolution MUST work correctly on Windows, Linux, and macOS using Python's `pathlib.Path` for all operations:

```python
import os
import sys
from pathlib import Path

def _get_default_credentials_path(self) -> Path:
    """
    Determine the credentials file path in an OS-agnostic way.
    
    Platform-specific behavior:
    - Windows: %LOCALAPPDATA%\opencode\auth.json
    - Linux: $XDG_DATA_HOME/opencode/auth.json or ~/.local/share/opencode/auth.json
    - macOS: $XDG_DATA_HOME/opencode/auth.json or ~/.local/share/opencode/auth.json
    
    Returns:
        Path object pointing to the credentials file
    """
    # Windows: Use LOCALAPPDATA
    if sys.platform == "win32" or os.name == "nt":
        localappdata = os.environ.get("LOCALAPPDATA")
        if localappdata:
            return Path(localappdata) / "opencode" / "auth.json"
        # Fallback for Windows if LOCALAPPDATA not set
        return Path.home() / "AppData" / "Local" / "opencode" / "auth.json"
    
    # Linux/macOS: Use XDG_DATA_HOME or default
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / "opencode" / "auth.json"
    
    # Default XDG data directory
    return Path.home() / ".local" / "share" / "opencode" / "auth.json"
```

**Platform-Specific Path Examples:**

| Platform | Condition | Resolved Path |
|----------|-----------|---------------|
| Windows | `LOCALAPPDATA` set | `C:\Users\{user}\AppData\Local\opencode\auth.json` |
| Windows | `LOCALAPPDATA` not set | `C:\Users\{user}\AppData\Local\opencode\auth.json` (via `Path.home()`) |
| Linux | `XDG_DATA_HOME` set | `{XDG_DATA_HOME}/opencode/auth.json` |
| Linux | `XDG_DATA_HOME` not set | `/home/{user}/.local/share/opencode/auth.json` |
| macOS | `XDG_DATA_HOME` set | `{XDG_DATA_HOME}/opencode/auth.json` |
| macOS | `XDG_DATA_HOME` not set | `/Users/{user}/.local/share/opencode/auth.json` |

**Implementation Notes:**
- Always use `pathlib.Path` for path construction (never string concatenation with `/` or `\\`)
- Use `Path.home()` instead of `os.path.expanduser("~")` for better cross-platform support
- Check `sys.platform == "win32"` or `os.name == "nt"` for Windows detection
- Use `/` operator with `Path` objects which handles separators correctly on all platforms

**Credential Structure (from auth.json):**
```json
{
  "opencode": {
    "type": "oauth",
    "access": "eyJ...",
    "refresh": "dGVz...",
    "expires": 1733000000
  }
}
```

#### 3. Token Manager (Inline)

**Responsibilities:**
- Cache tokens in memory
- Check token expiry with configurable buffer
- Provide authentication headers

**Token Expiry Logic:**
```python
TOKEN_EXPIRY_BUFFER_SECONDS = 60.0

def _is_token_expired(self, buffer_seconds: float = TOKEN_EXPIRY_BUFFER_SECONDS) -> bool:
    if not self._oauth_credentials:
        return True
    
    expires = self._oauth_credentials.get("expires")
    if not isinstance(expires, (int, float)):
        return False  # No expiry = don't assume expired
    
    # Handle both seconds and milliseconds timestamps
    if expires > 1e12:  # Likely milliseconds
        expires = expires / 1000.0
    
    return time.time() >= (expires - buffer_seconds)
```

### Data Flow

#### Initialization Flow

```
1. initialize() called
   │
   ├─> _get_credentials_path()
   │   └─> Determine XDG-compliant path
   │
   ├─> _load_oauth_credentials()
   │   ├─> Read auth.json
   │   ├─> Parse JSON
   │   ├─> Extract "opencode" provider credentials
   │   └─> Validate structure (type="oauth", access, refresh, expires)
   │
   ├─> _is_token_expired()
   │   └─> Check if token needs refresh
   │
   ├─> Set is_functional = True (if credentials valid)
   │
   └─> (Optional) Start file watcher
```

#### Request Flow

```
1. chat_completions() called
   │
   ├─> Check is_functional
   │   └─> If False, raise BackendError
   │
   ├─> Check _is_token_expired()
   │   └─> If expired, reload credentials from file
   │
   ├─> get_headers()
   │   └─> Return {"Authorization": f"Bearer {access_token}"}
   │
   └─> Call parent OpenAIConnector.chat_completions()
       └─> HTTP request to api.gateway.opencode.ai/v1/chat/completions
```

### File Structure

```
src/connectors/
├── opencode_zen.py           # Main connector implementation
└── utils/
    └── (no new files needed - inline implementation)

tests/
├── unit/
│   └── connectors/
│       └── test_opencode_zen_connector.py
└── integration/
    └── test_opencode_zen_integration.py (optional)
```

## Detailed Component Specifications

### OpencodeZenConnector Class

#### Constructor

```python
def __init__(
    self,
    client: httpx.AsyncClient,
    config: AppConfig,
    translation_service: TranslationService | None = None,
) -> None:
    super().__init__(client, config, translation_service=translation_service)
    self.name = "opencode-zen"
    self._default_endpoint = "https://api.gateway.opencode.ai/v1"
    self.is_functional = False
    self._oauth_credentials: dict[str, Any] | None = None
    self._credentials_path: Path | None = None
    self._last_modified: float = 0
    self._token_lock = asyncio.Lock()
    self._file_observer: BaseObserver | None = None
    self._credential_validation_errors: list[str] = []
```

#### Initialization Method

```python
async def initialize(self, **kwargs: Any) -> None:
    """Initialize backend with credential loading and validation."""
    logger.info("Initializing OpenCode Zen backend...")
    
    # Reset state
    self._credential_validation_errors = []
    self.is_functional = False
    
    # Step 1: Determine credentials path
    custom_path = kwargs.get("credentials_path") or os.getenv("OPENCODE_AUTH_PATH")
    self._credentials_path = (
        Path(custom_path).expanduser() if custom_path 
        else self._get_default_credentials_path()
    )
    
    # Step 2: Load credentials
    if not await self._load_oauth_credentials():
        self._credential_validation_errors.append(
            f"Failed to load credentials from {self._credentials_path}. "
            "Run 'opencode auth login' to authenticate."
        )
        return
    
    # Step 3: Validate token
    if self._is_token_expired(buffer_seconds=0):
        logger.warning("OpenCode OAuth token is expired")
        self._credential_validation_errors.append("OAuth token is expired")
        # Still allow initialization - token might be refreshed by file change
    
    # Step 4: Set API endpoint
    self.api_base_url = kwargs.get("api_base_url", self._default_endpoint)
    
    # Step 5: Configure available models
    self.available_models = [
        "anthropic/claude-sonnet-4",
        "openai/gpt-4.1",
        "zhipuai/glm-4.5-flash",
    ]
    
    # Step 6: Start file watching (optional)
    if kwargs.get("enable_file_watching", True):
        self._start_file_watching()
    
    # Mark as functional
    self.is_functional = True
    logger.info(
        "OpenCode Zen backend initialized with %d models",
        len(self.available_models)
    )
```

#### Credentials Loading

```python
async def _load_oauth_credentials(self) -> bool:
    """Load OAuth credentials from auth.json file."""
    try:
        if not self._credentials_path or not self._credentials_path.exists():
            logger.warning(
                "OpenCode credentials not found at %s", 
                self._credentials_path
            )
            return False
        
        # Check modification time for caching
        current_mtime = self._credentials_path.stat().st_mtime
        if current_mtime == self._last_modified and self._oauth_credentials:
            return True
        
        self._last_modified = current_mtime
        
        with open(self._credentials_path, encoding="utf-8") as f:
            all_credentials = json.load(f)
        
        # Extract provider-specific credentials
        provider_creds = all_credentials.get("opencode")
        if not provider_creds:
            logger.warning("No 'opencode' provider found in auth.json")
            return False
        
        # Validate structure
        if provider_creds.get("type") != "oauth":
            logger.warning("OpenCode credentials are not OAuth type")
            return False
        
        required_fields = ["access", "refresh", "expires"]
        for field in required_fields:
            if field not in provider_creds:
                logger.warning("Missing field '%s' in OpenCode credentials", field)
                return False
        
        self._oauth_credentials = provider_creds
        logger.info("Successfully loaded OpenCode OAuth credentials")
        return True
        
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in OpenCode credentials: %s", e)
        return False
    except Exception as e:
        logger.error("Error loading OpenCode credentials: %s", e)
        return False
```

#### Authentication Headers

```python
def get_headers(self, identity: IAppIdentityConfig | None = None) -> dict[str, str]:
    """Override to use OAuth access token for authentication."""
    if not self._oauth_credentials or not self._oauth_credentials.get("access"):
        raise AuthenticationError(
            message="No valid OpenCode OAuth access token available. "
                    "Please run 'opencode auth login' to authenticate.",
            details={"backend": "opencode-zen"},
        )
    
    headers = {
        "Authorization": f"Bearer {self._oauth_credentials['access']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    return ensure_loop_guard_header(headers)
```

#### Chat Completions Override

```python
async def chat_completions(
    self,
    request_data: DomainModel | InternalDTO | dict[str, Any],
    processed_messages: list[Any],
    effective_model: str,
    identity: IAppIdentityConfig | None = None,
    **kwargs: Any,
) -> ResponseEnvelope | StreamingResponseEnvelope:
    """Handle chat completions with credential validation."""
    
    # Validate backend is functional
    if not self.is_functional:
        errors = "; ".join(self._credential_validation_errors) or "Backend not initialized"
        raise BackendError(
            message=f"OpenCode Zen backend is not functional: {errors}",
            backend_name="opencode-zen",
        )
    
    # Check token expiry and reload if needed
    if self._is_token_expired():
        logger.info("Token expired, reloading credentials...")
        if not await self._load_oauth_credentials():
            raise AuthenticationError(
                message="Failed to reload OpenCode credentials after token expiry",
                details={"backend": "opencode-zen"},
            )
        if self._is_token_expired(buffer_seconds=0):
            raise AuthenticationError(
                message="OpenCode OAuth token is expired. "
                        "Please run 'opencode auth login' to re-authenticate.",
                details={"backend": "opencode-zen"},
            )
    
    # Strip vendor prefix from model if present
    model_name = effective_model
    if model_name.startswith("opencode-zen/"):
        model_name = model_name[len("opencode-zen/"):]
    
    # Call parent implementation
    return await super().chat_completions(
        request_data=request_data,
        processed_messages=processed_messages,
        effective_model=model_name,
        identity=identity,
        **kwargs,
    )
```

### Error Handling Strategy

| Error Condition | Exception Type | User Message |
|-----------------|----------------|--------------|
| Credentials file not found | `AuthenticationError` | "OpenCode credentials not found. Run 'opencode auth login' to authenticate." |
| Invalid JSON in auth.json | `AuthenticationError` | "Invalid OpenCode credentials file format." |
| Missing 'opencode' provider | `AuthenticationError` | "No OpenCode provider found in credentials. Run 'opencode auth login'." |
| Token expired | `AuthenticationError` | "OpenCode OAuth token expired. Run 'opencode auth login' to re-authenticate." |
| Missing access token | `AuthenticationError` | "No valid access token available." |
| API communication failure | `BackendError` | "Failed to communicate with OpenCode Zen gateway." |
| Backend not functional | `BackendError` | "OpenCode Zen backend is not functional: [specific errors]" |

### Configuration Options

| Option | Environment Variable | Config Key | Default |
|--------|---------------------|------------|---------|
| Credentials path | `OPENCODE_AUTH_PATH` | `credentials_path` | OS-specific (see below) |
| API base URL | `OPENCODE_ZEN_API_URL` | `api_base_url` | `https://api.gateway.opencode.ai/v1` |
| Enable file watching | `OPENCODE_ZEN_WATCH_FILE` | `enable_file_watching` | `true` |
| Request timeout | - | `timeout` | `120.0` |

**Default Credentials Path by Platform:**
- **Windows**: `%LOCALAPPDATA%\opencode\auth.json`
- **Linux**: `$XDG_DATA_HOME/opencode/auth.json` or `~/.local/share/opencode/auth.json`
- **macOS**: `$XDG_DATA_HOME/opencode/auth.json` or `~/.local/share/opencode/auth.json`

### Model Name Mapping

| Incoming Model | Sent to Gateway |
|----------------|-----------------|
| `opencode-zen/anthropic/claude-sonnet-4` | `anthropic/claude-sonnet-4` |
| `anthropic/claude-sonnet-4` | `anthropic/claude-sonnet-4` |
| `opencode-zen/openai/gpt-4.1` | `openai/gpt-4.1` |
| `openai/gpt-4.1` | `openai/gpt-4.1` |

## Testing Strategy

### Unit Tests

1. **Credential Loading Tests**
   - Test successful credential loading
   - Test file not found handling
   - Test invalid JSON handling
   - Test missing provider key
   - Test missing required fields

2. **Token Management Tests**
   - Test token expiry detection (seconds vs milliseconds timestamps)
   - Test token expiry buffer
   - Test credential caching with mtime

3. **Header Generation Tests**
   - Test correct Authorization header format
   - Test missing token handling

4. **Model Routing Tests**
   - Test vendor prefix stripping
   - Test available models list

5. **Cross-Platform Path Resolution Tests (CRITICAL)**
   - Test Windows path resolution with `LOCALAPPDATA` set
   - Test Windows path resolution with `LOCALAPPDATA` not set (fallback)
   - Test Linux path resolution with `XDG_DATA_HOME` set
   - Test Linux path resolution with `XDG_DATA_HOME` not set (fallback)
   - Test macOS path resolution (similar to Linux)
   - Mock `os.name`, `sys.platform`, and environment variables for each test
   - Verify `Path.home()` is used correctly for fallbacks
   - Verify `pathlib.Path` is used for all path construction

### Integration Tests

1. **End-to-end request flow** (mocked gateway)
2. **File watching trigger** (file modification detection)
3. **Error recovery scenarios**

## Security Considerations

1. **Credential Storage**: Credentials are stored in user-only readable file (`chmod 600`)
2. **Token Handling**: Access tokens are never logged, only masked
3. **Memory Safety**: Credentials are cleared from memory when connector is destroyed
4. **Path Traversal**: Credential path is validated and canonicalized

## Implementation Phases

### Phase 1: Core Implementation
- [ ] Create `OpencodeZenConnector` class
- [ ] Implement credential loading
- [ ] Implement token expiry checking
- [ ] Implement header generation
- [ ] Register in backend registry

### Phase 2: Integration
- [ ] Implement chat_completions override
- [ ] Add model routing logic
- [ ] Add configuration support

### Phase 3: Robustness
- [ ] Add file watching (optional)
- [ ] Add comprehensive error handling
- [ ] Add logging

### Phase 4: Testing
- [ ] Write unit tests
- [ ] Write integration tests
- [ ] Manual testing with real credentials

## Dependencies

- **Existing**: `httpx`, `asyncio`, `json`, `pathlib`, `logging`
- **Optional**: `watchdog` (for file watching, already used by qwen_oauth)
- **No new dependencies required**
