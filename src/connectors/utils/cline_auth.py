from __future__ import annotations

import asyncio
import base64
import ctypes
import json
import logging
import os
import platform
import sqlite3
import subprocess
import time
import uuid
from collections.abc import Mapping
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from src.core.common.exceptions import AuthenticationError, BackendError

logger = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency for Windows integration
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if TYPE_CHECKING:
        AESGCMType = type[AESGCM]
    else:
        AESGCMType = type(AESGCM)  # type: ignore[misc]
except ImportError:  # pragma: no cover
    AESGCM = None  # type: ignore[assignment,misc]
    AESGCMType = None  # type: ignore[assignment,misc]


class _ClineTokenStore:
    """Helper class that reads/writes the VSCode-style secrets JSON."""

    PRIMARY_KEY = "cline:clineAccountId"
    LEGACY_KEY = "clineAccountId"

    def __init__(self, secrets_path: Path) -> None:
        self._secrets_path = secrets_path

    def read(self) -> dict[str, Any] | None:
        secrets = self._read_all()
        raw_value = secrets.get(self.PRIMARY_KEY) or secrets.get(self.LEGACY_KEY)

        if raw_value is None:
            return None

        if isinstance(raw_value, str):
            try:
                parsed: dict[str, Any] = json.loads(raw_value)
                return parsed
            except json.JSONDecodeError:
                logger.warning("Failed to parse Cline auth payload from secrets file")
                return None

        if isinstance(raw_value, Mapping):
            return dict(raw_value)

        logger.warning(
            "Unexpected auth payload type in secrets file: %s", type(raw_value).__name__
        )
        return None

    def write(self, payload: Mapping[str, Any]) -> None:
        secrets = self._read_all()
        serialized = json.dumps(payload)

        secrets[self.PRIMARY_KEY] = serialized
        self._secrets_path.parent.mkdir(parents=True, exist_ok=True)

        with self._secrets_path.open("w", encoding="utf-8") as handle:
            json.dump(secrets, handle, indent=2)

    def _read_all(self) -> dict[str, Any]:
        if not self._secrets_path.exists():
            return {}

        try:
            with self._secrets_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, Mapping):
                    return dict(data)
        except json.JSONDecodeError:
            logger.warning("Failed to parse secrets JSON at %s", self._secrets_path)

        return {}


