# Stale Authentication Token Handling — Best Practices

## Purpose

This document defines a reusable pattern for backends that authenticate via credentials stored on disk (JSON/YAML, tokens, API keys, certificates). It is derived from the hardened implementation added for `qwen-oauth` and is intended to be applied consistently to other file‑backed auth providers.

Goals:

- Detect invalid/expired credentials at startup (fail fast instead of failing requests later)
- Track backend health clearly and expose actionable validation errors
- Auto‑reload credentials when the file changes (OS‑independent file watching)
- Re‑validate during runtime and gracefully degrade if recovery fails
- Return descriptive errors to clients (e.g., 502 with detail)

---

## Core Pattern

Implement these capabilities in each file‑backed backend:

1) Startup validation (fail fast)

- Verify credentials file path is known and readable
- Parse credentials (JSON/YAML) with clear error messages on decode failures
- Validate structure (required fields) and types
- Validate expiry (e.g., `expiry_date` in ms; `expires_at` as UNIX ts)
- Attempt refresh on startup if token appears expired and a refresh mechanism exists
- If invalid → mark backend non‑functional and record validation errors

2) Health tracking API

- `is_backend_functional() -> bool`: true only if backend is usable
- `get_validation_errors() -> list[str]`: returns a copy of last validation errors
- Internal state to maintain:
  - `is_functional: bool`
  - `_initialization_failed: bool`
  - `_credential_validation_errors: list[str]`
  - `_last_validation_time: float` (epoch seconds)

3) File watching (cross‑platform)

- Use `watchdog` to watch the credentials file directory
- On file change:
  - Re‑validate file structure and expiry
  - Reload credentials in memory
  - Update health state and errors
- Start watching after successful initialization; stop on shutdown

4) Runtime validation

- Throttle checks (e.g., every 30s) to avoid excessive I/O
- If token expires during runtime:
  - Attempt reload from disk
  - If still invalid/expired → mark non‑functional and persist errors
  - If valid → clear errors and continue

5) Descriptive client errors

- Before handling a request, ensure backend is functional and token is valid/refreshed
- If not, raise an error like:
  - HTTP 502 with detail: `"No valid credentials found for backend <name>: <joined errors>"`

6) Application‑level startup validation

- During app boot, build/initialize configured backends and collect the functional ones
- If none are functional → fail startup with clear logs

---

## Reference Interfaces (pseudocode)

```python
class FileBackedAuthBackend:
    def __init__(self, ...):
        self.is_functional: bool = False
        self._initialization_failed: bool = False
        self._credential_validation_errors: list[str] = []
        self._last_validation_time: float = 0.0
        self._credentials_path: Path | None = None
        self._file_observer: Observer | None = None

    def is_backend_functional(self) -> bool:
        return (
            self.is_functional
            and not self._initialization_failed
            and len(self._credential_validation_errors) == 0
        )

    def get_validation_errors(self) -> list[str]:
        return self._credential_validation_errors.copy()

    async def initialize(self) -> None:
        # 1) File exists + readable + parseable
        ok, errs = self._validate_credentials_file_exists()
        if not ok:
            self._fail_init(errs)
            return

        # 2) Load credentials into memory
        if not await self._load_credentials():
            self._fail_init(["Failed to load credentials despite validation passing"])
            return

        # 3) Structure + expiry validation
        ok, errs = self._validate_credentials_structure(self._credentials)
        if not ok:
            self._fail_init(errs)
            return

        # 4) Refresh if needed
        if not await self._refresh_token_if_needed():
            self._fail_init(["Failed to refresh expired token during initialization"])
            return

        # 5) Start file watching and mark functional
        self._start_file_watching()
        self.is_functional = True
        self._last_validation_time = time.time()

    async def _validate_runtime_credentials(self) -> bool:
        now = time.time()
        if now - self._last_validation_time < 30:
            return self.is_backend_functional()
        self._last_validation_time = now

        if self._is_token_expired():
            if await self._load_credentials():
                if self._is_token_expired():
                    self._degrade(["Token expired and no valid replacement found"])
                    return False
                self._recover()
                return True
            self._degrade(["Failed to reload expired credentials"])
            return False

        return self.is_backend_functional()
```

Helper state transitions:

```python
def _fail_init(self, errors: list[str]) -> None:
    self._credential_validation_errors = errors
    self._initialization_failed = True
    self.is_functional = False

def _degrade(self, errors: list[str]) -> None:
    self._credential_validation_errors = errors
    self.is_functional = False

def _recover(self) -> None:
    self._credential_validation_errors = []
    self.is_functional = True
```

---

## Validation Rules by Credential Type

### OAuth‑like tokens (access/refresh)

