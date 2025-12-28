# Implementation Tasks: opencode-zen-connector

## Overview

This document outlines the implementation tasks for the OpenCode Zen backend connector, **organized following Test-Driven Development (TDD) methodology**.

### TDD Approach

Each feature follows the Red-Green-Refactor cycle:

1. **RED**: Write failing tests first
2. **GREEN**: Write minimal implementation to pass tests
3. **REFACTOR**: Improve code while keeping tests passing

---

## Phase 1: Test Infrastructure Setup

### TASK-1: Create Test File and Fixtures

**Priority:** High | **Estimated Effort:** 20 min | **Requirements:** REQ-10 | **Status:** Completed

**Description:**
Set up the test file structure and common fixtures for all connector tests.

**Acceptance Criteria:**

- [x] Create `tests/unit/connectors/test_opencode_zen_connector.py`
- [x] Create pytest fixtures for mock credentials
- [x] Create fixtures for mock httpx client
- [x] Create fixtures for mock config
- [x] Create helper functions for temporary credential files

**Implementation Details:**

```python
# tests/unit/connectors/test_opencode_zen_connector.py
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

@pytest.fixture
def mock_credentials():
    return {
        "opencode": {
            "type": "oauth",
            "access": "test-access-token",
            "refresh": "test-refresh-token",
            "expires": int(time.time()) + 3600  # 1 hour from now
        }
    }

@pytest.fixture
def temp_credentials_file(tmp_path, mock_credentials):
    creds_file = tmp_path / "auth.json"
    creds_file.write_text(json.dumps(mock_credentials))
    return creds_file
```

---

## Phase 2: Cross-Platform Path Resolution (TDD)

### TASK-2: Write Cross-Platform Path Resolution Tests

**Priority:** High | **Estimated Effort:** 45 min | **Requirements:** REQ-2, REQ-10 | **Status:** Completed

**Description:**
Write comprehensive tests for OS-agnostic path resolution BEFORE implementing the method.

**Test Cases (RED phase):**

- [x] Test Windows path with LOCALAPPDATA set
- [x] Test Windows path with LOCALAPPDATA not set (fallback to Path.home())
- [x] Test Linux path with XDG_DATA_HOME set
- [x] Test Linux path with XDG_DATA_HOME not set (fallback)
- [x] Test macOS path (similar to Linux)
- [x] Test that pathlib.Path is used (not string concatenation)
- [x] Test that Path.home() is used for home directory

**Implementation Details:**

```python
class TestCrossPlatformPathResolution:
    """Tests for _get_default_credentials_path() - WRITE THESE FIRST"""
    
    def test_windows_path_with_localappdata(self, connector):
        """Windows should use LOCALAPPDATA when set."""
        with patch.dict(os.environ, {"LOCALAPPDATA": "C:\\Users\\test\\AppData\\Local"}):
            with patch("sys.platform", "win32"):
                path = connector._get_default_credentials_path()
                assert path == Path("C:/Users/test/AppData/Local/opencode/auth.json")
    
    def test_windows_path_fallback(self, connector):
        """Windows should fallback to Path.home() when LOCALAPPDATA not set."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.platform", "win32"):
                with patch("pathlib.Path.home", return_value=Path("C:/Users/testuser")):
                    path = connector._get_default_credentials_path()
                    assert path == Path("C:/Users/testuser/AppData/Local/opencode/auth.json")
    
    def test_linux_path_with_xdg_data_home(self, connector):
        """Linux should use XDG_DATA_HOME when set."""
        with patch.dict(os.environ, {"XDG_DATA_HOME": "/custom/data"}):
            with patch("sys.platform", "linux"):
                with patch("os.name", "posix"):
                    path = connector._get_default_credentials_path()
                    assert path == Path("/custom/data/opencode/auth.json")
    
    def test_linux_path_fallback(self, connector):
        """Linux should fallback to ~/.local/share when XDG_DATA_HOME not set."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.platform", "linux"):
                with patch("os.name", "posix"):
                    with patch("pathlib.Path.home", return_value=Path("/home/testuser")):
                        path = connector._get_default_credentials_path()
                        assert path == Path("/home/testuser/.local/share/opencode/auth.json")
    
    def test_macos_path_fallback(self, connector):
        """macOS should use same fallback as Linux."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.platform", "darwin"):
                with patch("os.name", "posix"):
                    with patch("pathlib.Path.home", return_value=Path("/Users/testuser")):
                        path = connector._get_default_credentials_path()
                        assert path == Path("/Users/testuser/.local/share/opencode/auth.json")
    
    def test_returns_path_object(self, connector):
        """Method should return pathlib.Path, not string."""
        path = connector._get_default_credentials_path()
        assert isinstance(path, Path)
```