class ClineAuthMixin:
    """Auth/token management helpers shared by the Cline connector."""

    client: httpx.AsyncClient
    backend_type: str
    api_key: str | None
    _ENVIRONMENT_BASES: dict[str, str]
    _token_lock: asyncio.Lock
    _token_cache: dict[str, Any] | None
    _secrets_path: Path | None
    _token_store: _ClineTokenStore | None
    _token_file_mtime: float | None
    _refresh_endpoint: str
    _user_info_endpoint: str
    _request_timeout: float
    _codex_auth_override: Path | None
    _user_agent: str
    _client_type: str
    _client_version: str
    _core_version: str
    _is_multiroot: str

    _DEFAULT_SECRETS_SUBDIR = Path("data") / "secrets.json"
    _TOKEN_EXPIRY_BUFFER_SECONDS = 60.0

    async def _ensure_auth_token(
        self, force_reload: bool = False, *, force_refresh: bool = False
    ) -> dict[str, Any]:
        async with self._token_lock:
            if force_reload or self._token_cache is None or self._token_file_changed():
                token_data = self._load_tokens_from_disk()
            else:
                token_data = self._token_cache

            if not token_data:
                raise AuthenticationError(
                    "Cline auth token not found. Please sign into Cline first.",
                    details={
                        "secrets_path": (
                            str(self._secrets_path) if self._secrets_path else None
                        )
                    },
                )

            needs_refresh = force_refresh or self._is_token_expired(token_data)
            needs_conversion = self._token_needs_conversion(token_data)
            if needs_refresh or needs_conversion:
                refresh_token = token_data.get("refreshToken")
                if not refresh_token:
                    replacement = self._reload_from_secondary_tokens()
                    if not replacement:
                        raise AuthenticationError(
                            "Stored Cline token cannot be refreshed. Please sign into Cline.",
                            details={"provider": token_data.get("provider")},
                        )
                    token_data = replacement
                else:
                    try:
                        token_data = await self._refresh_tokens(
                            refresh_token, token_data
                        )
                    except AuthenticationError as exc:
                        replacement = self._reload_from_secondary_tokens()
                        if not replacement:
                            raise exc
                        token_data = replacement
                self._token_cache = token_data
                self._persist_tokens(token_data)
            else:
                self._token_cache = token_data

            api_key = token_data.get("idToken")
            if not api_key:
                raise AuthenticationError("Cline auth token is missing idToken field.")
            if not api_key.startswith("workos:"):
                api_key = f"workos:{api_key}"
            self.api_key = api_key
            return token_data

    def _resolve_secrets_path(
        self,
        explicit_path: str | os.PathLike[str] | None,
        cline_dir: str | None,
    ) -> Path:
        candidate_files: list[Path] = []
        seen: set[str] = set()

        def _add_candidate(path: Path | None, *, is_directory: bool = False) -> None:
            if path is None:
                return
            candidate = path
            if is_directory:
                candidate = path / self._DEFAULT_SECRETS_SUBDIR
            candidate = candidate.expanduser()
            key = str(candidate)
            if not key or key in seen:
                return
            seen.add(key)
            candidate_files.append(candidate)

        explicit = Path(explicit_path).expanduser() if explicit_path else None
        if explicit:
            _add_candidate(explicit)

        for directory in self._discover_candidate_directories(cline_dir):
            _add_candidate(directory, is_directory=True)

        if not candidate_files:
            default_path = Path.home() / ".cline" / self._DEFAULT_SECRETS_SUBDIR
            return default_path

        for candidate in candidate_files:
            if candidate.exists():
                return candidate

        return candidate_files[0]

    def _discover_candidate_directories(
        self, configured_dir: str | os.PathLike[str] | None
    ) -> list[Path]:
        directories: list[Path] = []

        def _add_directory(value: str | os.PathLike[str] | Path | None) -> None:
            if not value:
                return
            path = Path(value).expanduser()
            directories.append(path)

        _add_directory(configured_dir)
        _add_directory(os.getenv("CLINE_DIR"))

        _add_directory(Path.home() / ".cline")

        for win_dir in self._discover_windows_candidate_dirs():
            _add_directory(win_dir)

        if self._is_wsl():
            for wsl_dir in self._discover_wsl_candidate_dirs():
                _add_directory(wsl_dir)

        unique_directories: list[Path] = []
        seen: set[str] = set()
        for directory in directories:
            key = str(directory)
            if not key or key in seen:
                continue
            seen.add(key)
            unique_directories.append(directory)
        return unique_directories

    def _discover_windows_candidate_dirs(self) -> list[Path]:
        directories: list[Path] = []

        userprofile = os.getenv("USERPROFILE")
        if userprofile:
            directories.append(Path(userprofile) / ".cline")

        homedrive = os.getenv("HOMEDRIVE")
        homepath = os.getenv("HOMEPATH")
        if homedrive and homepath:
            directories.append(Path(homedrive + homepath) / ".cline")

        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            directories.append(Path(local_app_data) / "cline")

        roaming_app_data = os.getenv("APPDATA")
        if roaming_app_data:
            directories.append(Path(roaming_app_data) / "cline")

        return directories

    def _discover_wsl_candidate_dirs(self) -> list[Path]:
        directories: list[Path] = []

        cwd_guess = self._extract_windows_home_from_path(Path.cwd())
        if cwd_guess:
            directories.append(cwd_guess)

        env_userprofile = os.getenv("USERPROFILE")
        if env_userprofile and env_userprofile.startswith("/mnt/"):
            directories.append(Path(env_userprofile))

        directories.extend(self._enumerate_wsl_windows_homes())
        return directories

    def _enumerate_wsl_windows_homes(self) -> list[Path]:
        homes: list[Path] = []
        mnt_root = Path("/mnt")
        if not mnt_root.exists():
            return homes

        try:
            drive_dirs = list(mnt_root.iterdir())
        except OSError:
            return homes

        for drive_dir in drive_dirs:
            users_root = drive_dir / "Users"
            if not users_root.is_dir():
                continue
            try:
                user_dirs = list(users_root.iterdir())
            except OSError:
                continue
            for user_dir in user_dirs:
                if not user_dir.is_dir():
                    continue
                cline_dir = user_dir / ".cline"
                secrets_file = cline_dir / self._DEFAULT_SECRETS_SUBDIR
                if secrets_file.exists():
                    homes.append(user_dir / ".cline")
        return homes

    def _extract_windows_home_from_path(self, path: Path) -> Path | None:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path

        parts = resolved.parts
        lower_parts = [part.lower() for part in parts]
        for idx, part in enumerate(lower_parts):
            if part != "mnt":
                continue
            if idx + 3 >= len(parts):
                continue
            drive = parts[idx + 1]
            users_segment = lower_parts[idx + 2]
            username = parts[idx + 3]
            if len(drive) != 1 or users_segment != "users":
                continue
            return Path("/mnt") / drive / "Users" / username / ".cline"
        return None

    @staticmethod
    def _is_wsl() -> bool:
        if os.name != "posix":
            return False
        try:
            return "microsoft" in platform.release().lower()
        except OSError:
            return False

    def _resolve_api_base(
        self, explicit_url: str | None, environment: str | None
    ) -> tuple[str, str]:
        if explicit_url:
            return self._normalize_api_base(explicit_url)

        env_key = (environment or "production").lower()
        host = self._ENVIRONMENT_BASES.get(
            env_key, self._ENVIRONMENT_BASES["production"]
        )
        host = host.rstrip("/")
        return host, f"{host}/api/v1"

    def _normalize_api_base(self, url: str) -> tuple[str, str]:
        cleaned = url.strip().rstrip("/")
        marker = "/api/v1"

        idx = cleaned.find(marker)
        if idx != -1:
            host = cleaned[:idx].rstrip("/")
            if not host:
                host = self._ENVIRONMENT_BASES["production"]
            return host, f"{host}{marker}"

        return cleaned, f"{cleaned}/api/v1"

    def _token_file_changed(self) -> bool:
        if not self._secrets_path:
            return False

        try:
            current_mtime = self._secrets_path.stat().st_mtime
        except FileNotFoundError:
            return False

        if self._token_file_mtime is None:
            return True

        return current_mtime > self._token_file_mtime

    def _load_tokens_from_disk(self) -> dict[str, Any] | None:
        if not self._token_store:
            return None

        token_data = self._token_store.read()
        self._token_file_mtime = self._read_secrets_mtime()
        if token_data:
            return token_data

        vscode_tokens = self._load_tokens_from_vscode_secret_store()
        if vscode_tokens:
            logger.info("Loaded Cline credentials from VSCode secret store")
            self._persist_tokens(vscode_tokens)
            return vscode_tokens

        fallback = self._load_tokens_from_codex_auth()
        if fallback:
            logger.info("Loaded Cline credentials from Codex auth file")
            self._persist_tokens(fallback)
            return fallback

        return token_data

    def _persist_tokens(self, token_data: Mapping[str, Any]) -> None:
        if not self._token_store:
            return
        self._token_store.write(token_data)
        self._token_file_mtime = self._read_secrets_mtime()

    def _read_secrets_mtime(self) -> float | None:
        if not self._secrets_path:
            return None
        try:
            return self._secrets_path.stat().st_mtime
        except FileNotFoundError:
            return None

    def _is_token_expired(self, token_data: Mapping[str, Any]) -> bool:
        expires_at = token_data.get("expiresAt")
        if expires_at is None:
            return False
        try:
            expires_at_float = float(expires_at)
        except (TypeError, ValueError):
            return False

        return (expires_at_float - self._TOKEN_EXPIRY_BUFFER_SECONDS) <= time.time()

    async def _refresh_tokens(
        self,
        refresh_token: str,
        existing_payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "refreshToken": refresh_token,
            "grantType": "refresh_token",
        }

        try:
            response = await self.client.post(
                self._refresh_endpoint,
                json=payload,
                timeout=self._request_timeout,
            )
        except httpx.HTTPError as exc:
            raise BackendError(
                "Failed to contact Cline refresh endpoint.",
                backend_name=self.backend_type,
                details={"error": str(exc)},
            ) from exc

        if response.status_code != 200:
            raise AuthenticationError(
                "Cline token refresh failed.",
                details={"status_code": response.status_code, "body": response.text},
            )

        try:
            response_json = response.json()
        except json.JSONDecodeError as exc:
            raise BackendError(
                "Invalid JSON from Cline refresh endpoint.",
                backend_name=self.backend_type,
            ) from exc

        if not response_json.get("success"):
            raise AuthenticationError(
                "Cline token refresh was rejected.",
                details={"response": response_json},
            )

        data = response_json.get("data")
        if not isinstance(data, Mapping):
            raise BackendError(
                "Cline refresh response missing token payload.",
                backend_name=self.backend_type,
                details={"response": response_json},
            )

        access_token = data.get("accessToken")
        if not access_token:
            raise AuthenticationError("Cline refresh response missing accessToken.")

        new_refresh_token = data.get("refreshToken") or refresh_token
        expires_at = self._parse_expiry_timestamp(
            data.get("expiresAt"),
            fallback=existing_payload.get("expiresAt") if existing_payload else None,
        )

        user_info = await self._fetch_user_info(access_token)
        if not user_info and existing_payload:
            existing_user = existing_payload.get("userInfo")
            if isinstance(existing_user, Mapping):
                user_info = dict(existing_user)

        return {
            "idToken": access_token,
            "refreshToken": new_refresh_token,
            "expiresAt": expires_at,
            "userInfo": user_info or {},
            "provider": "cline",
        }

    async def _fetch_user_info(self, access_token: str) -> dict[str, Any] | None:
        headers = {"Authorization": f"Bearer workos:{access_token}"}
        try:
            response = await self.client.get(
                self._user_info_endpoint,
                headers=headers,
                timeout=self._request_timeout,
            )
        except httpx.HTTPError as exc:
            logger.warning("Failed to fetch Cline user info: %s", exc)
            return None

        if response.status_code != 200:
            logger.debug(
                "Cline user info request failed with status %s",
                response.status_code,
            )
            return None

        try:
            payload = response.json()
        except json.JSONDecodeError:
            logger.warning("Received invalid JSON when fetching Cline user info")
            return None

        data = payload.get("data") if isinstance(payload, Mapping) else None
        if isinstance(data, Mapping):
            return dict(data)

        if isinstance(payload, Mapping):
            return dict(payload)

        return None

    def _parse_expiry_timestamp(
        self,
        value: Any,
        *,
        fallback: Any = None,
    ) -> float | None:
        if isinstance(value, int | float):
            return float(value)

        if isinstance(value, str):
            try:
                dt = parsedate_to_datetime(value)
                return dt.timestamp()
            except (TypeError, ValueError):
                logger.debug("Unable to parse expiresAt value '%s'", value)

        if fallback is not None:
            try:
                return float(fallback)
            except (TypeError, ValueError):
                return None

        return None

    def _reload_from_secondary_tokens(self) -> dict[str, Any] | None:
        vscode_tokens = self._load_tokens_from_vscode_secret_store()
        if vscode_tokens:
            logger.info("Recovered Cline credentials from VSCode secret store")
            self._persist_tokens(vscode_tokens)
            return vscode_tokens

        fallback = self._load_tokens_from_codex_auth()
        if fallback:
            logger.info("Recovered Cline credentials from Codex auth file")
            self._persist_tokens(fallback)
            return fallback

        return None

    def _load_tokens_from_codex_auth(self) -> dict[str, Any] | None:
        if not self._codex_auth_override:
            return None

        candidate = self._codex_auth_override
        try:
            with candidate.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            logger.debug("Codex auth file not found at %s", candidate)
            return None
        except json.JSONDecodeError:
            logger.debug("Failed to parse Codex auth file at %s", candidate)
            return None

        tokens = payload.get("tokens")
        if not isinstance(tokens, Mapping):
            return None

        access_token = tokens.get("access_token") or tokens.get("id_token")
        refresh_token = tokens.get("refresh_token")
        if not isinstance(access_token, str) or not isinstance(refresh_token, str):
            return None

        expires_at = self._extract_jwt_exp(access_token)
        account_id = tokens.get("account_id")
        user_info: dict[str, Any] = {}
        if isinstance(account_id, str) and account_id:
            user_info["id"] = account_id
        else:
            jwt_payload = self._decode_jwt_payload(access_token)
            user_claim = None
            if isinstance(jwt_payload, Mapping):
                user_claim = (
                    jwt_payload.get("sub")
                    or jwt_payload.get("external_id")
                    or jwt_payload.get("user_id")
                )
            if isinstance(user_claim, str) and user_claim:
                user_info["id"] = user_claim

        return {
            "idToken": access_token,
            "refreshToken": refresh_token,
            "expiresAt": expires_at,
            "userInfo": user_info,
            "provider": "codex",
        }

    def _load_tokens_from_vscode_secret_store(self) -> dict[str, Any] | None:
        if os.name != "nt":
            return None
        if AESGCM is None:
            logger.debug(
                "cryptography package not available; skipping VSCode secret load"
            )
            return None

        state_db, local_state = self._resolve_vscode_paths()
        if not state_db or not local_state:
            return None

        try:
            aes_key = self._extract_vscode_aes_key(local_state)
            if not aes_key:
                return None

            secret_blob = self._read_vscode_secret_blob(state_db)
            if not secret_blob:
                return None

            plaintext = self._decrypt_vscode_secret(secret_blob, aes_key)
            data = json.loads(plaintext.decode("utf-8"))
            if isinstance(data, Mapping):
                return dict(data)
        except Exception as exc:
            logger.debug("Failed to load VSCode secret store: %s", exc, exc_info=True)
            return None
        return None

    def _resolve_vscode_paths(self) -> tuple[Path | None, Path | None]:
        appdata = os.getenv("APPDATA")
        if not appdata:
            return None, None

        state_db = Path(
            os.getenv(
                "CLINE_VSCODE_STATE_DB",
                Path(appdata) / "Code" / "User" / "globalStorage" / "state.vscdb",
            )
        )
        local_state = Path(
            os.getenv(
                "CLINE_VSCODE_LOCAL_STATE",
                Path(appdata) / "Code" / "Local State",
            )
        )

        if not state_db.exists() or not local_state.exists():
            return None, None
        return state_db, local_state

    def _extract_vscode_aes_key(self, local_state: Path) -> bytes | None:
        try:
            with local_state.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            encrypted_key_b64 = data.get("os_crypt", {}).get("encrypted_key")
            if not isinstance(encrypted_key_b64, str):
                return None
            encrypted_key = base64.b64decode(encrypted_key_b64)
            if encrypted_key.startswith(b"DPAPI"):
                encrypted_key = encrypted_key[5:]
            return self._dpapi_decrypt(encrypted_key)
        except Exception:
            logger.debug("Failed to extract VSCode AES key", exc_info=True)
            return None

    def _read_vscode_secret_blob(self, state_db: Path) -> bytes | None:
        patterns = [
            'secret://{"extensionId":"saoudrizwan.claude-dev","key":"cline:clineAccountId"}',
            'secret://{"extensionId":"rooveterinaryinc.roo-cline","key":"cline:clineAccountId"}',
        ]

        try:
            conn = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True)
        except sqlite3.Error:
            logger.debug("Unable to open VSCode state database", exc_info=True)
            return None

        try:
            cur = conn.cursor()
            for pattern in patterns:
                cur.execute(
                    "SELECT value FROM ItemTable WHERE key=? ORDER BY rowid DESC LIMIT 1",
                    (pattern,),
                )
                row = cur.fetchone()
                if not row:
                    continue
                value = row[0]
                try:
                    buffer_json = json.loads(value)
                    data = buffer_json.get("data")
                    if isinstance(data, list):
                        return bytes(data)
                except Exception:
                    logger.debug(
                        "Failed to parse VSCode secret blob for key %s", pattern
                    )
                    continue
        finally:
            conn.close()

        return None

    def _decrypt_vscode_secret(self, blob: bytes, aes_key: bytes) -> bytes:
        if not blob.startswith(b"v10"):
            return blob

        nonce = blob[3:15]
        ciphertext = blob[15:-16]
        tag = blob[-16:]
        aesgcm = AESGCM(aes_key)
        return aesgcm.decrypt(nonce, ciphertext + tag, None)

    def _dpapi_decrypt(self, encrypted: bytes) -> bytes:
        class DATA_BLOB(ctypes.Structure):  # noqa: N801
            _fields_ = [
                ("cbData", ctypes.c_uint32),
                ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
            ]

        if os.name == "nt":
            buffer = ctypes.create_string_buffer(encrypted)
            blob_in = DATA_BLOB(
                len(encrypted), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
            )
            blob_out = DATA_BLOB()
            if (
                ctypes.windll.crypt32.CryptUnprotectData(
                    ctypes.byref(blob_in),
                    None,
                    None,
                    None,
                    None,
                    0,
                    ctypes.byref(blob_out),
                )
                == 0
            ):
                raise ctypes.WinError()

            try:
                data = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            finally:
                ctypes.windll.kernel32.LocalFree(blob_out.pbData)
            return data

        powershell = os.getenv(
            "POWERSHELL_PATH_OVERRIDE",
            "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
        )
        if not Path(powershell).exists():
            raise RuntimeError("PowerShell not available for DPAPI decryption")

        b64_payload = base64.b64encode(encrypted).decode("ascii")
        script = (
            f"$enc=[Convert]::FromBase64String('{b64_payload}');"
            "$dec=[System.Security.Cryptography.ProtectedData]::"
            "Unprotect($enc,$null,"
            "[System.Security.Cryptography.DataProtectionScope]::CurrentUser);"
            "[Console]::Write([Convert]::ToBase64String($dec))"
        )

        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"PowerShell DPAPI decrypt failed: {result.stderr.strip()}"
            )
        try:
            return base64.b64decode(result.stdout.strip())
        except Exception as exc:
            raise RuntimeError("Failed to decode PowerShell DPAPI output") from exc

    @staticmethod
    def _decode_jwt_payload(token: str) -> Mapping[str, Any] | None:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        payload_part = parts[1]
        padding = "=" * (-len(payload_part) % 4)
        try:
            decoded = base64.urlsafe_b64decode(payload_part + padding)
            data = json.loads(decoded.decode("utf-8"))
        except (json.JSONDecodeError, ValueError, OSError):
            return None
        if isinstance(data, Mapping):
            return data
        return None

    def _extract_jwt_exp(self, token: str) -> float | None:
        payload = self._decode_jwt_payload(token)
        if not isinstance(payload, Mapping):
            return None
        expires_at = payload.get("exp")
        if isinstance(expires_at, int | float):
            return float(expires_at)
        return None

    def _token_needs_conversion(self, token_data: Mapping[str, Any]) -> bool:
        provider = token_data.get("provider")
        if provider is None:
            return False
        return str(provider).lower() != "cline"

    async def _invalidate_token_cache(self) -> None:
        async with self._token_lock:
            self._token_cache = None
            self._token_file_mtime = None

    def _build_default_headers(
        self, *, session_id: str | None = None
    ) -> dict[str, str]:
        headers = {
            "HTTP-Referer": "https://cline.bot",
            "Referer": "https://cline.bot",
            "X-Title": "Cline",
            "User-Agent": self._user_agent,
            "X-CLIENT-TYPE": self._client_type,
            "X-CLIENT-VERSION": self._client_version,
            "X-CORE-VERSION": self._core_version,
            "X-PLATFORM": platform.system() or "unknown",
            "X-PLATFORM-VERSION": platform.version() or "unknown",
            "X-IS-MULTIROOT": self._is_multiroot,
        }
        headers["X-Task-ID"] = session_id or uuid.uuid4().hex
        return headers
