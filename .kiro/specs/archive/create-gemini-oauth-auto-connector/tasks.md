# Implementation Plan: Gemini OAuth Auto-Connector

## Overview

This implementation plan breaks down the `gemini-oauth-auto` connector into ordered tasks following TDD principles. Tasks are organized to build foundational components first, then compose them into the connector.

**Estimated Effort**: 3-5 days  
**Risk Level**: Low (extends existing, well-tested base class)

---

## Phase 1: Foundation (Models, Constants, Errors)

### Task 1: Create Package Structure and Constants

- [x] 1.1 Create package directory structure (P)
  - Create `src/connectors/gemini_oauth_auto/` package
  - Create `__init__.py` with public exports
  - _Requirements: 1, 2, 3, 9_

- [x] 1.2 Define OAuth constants module (P)
  - Create `src/connectors/gemini_oauth_auto/constants.py`
  - Define `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET` (from gemini-cli)
  - Define `AUTH_URL`, `TOKEN_URL`, `USERINFO_URL`
  - Define `OAUTH_SCOPES` list
  - Define `SUCCESS_REDIRECT`, `FAILURE_REDIRECT` URLs
  - _Requirements: 1, 3_

- [x] 1.3 Define error classes (P)
  - Create `src/connectors/gemini_oauth_auto/errors.py`
  - Define `OAuthError(Exception)` for script-only errors
  - Define `TokenRefreshError(LLMProxyError)` with `needs_reauth` flag
  - Define `NoValidAccountsError(LLMProxyError)`
  - _Requirements: 3, 4, 9_

### Task 2: Define Data Models

- [x] 2.1 Create Pydantic models module
  - Create `src/connectors/gemini_oauth_auto/models.py`
  - Define `StoredAccount(BaseModel)` with all fields:
    - `account_id`, `email`, `access_token`, `refresh_token`
    - `token_type`, `scope`, `expiry_date` (milliseconds)
    - `created_at`, `updated_at`, `last_used`, `needs_reauth`
  - Implement `is_expired(buffer_ms)` method
  - Implement `to_credentials_dict()` method
  - Implement `status` property
  - Define `AccountSummary(BaseModel)` for list display
  - Add `ACCOUNT_ID_PATTERN` validation regex
  - _Requirements: 2_

- [x] 2.2 Write unit tests for models
  - Create `tests/unit/connectors/gemini_oauth_auto/test_models.py`
  - Test `is_expired()` with various buffer values
  - Test `to_credentials_dict()` output format
  - Test `status` property: valid/expired/needs_reauth
  - Test account_id validation regex
  - _Requirements: 2_

---

## Phase 2: Service Interfaces

### Task 3: Define Service Interfaces

- [x] 3.1 Create ITokenStorage interface (P)
  - Create `src/connectors/gemini_oauth_auto/interfaces.py`
  - Define `ITokenStorage(ABC)` with methods:
    - `async load_all_accounts() -> list[StoredAccount]`
    - `async get_account(account_id: str) -> StoredAccount | None`
    - `async save_account(account: StoredAccount) -> None`
    - `async delete_account(account_id: str) -> bool`
    - `async list_accounts() -> list[AccountSummary]`
  - Document preconditions/postconditions
  - _Requirements: 2, 5, 8_

- [x] 3.2 Create ITokenRefresh interface (P)
  - Add to `src/connectors/gemini_oauth_auto/interfaces.py`
  - Define `ITokenRefresh(ABC)` with methods:
    - `async refresh_if_needed(account, buffer_ms) -> StoredAccount`
    - `async force_refresh(account) -> StoredAccount`
  - Document exception contracts (TokenRefreshError)
  - _Requirements: 3_

- [x] 3.3 Create IAccountSelector interface (P)
  - Add to `src/connectors/gemini_oauth_auto/interfaces.py`
  - Define `IAccountSelector(ABC)` with methods:
    - `async get_next_account() -> StoredAccount | None`
    - `get_current_account() -> StoredAccount | None`
    - `async rotate_on_quota() -> StoredAccount | None`
    - `get_available_count() -> int`
  - _Requirements: 4_

---

## Phase 3: Service Implementations

### Task 4: Implement TokenStorageService