---

### TASK-3: Implement Cross-Platform Path Resolution

**Priority:** High | **Estimated Effort:** 30 min | **Requirements:** REQ-2 | **Status:** Completed

**Description:**
Implement `_get_default_credentials_path()` to pass all tests from TASK-2 (GREEN phase).

**Acceptance Criteria:**

- [x] All tests from TASK-2 pass
- [x] Use `sys.platform == "win32"` or `os.name == "nt"` for Windows detection
- [x] Use `os.environ.get("LOCALAPPDATA")` for Windows
- [x] Use `Path.home() / "AppData" / "Local"` as Windows fallback
- [x] Use `os.environ.get("XDG_DATA_HOME")` for Linux/macOS
- [x] Use `Path.home() / ".local" / "share"` as Linux/macOS fallback
- [x] Use `pathlib.Path` for ALL path operations

**Implementation:**

```python
def _get_default_credentials_path(self) -> Path:
    """Determine credentials path in OS-agnostic way."""
    # Windows: Use LOCALAPPDATA
    if sys.platform == "win32" or os.name == "nt":
        localappdata = os.environ.get("LOCALAPPDATA")
        if localappdata:
            return Path(localappdata) / "opencode" / "auth.json"
        return Path.home() / "AppData" / "Local" / "opencode" / "auth.json"
    
    # Linux/macOS: Use XDG_DATA_HOME or default
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / "opencode" / "auth.json"
    
    return Path.home() / ".local" / "share" / "opencode" / "auth.json"
```

---

## Phase 3: Credentials Loading (TDD)

### TASK-4: Write Credentials Loading Tests

**Priority:** High | **Estimated Effort:** 45 min | **Requirements:** REQ-2, REQ-10 | **Status:** Completed

**Description:**
Write tests for credential file loading BEFORE implementing.

**Test Cases (RED phase):**

- [x] Test successful credential loading from valid file
- [x] Test file not found returns False
- [x] Test invalid JSON returns False
- [x] Test missing "opencode" provider key returns False
- [x] Test missing "access" field returns False
- [x] Test missing "refresh" field returns False
- [x] Test missing "expires" field returns False
- [x] Test non-oauth type returns False
- [x] Test file mtime caching (no reload if unchanged)
- [x] Test credentials stored in _oauth_credentials

**Implementation Details:**

```python
class TestCredentialsLoading:
    """Tests for _load_oauth_credentials() - WRITE THESE FIRST"""
    
    @pytest.mark.asyncio
    async def test_successful_load(self, connector, temp_credentials_file):
        connector._credentials_path = temp_credentials_file
        result = await connector._load_oauth_credentials()
        assert result is True
        assert connector._oauth_credentials["access"] == "test-access-token"
    
    @pytest.mark.asyncio
    async def test_file_not_found(self, connector, tmp_path):
        connector._credentials_path = tmp_path / "nonexistent.json"
        result = await connector._load_oauth_credentials()
        assert result is False
    
    @pytest.mark.asyncio
    async def test_invalid_json(self, connector, tmp_path):
        bad_file = tmp_path / "auth.json"
        bad_file.write_text("not valid json {{{")
        connector._credentials_path = bad_file
        result = await connector._load_oauth_credentials()
        assert result is False
    
    # ... more tests
```

---

### TASK-5: Implement Credentials Loading

**Priority:** High | **Estimated Effort:** 45 min | **Requirements:** REQ-2, REQ-3 | **Status:** Completed

**Description:**
Implement `_load_oauth_credentials()` to pass all tests from TASK-4 (GREEN phase).

**Acceptance Criteria:**

- [x] All tests from TASK-4 pass
- [x] Read file using Path object
- [x] Parse JSON safely with error handling
- [x] Extract "opencode" provider credentials
- [x] Validate required fields (type, access, refresh, expires)
- [x] Implement mtime caching

---

## Phase 4: Token Management (TDD)

### TASK-6: Write Token Expiry Tests

**Priority:** High | **Estimated Effort:** 30 min | **Requirements:** REQ-3, REQ-10 | **Status:** Completed

**Description:**
Write tests for token expiry detection BEFORE implementing.