- Required fields: `access_token` (str, non‑empty), `refresh_token` (str, non‑empty)
- Optional/Recommended: `expiry_date` (ms since epoch)
- Expiry rule: `now >= expiry_date/1000` → expired
- On startup and runtime expiry, attempt refresh; if still invalid → non‑functional

Example structure check:

```python
def _validate_credentials_structure(self, data: dict[str, Any]) -> tuple[bool, list[str]]:
    errors = []
    for f in ["access_token", "refresh_token"]:
        if f not in data:
            errors.append(f"Missing required field: {f}")
        elif not isinstance(data[f], str) or not data[f]:
            errors.append(f"Invalid {f}: must be a non-empty string")

    if "expiry_date" in data:
        expiry = data["expiry_date"]
        if not isinstance(expiry, (int, float)):
            errors.append("Invalid expiry_date: must be a number (ms)")
        else:
            if time.time() >= float(expiry) / 1000.0:
                errors.append("Token expired")
    return len(errors) == 0, errors
```

### API key

- Required: `api_key` (str, non‑empty)
- Optional: `expires_at` (epoch seconds)
- If `expires_at` present and `now >= expires_at` → expired → non‑functional

### Certificate‑based

- Required files exist and are regular files: `certificate_path`, `private_key_path`
- Optional `ca_bundle_path`
- Verify readability; consider parsing/format checks where feasible

---

## File Watching

Use `watchdog` to watch the parent directory of the credentials file:

```python
class CredentialsFileHandler(FileSystemEventHandler):
    def __init__(self, backend: FileBackedAuthBackend):
        self.backend = backend

    def on_modified(self, event):
        if not event.is_directory and event.src_path == str(self.backend._credentials_path):
            task = asyncio.create_task(self.backend._handle_credentials_file_change())
            self.backend._pending_reload_task = task
```

On change:

- Validate file → reload → update health (recover or degrade)
- Log: success, invalid structure, still expired, reload failures

---

## Request Path Enforcement

Before any upstream call:

```python
if not await self._validate_runtime_credentials():
    details = "; ".join(self._credential_validation_errors) or "Backend is not functional"
    raise HTTPException(status_code=502, detail=f"No valid credentials found for backend {self.name}: {details}")

if not await self._refresh_token_if_needed():
    raise HTTPException(status_code=502, detail=f"No valid credentials found for backend {self.name}: Failed to refresh expired token")
```

Return 502 (Bad Gateway) for upstream auth failures, with precise detail text.

---

## App Startup Guardrail

At application boot, validate configured backends and ensure at least one is functional. If none are functional, fail startup with clear logs:

- Log each backend as functional or list its validation errors
- Abort with: "No functional backends found! Proxy cannot operate without at least one working backend."

---

## Testing Checklist (apply to each backend)

Startup validation

- Missing credentials file → non‑functional, error recorded
- Invalid JSON/YAML → non‑functional, error recorded
- Missing required fields → non‑functional
- Empty/invalid values → non‑functional
- Expired token/key → non‑functional (refresh attempted if applicable)
- Valid credentials → functional

Runtime behavior

- Throttled validation honors interval
- Expired during runtime → reload attempt → recover on success; degrade on failure

File watching

- Starts when credentials path exists
- On valid update → recover and clear errors
- On invalid update → degrade and record errors

Error responses

- 502 with descriptive `detail` message when non‑functional

Integration

- App boot fails when no functional backends exist
- App boot succeeds when at least one backend is functional

---

## Logging Guidance (examples)

Startup

- INFO: Initializing <backend> with enhanced validation…
- INFO: Credentials file validation passed / ERROR with reasons
- INFO: Token refresh check completed / ERROR on failure
- INFO: Started watching credentials file: <path>

Runtime

- INFO: Access token expired during runtime, attempting to reload credentials…
- INFO: Successfully reloaded valid credentials
- WARN: Reloaded token is still expired, marking backend as non‑functional
- ERROR: Failed to reload credentials, marking backend as non‑functional

File changes

- INFO: Credentials file modified: <path>
- INFO: Successfully reloaded credentials from updated file
- WARN: Updated credentials file is invalid: <reasons>

---

## Migration Steps for Existing Backends

1) Add health fields and helpers (`is_functional`, `_initialization_failed`, `_credential_validation_errors`, `_last_validation_time`, getters)
2) Implement startup validation pipeline (file → load → structure/expiry → refresh → watch)
3) Add runtime validation with throttling and recovery/degradation paths
4) Enforce request‑time checks and descriptive 502 errors
5) Integrate with app startup guardrail (fail when none functional)
6) Add comprehensive unit and integration tests per the checklist

---

## Notes

- Expiry units must be explicit (ms vs s) and consistent per backend
- Avoid broad exception catches without logging; record details into `_credential_validation_errors`
- Keep file watchers robust but quiet; never crash on watcher errors (log warnings)
- Always copy error lists in getters to avoid external mutation