- [x] 4.1 Write unit tests for TokenStorageService FIRST (TDD Red)
  - Create `tests/unit/connectors/gemini_oauth_auto/test_token_storage.py`
  - Test `load_all_accounts()` with valid files
  - Test `load_all_accounts()` skips corrupted files
  - Test `save_account()` atomic write (temp + rename)
  - Test `save_account()` sets restrictive permissions
  - Test `get_account()` returns None for missing
  - Test `delete_account()` removes file
  - Test directory auto-creation
  - _Requirements: 2, 5, 8_

- [x] 4.2 Implement TokenStorageService (TDD Green)
  - Create `src/connectors/gemini_oauth_auto/token_storage.py`
  - Implement `TokenStorageService(ITokenStorage)`
  - Constructor accepts `storage_path: Path`
  - Implement atomic writes via temp file + rename
  - Set file permissions 0o600 on POSIX
  - Log warnings for corrupted files, don't raise
  - Use `aiofiles` for async file I/O
  - _Requirements: 2, 5, 8_

- [x] 4.3 Verify tests pass (TDD Refactor)
  - Run unit tests: `.venv\Scripts\python.exe -m pytest tests/unit/connectors/gemini_oauth_auto/test_token_storage.py -v`
  - Fix any failures
  - Run QA checks on `token_storage.py`
  - _Requirements: 2_

### Task 5: Implement TokenRefreshService

- [x] 5.1 Write unit tests for TokenRefreshService FIRST (TDD Red)
  - Create `tests/unit/connectors/gemini_oauth_auto/test_token_refresh.py`
  - Test `refresh_if_needed()` returns unchanged if not expired
  - Test `refresh_if_needed()` refreshes when within buffer
  - Test `force_refresh()` always refreshes
  - Test `invalid_grant` error sets `needs_reauth=True`
  - Test retry with exponential backoff (mock delays)
  - Test concurrent refresh prevention (lock behavior)
  - Mock `httpx.AsyncClient` responses
  - _Requirements: 3_

- [x] 5.2 Implement TokenRefreshService (TDD Green)
  - Create `src/connectors/gemini_oauth_auto/token_refresh.py`
  - Implement `TokenRefreshService(ITokenRefresh)`
  - Constructor accepts `storage: ITokenStorage`, `http_client: httpx.AsyncClient`
  - Implement `_get_lock()` for per-account locking
  - Implement `_do_refresh_with_retry()` with exponential backoff
  - Implement `_do_refresh()` with double-check pattern
  - Handle `invalid_grant` by setting `needs_reauth=True`
  - Clear `needs_reauth` on successful refresh
  - _Requirements: 3_

- [x] 5.3 Verify tests pass (TDD Refactor)
  - Run unit tests: `.venv\Scripts\python.exe -m pytest tests/unit/connectors/gemini_oauth_auto/test_token_refresh.py -v`
  - Fix any failures
  - Run QA checks on `token_refresh.py`
  - _Requirements: 3_

### Task 6: Implement AccountSelectorService

- [x] 6.1 Write unit tests for AccountSelectorService FIRST (TDD Red)
  - Create `tests/unit/connectors/gemini_oauth_auto/test_account_selector.py`
  - Test `get_next_account()` returns valid account
  - Test `get_next_account()` skips `needs_reauth` accounts
  - Test `get_next_account()` triggers refresh for near-expiry
  - Test round-robin rotation behavior
  - Test `rotate_on_quota()` advances to next
  - Test `get_available_count()` excludes invalid
  - Test empty accounts returns None
  - _Requirements: 4_

- [x] 6.2 Implement AccountSelectorService (TDD Green)
  - Create `src/connectors/gemini_oauth_auto/account_selector.py`
  - Implement `AccountSelectorService(IAccountSelector)`
  - Constructor accepts `storage: ITokenStorage`, `refresh_service: ITokenRefresh`
  - Implement round-robin via `_rotation_index`
  - Skip accounts with `needs_reauth=True`
  - Trigger `refresh_if_needed()` for near-expiry accounts
  - Track current account separately from rotation
  - _Requirements: 4_

- [x] 6.3 Verify tests pass (TDD Refactor)
  - Run unit tests: `.venv\Scripts\python.exe -m pytest tests/unit/connectors/gemini_oauth_auto/test_account_selector.py -v`
  - Fix any failures
  - Run QA checks on `account_selector.py`
  - _Requirements: 4_

---

## Phase 4: OAuth Flow (Script-Only)

### Task 7: Implement OAuthFlowService