**Test Cases (RED phase):**

- [x] Test token not expired (future expiry)
- [x] Test token expired (past expiry)
- [x] Test token expiring within buffer (should be considered expired)
- [x] Test milliseconds timestamp (> 1e12)
- [x] Test seconds timestamp
- [x] Test missing expires field returns False
- [x] Test no credentials returns True (expired)
- [x] Test custom buffer value

**Implementation Details:**

```python
class TestTokenExpiry:
    """Tests for _is_token_expired() - WRITE THESE FIRST"""
    
    def test_token_not_expired(self, connector):
        connector._oauth_credentials = {"expires": time.time() + 3600}
        assert connector._is_token_expired() is False
    
    def test_token_expired(self, connector):
        connector._oauth_credentials = {"expires": time.time() - 100}
        assert connector._is_token_expired() is True
    
    def test_token_within_buffer_is_expired(self, connector):
        connector._oauth_credentials = {"expires": time.time() + 30}  # Within 60s buffer
        assert connector._is_token_expired() is True
    
    def test_milliseconds_timestamp(self, connector):
        connector._oauth_credentials = {"expires": (time.time() + 3600) * 1000}
        assert connector._is_token_expired() is False
```

---

### TASK-7: Implement Token Expiry Checking

**Priority:** High | **Estimated Effort:** 20 min | **Requirements:** REQ-3 | **Status:** Completed

**Description:**
Implement `_is_token_expired()` to pass all tests from TASK-6 (GREEN phase).

**Acceptance Criteria:**

- [x] All tests from TASK-6 pass
- [x] Handle both seconds and milliseconds timestamps
- [x] Apply configurable buffer (default 60s)
- [x] Return True if no credentials

---

## Phase 5: Authentication Headers (TDD)

### TASK-8: Write Authentication Header Tests

**Priority:** High | **Estimated Effort:** 30 min | **Requirements:** REQ-3, REQ-4, REQ-10 | **Status:** Completed

**Description:**
Write tests for header generation BEFORE implementing.

**Test Cases (RED phase):**

- [x] Test correct Authorization header format (Bearer token)
- [x] Test Content-Type header present
- [x] Test Accept header present
- [x] Test AuthenticationError when no credentials
- [x] Test AuthenticationError when no access token

**Implementation Details:**

```python
class TestAuthenticationHeaders:
    """Tests for get_headers() - WRITE THESE FIRST"""
    
    def test_correct_authorization_header(self, connector):
        connector._oauth_credentials = {"access": "my-token"}
        headers = connector.get_headers()
        assert headers["Authorization"] == "Bearer my-token"
    
    def test_missing_credentials_raises_error(self, connector):
        connector._oauth_credentials = None
        with pytest.raises(AuthenticationError):
            connector.get_headers()
```

---

### TASK-9: Implement Authentication Headers

**Priority:** High | **Estimated Effort:** 20 min | **Requirements:** REQ-3, REQ-4 | **Status:** Completed

**Description:**
Implement `get_headers()` to pass all tests from TASK-8 (GREEN phase).

**Acceptance Criteria:**

- [x] All tests from TASK-8 pass
- [x] Return Bearer token in Authorization header
- [x] Include Content-Type and Accept headers
- [x] Raise AuthenticationError when no token

---

## Phase 6: Connector Class Structure (TDD)

### TASK-10: Write Connector Class Tests

**Priority:** High | **Estimated Effort:** 20 min | **Requirements:** REQ-1, REQ-10 | **Status:** Completed

**Description:**
Write tests for basic connector structure BEFORE implementing skeleton.

**Test Cases (RED phase):**

- [x] Test backend_type is "opencode-zen"
- [x] Test VENDOR_PREFIX is "opencode-zen"
- [x] Test extends OpenAIConnector
- [x] Test default endpoint URL
- [x] Test initial state (is_functional = False)

---

### TASK-11: Create OpencodeZenConnector Class Skeleton

**Priority:** High | **Estimated Effort:** 30 min | **Requirements:** REQ-1 | **Status:** Completed

**Description:**
Create the main connector class to pass tests from TASK-10 (GREEN phase).

**Acceptance Criteria:**

- [x] All tests from TASK-10 pass
- [x] Create `src/connectors/opencode_zen.py`
- [x] Define class extending `OpenAIConnector`
- [x] Set backend_type and VENDOR_PREFIX
- [x] Define all instance attributes

---

### TASK-12: Implement Backend Registry Registration

**Priority:** High | **Estimated Effort:** 10 min | **Requirements:** REQ-1 | **Status:** Completed

**Description:**
Register connector in backend registry.

**Acceptance Criteria:**

- [x] Add registration at end of module
- [x] Verify connector can be retrieved from registry

---

## Phase 7: Initialization (TDD)

### TASK-13: Write Initialization Tests

**Priority:** High | **Estimated Effort:** 45 min | **Requirements:** REQ-6, REQ-10 | **Status:** Completed

**Description:**
Write tests for connector initialization BEFORE implementing.

**Test Cases (RED phase):**

- [x] Test successful initialization with valid credentials
- [x] Test initialization with missing credentials
- [x] Test initialization with expired token
- [x] Test custom credentials path from kwargs
- [x] Test custom credentials path from environment variable
- [x] Test custom API endpoint
- [x] Test is_functional flag set correctly
- [x] Test available_models populated

---

### TASK-14: Implement Initialize Method

**Priority:** High | **Estimated Effort:** 45 min | **Requirements:** REQ-6, REQ-9 | **Status:** Completed

**Description:**
Implement `initialize()` to pass all tests from TASK-13 (GREEN phase).

**Acceptance Criteria:**

- [x] All tests from TASK-13 pass
- [x] Support custom credentials path
- [x] Load and validate credentials
- [x] Set is_functional appropriately

---

## Phase 8: Chat Completions (TDD)

### TASK-15: Write Chat Completions Tests

**Priority:** High | **Estimated Effort:** 45 min | **Requirements:** REQ-4, REQ-5, REQ-10 | **Status:** Completed

**Description:**
Write tests for chat_completions override BEFORE implementing.

**Test Cases (RED phase):**

- [x] Test raises error when not functional
- [x] Test reloads credentials when token expired
- [x] Test strips "opencode-zen/" prefix from model
- [x] Test passes through to parent method
- [x] Test error handling for auth failures

---

### TASK-16: Implement Chat Completions Override

**Priority:** High | **Estimated Effort:** 30 min | **Requirements:** REQ-4, REQ-5 | **Status:** Completed

**Description:**
Implement `chat_completions()` to pass all tests from TASK-15 (GREEN phase).

---

## Phase 9: Supporting Features (TDD)

### TASK-17: Write Model List Tests and Implementation

**Priority:** Medium | **Estimated Effort:** 30 min | **Requirements:** REQ-5, REQ-10 | **Status:** Completed

**Description:**
TDD cycle for `get_available_models()`.

**Test Cases:**

- [x] Test returns empty list when not functional
- [x] Test returns prefixed models when functional
- [x] Test includes all supported models

---

### TASK-18: Write Health Check Tests and Implementation

**Priority:** Medium | **Estimated Effort:** 30 min | **Requirements:** REQ-6, REQ-10 | **Status:** Completed

**Description:**
TDD cycle for health check functionality.

---

### TASK-19: Write Validation Errors Tests and Implementation

**Priority:** Medium | **Estimated Effort:** 20 min | **Requirements:** REQ-8, REQ-10 | **Status:** Completed

**Description:**
TDD cycle for `get_validation_errors()` and `is_backend_functional()`.

---

## Phase 10: Robustness

### TASK-20: Add Comprehensive Logging

**Priority:** Medium | **Estimated Effort:** 20 min | **Requirements:** REQ-8 | **Status:** Completed

**Description:**
Add logging throughout the connector (REFACTOR phase).

**Acceptance Criteria:**

- [x] Log INFO on successful initialization
- [x] Log WARNING on expired tokens
- [x] Log ERROR on failures
- [x] Never log actual token values

---

### TASK-21: Implement File Watching (Optional)

**Priority:** Low | **Estimated Effort:** 45 min | **Requirements:** REQ-7 | **Status:** Completed

**Description:**
Optional file watching for credential changes.

---

## Phase 11: Integration Tests

### TASK-22: Write Integration Tests

**Priority:** Medium | **Estimated Effort:** 60 min | **Requirements:** REQ-10 | **Status:** Completed

**Description:**
Write integration tests for end-to-end flows.

**Test Cases:**

- [x] Test full initialization and chat completion flow
- [x] Test streaming response handling
- [x] Test error recovery scenarios

**File:** `tests/integration/test_opencode_zen_integration.py`

---

## Phase 12: Documentation