- [x] 7.1 Write unit tests for OAuthFlowService FIRST (TDD Red)
  - Create `tests/unit/connectors/gemini_oauth_auto/test_oauth_flow.py`
  - Test state parameter generation (32 bytes hex)
  - Test authorization URL construction
  - Test code exchange request format
  - Test userinfo fetch and email extraction
  - Test state validation failure handling
  - Test timeout behavior
  - Mock HTTP responses, skip browser tests
  - _Requirements: 1_

- [x] 7.2 Implement OAuthFlowService (TDD Green)
  - Create `src/connectors/gemini_oauth_auto/oauth_flow.py`
  - Implement `OAuthFlowService`
  - Constructor accepts `storage: ITokenStorage`, `http_client: httpx.AsyncClient | None`
  - Implement `_generate_state()` with `secrets.token_hex(32)`
  - Implement `_build_auth_url()` with all required params
  - Implement `_exchange_code()` for token exchange
  - Implement `_fetch_userinfo()` for email
  - Implement `_start_callback_server()` using `FastAPI` (refactored from `aiohttp`)
  - Implement `authorize()` main entry point
  - Handle browser opening with fallback to URL print
  - _Requirements: 1, 6, 7_

- [x] 7.3 Verify tests pass (TDD Refactor)
  - Run unit tests: `.venv\Scripts\python.exe -m pytest tests/unit/connectors/gemini_oauth_auto/test_oauth_flow.py -v`
  - Fix any failures
  - Run QA checks on `oauth_flow.py`
  - _Requirements: 1_

---

## Phase 5: Management Script

### Task 8: Implement Account Management Script

- [x] 8.1 Create script structure
  - Create `scripts/manage_gemini_accounts.py`
  - Add shebang and module docstring
  - Set up `argparse` with subcommands: list, add, update, remove
  - Add path setup for importing `src/` modules
  - _Requirements: 5, 6, 7, 8_

- [x] 8.2 Implement `list` command
  - Display accounts in table format (default)
  - Show: account_id, email, status, expiry, last_used
  - Add `--json` flag for machine-readable output
  - Handle empty accounts with helpful message
  - _Requirements: 5_

- [x] 8.3 Implement `add` command
  - Invoke `OAuthFlowService.authorize()`
  - Support `--account-id` for custom identifier
  - Support `--no-browser` to disable auto-open
  - Support `--port` for fixed callback port
  - Support `--timeout` for auth timeout
  - Support `--force` to overwrite existing
  - Handle duplicate email warning
  - _Requirements: 6_

- [x] 8.4 Implement `update` command
  - Validate account exists
  - Reuse OAuth flow from add
  - Preserve `account_id` and `created_at`
  - Clear `needs_reauth` flag
  - _Requirements: 7_

- [x] 8.5 Implement `remove` command
  - Validate account exists
  - Prompt for confirmation (unless `--force`)
  - Delete credential file
  - Recommend revoking at Google security settings
  - _Requirements: 8_

- [x] 8.6 Test script manually
  - Run `python scripts/manage_gemini_accounts.py list`
  - Verify output format
  - Run `python scripts/manage_gemini_accounts.py --help`
  - _Requirements: 5, 6, 7, 8_

---

## Phase 6: Connector Implementation

### Task 9: Implement GeminiOAuthAutoConnector

- [x] 9.1 Write unit tests for connector FIRST (TDD Red)
  - Create `tests/unit/connectors/gemini_oauth_auto/test_connector.py`
  - Test `initialize()` loads accounts
  - Test `initialize()` sets functional state
  - Test `_oauth_credentials` returns current account
  - Test `_refresh_token_if_needed()` delegates to service
  - Test `_refresh_token_if_needed()` rotates on needs_reauth
  - Test `is_backend_functional()` checks account count
  - Test `_handle_quota_exhaustion()` rotates accounts
  - Mock all composed services
  - _Requirements: 9_

- [x] 9.2 Implement GeminiOAuthAutoConnector (TDD Green)
  - Create `src/connectors/gemini_oauth_auto/connector.py` (updated from stub)
  - Extend `GeminiOAuthBaseConnector`
  - Set `backend_type = "gemini-oauth-auto"`
  - Compose services in `__init__()` with shared httpx client
  - Override `initialize()` to use local storage
  - Override `_oauth_credentials` property
  - Override `_refresh_token_if_needed()` to use HTTP refresh
  - Override `_load_oauth_credentials()` to return False
  - Override `_start_file_watching()` as no-op
  - Override `is_backend_functional()` to check accounts
  - Implement `_handle_quota_exhaustion()`
  - Register with `backend_registry`
  - _Requirements: 9_