### TASK-23: Create Backend User Documentation

**Priority:** Medium | **Estimated Effort:** 45 min | **Requirements:** REQ-8 | **Status:** Completed

**Description:**
Create user-facing documentation for the opencode-zen backend following the existing documentation patterns.

**Acceptance Criteria:**

- [x] Create `docs/user_guide/backends/opencode-zen.md`
- [x] Follow format of existing backend docs (e.g., `cline.md`, `qwen-oauth.md`)
- [x] Include sections:
  - Overview and purpose
  - Prerequisites (opencode CLI installed, authenticated)
  - Authentication setup (`opencode auth login` instructions)
  - Configuration options (credentials path, API endpoint, environment variables)
  - Supported models list
  - Usage examples
  - Troubleshooting common issues
- [x] Document platform-specific credential paths (Windows, Linux, macOS)
- [x] Add cross-references to opencode documentation

**Documentation Structure:**

```markdown
# OpenCode Zen Backend

## Overview
The opencode-zen backend connects to OpenCode's Zen gateway...

## Prerequisites
- OpenCode CLI installed
- Authenticated via `opencode auth login`

## Configuration
| Option | Environment Variable | Default |
|--------|---------------------|---------|
| ... | ... | ... |

## Supported Models
- anthropic/claude-sonnet-4
- openai/gpt-4.1
- zhipuai/glm-4.5-flash

## Credential Locations
| Platform | Path |
|----------|------|
| Windows | %LOCALAPPDATA%\opencode\auth.json |
| Linux | ~/.local/share/opencode/auth.json |
| macOS | ~/.local/share/opencode/auth.json |

## Troubleshooting
...
```

---

## Task Execution Order (TDD)

```
1. TASK-1  (Test Infrastructure)
2. TASK-2  (Path Resolution Tests)      ─┐
3. TASK-3  (Path Resolution Impl)       ─┘ TDD Cycle
4. TASK-4  (Credentials Loading Tests)  ─┐
5. TASK-5  (Credentials Loading Impl)   ─┘ TDD Cycle
6. TASK-6  (Token Expiry Tests)         ─┐
7. TASK-7  (Token Expiry Impl)          ─┘ TDD Cycle
8. TASK-8  (Auth Headers Tests)         ─┐
9. TASK-9  (Auth Headers Impl)          ─┘ TDD Cycle
10. TASK-10 (Connector Class Tests)     ─┐
11. TASK-11 (Connector Class Impl)      ─┘ TDD Cycle
12. TASK-12 (Registry Registration)
13. TASK-13 (Initialize Tests)          ─┐
14. TASK-14 (Initialize Impl)           ─┘ TDD Cycle
15. TASK-15 (Chat Completions Tests)    ─┐
16. TASK-16 (Chat Completions Impl)     ─┘ TDD Cycle
17. TASK-17 (Model List - Full TDD)
18. TASK-18 (Health Check - Full TDD)
19. TASK-19 (Validation Errors - Full TDD)
20. TASK-20 (Logging - Refactor)
21. TASK-21 (File Watching - Optional)
22. TASK-22 (Integration Tests)
23. TASK-23 (User Documentation)
```

---

## Summary

| Phase | Tasks | TDD Pattern |
|-------|-------|-------------|
| Phase 1: Test Infrastructure | TASK-1 | Setup |
| Phase 2: Path Resolution | TASK-2, TASK-3 | RED → GREEN |
| Phase 3: Credentials Loading | TASK-4, TASK-5 | RED → GREEN |
| Phase 4: Token Management | TASK-6, TASK-7 | RED → GREEN |
| Phase 5: Auth Headers | TASK-8, TASK-9 | RED → GREEN |
| Phase 6: Connector Class | TASK-10, TASK-11, TASK-12 | RED → GREEN |
| Phase 7: Initialization | TASK-13, TASK-14 | RED → GREEN |
| Phase 8: Chat Completions | TASK-15, TASK-16 | RED → GREEN |
| Phase 9: Supporting Features | TASK-17-19 | RED → GREEN |
| Phase 10: Robustness | TASK-20, TASK-21 | REFACTOR |
| Phase 11: Integration | TASK-22 | E2E Testing |
| Phase 12: Documentation | TASK-23 | Docs |

**Total Tasks:** 23
**TDD Cycles:** 9 (test-first pairs)
**Refactor Tasks:** 2
**Integration Tasks:** 1
**Documentation Tasks:** 1