- [x] 9.3 Verify tests pass (TDD Refactor)
  - Run unit tests: `.venv\Scripts\python.exe -m pytest tests/unit/connectors/gemini_oauth_auto/test_connector.py -v`
  - Fix any failures
  - Run QA checks on `connector.py`
  - _Requirements: 9_

- [x] 9.4 Update package exports
  - Update `src/connectors/gemini_oauth_auto/__init__.py`
  - Export: `TokenStorageService`, `TokenRefreshService`, `AccountSelectorService`
  - Export: `OAuthFlowService`, `StoredAccount`, `AccountSummary`
  - Export error classes
  - _Requirements: 9_

---

## Phase 7: Configuration

### Task 10: Add Configuration Schema

- [x] 10.1 Create configuration schema file
  - Create `config/schemas/gemini_oauth_auto.yaml`
  - Define schema for connector configuration:
    - `accounts`: list of IDs or "all"
    - `refresh_buffer_seconds`: int (default 300)
    - `selection_strategy`: enum (round-robin, random, first-available)
    - `storage_path`: string (default "var/gemini_oauth_accounts")
  - _Requirements: 10_

- [x] 10.2 Add Pydantic config model
  - Add `GeminiOAuthAutoConfig` to `models.py` or separate config module
  - Define all fields with defaults
  - Add validation for selection_strategy enum
  - _Requirements: 10_

- [x] 10.3 Update example config
  - Add `gemini-oauth-auto` backend example to `config/config.example.yaml`
  - Document all configuration options
  - _Requirements: 10_

---

## Phase 8: Integration Testing

### Task 11: Integration Tests

- [x] 11.1 Create integration test for service composition
  - Create `tests/integration/connectors/test_gemini_oauth_auto.py`
  - Test `TokenStorageService` + `TokenRefreshService` + `AccountSelectorService` wiring
  - Test end-to-end token refresh flow with mocked Google endpoints
  - _Requirements: 3, 4_

- [x] 11.2 Create integration test for connector initialization
  - Test connector loads accounts from disk
  - Test connector handles zero accounts gracefully
  - Test connector rotates on quota exhaustion
  - _Requirements: 9_

- [x] 11.3 Run full test suite
  - Run: `.venv\Scripts\python.exe -m pytest tests/unit/connectors/gemini_oauth_auto/ -v`
  - Run: `.venv\Scripts\python.exe -m pytest tests/integration/connectors/test_gemini_oauth_auto.py -v`
  - Ensure all tests pass
  - _Requirements: 1-10_

---

## Phase 9: Final Verification

### Task 12: Quality Assurance

- [x] 12.1 Run linting and type checks
  - Run: `.venv\Scripts\python.exe -m ruff check src/connectors/gemini_oauth_auto/ --fix`
  - Run: `.venv\Scripts\python.exe -m black src/connectors/gemini_oauth_auto/`
  - Run: `.venv\Scripts\python.exe -m mypy src/connectors/gemini_oauth_auto/`
  - Fix any issues
  - _Requirements: All_

- [x] 12.2 Verify connector registration
  - Start proxy with `gemini-oauth-auto` backend configured
  - Verify backend appears in logs
  - Verify `/health` endpoint shows backend status
  - _Requirements: 9_

- [x] 12.3 Documentation
  - Update `README.md` with new backend type
  - Add usage instructions to `docs/` if applicable
  - Document script usage in script docstring
  - _Requirements: All_


---

## Post-Edit QA Workflow

**MANDATORY**: After editing ANY Python (*.py) file, run:

```powershell
.venv\Scripts\python.exe -m ruff check --fix <modified_filename> && .venv\Scripts\python.exe -m black <modified_filename> && .venv\Scripts\python.exe -m mypy <modified_filename>
```

---

## Checklist Before Marking Complete

- [x] All 10 requirements have test coverage
- [x] Unit tests pass for all services
- [x] Integration tests pass for service composition
- [x] No lint errors (`ruff check .`)
- [x] Type checks pass (`mypy src/connectors/gemini_oauth_auto/`)
- [x] Script runs without errors
- [x] Connector registers with backend_registry
- [x] Configuration schema documented
- [x] Error handling uses `LLMProxyError` hierarchy
- [x] Async/await used correctly (no blocking I/O)

