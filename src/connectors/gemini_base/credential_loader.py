"""
Credential loading and validation for Gemini OAuth connectors.

This module handles OAuth credential lifecycle management including:
- Loading credentials from file
- Saving credentials to file
- Validating credential structure
- Computing credential fingerprints for change detection
"""

import datetime
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class CredentialStorage(Protocol):
    """Protocol for credential storage required by CredentialLoader."""

    _oauth_credentials: dict[str, Any] | None
    _credentials_path: Path | None
    _last_modified: float
    _credentials_fingerprint: str | None
    _credentials_file_hash: str | None
    _last_credentials_event_hash: str | None
    gemini_cli_oauth_path: str | None


class CredentialLoader:
    """Manages OAuth credential loading and validation for Gemini connectors.

    This class handles credential file operations including loading, saving,
    validation, and fingerprinting. It is designed to be composed into
    connector classes that provide credential storage.
    """

    @staticmethod
    def validate_credentials_structure(
        credentials: dict[str, Any], silent: bool = False
    ) -> tuple[bool, list[str]]:
        """Validate the structure and content of OAuth credentials.

        Args:
            credentials: The credentials dictionary to validate.
            silent: If True, suppress INFO level logging.

        Returns:
            Tuple of (is_valid, list_of_errors).
        """
        errors: list[str] = []

        # Required fields for OAuth credentials
        required_fields = ["access_token"]
        for field in required_fields:
            if field not in credentials:
                errors.append(f"Missing required field: {field}")
            elif not isinstance(credentials[field], str) or not credentials[field]:
                errors.append(f"Invalid {field}: must be a non-empty string")

        # Optional refresh token validation
        if "refresh_token" in credentials and (
            not isinstance(credentials["refresh_token"], str)
            or not credentials["refresh_token"]
        ):
            errors.append("Invalid refresh_token: must be a non-empty string")

        # Expiry validation (if present)
        if "expiry_date" in credentials:
            expiry = credentials["expiry_date"]
            if not isinstance(expiry, int | float):
                errors.append("Invalid expiry_date: must be a number (ms)")
            else:
                # Record expired status without failing validation; refresh logic handles it
                current_utc_s = datetime.datetime.now(datetime.timezone.utc).timestamp()
                if (
                    current_utc_s >= float(expiry) / 1000.0
                    and not silent
                    and logger.isEnabledFor(logging.INFO)
                ):
                    logger.info(
                        "Loaded Gemini OAuth credentials appear expired; "
                        "refresh will be triggered."
                    )

        return len(errors) == 0, errors

    @staticmethod
    def validate_credentials_file_exists(
        gemini_cli_oauth_path: str | None,
    ) -> tuple[bool, list[str], Path | None]:
        """Validate that the OAuth credentials file exists and is readable.

        Args:
            gemini_cli_oauth_path: Custom path to .gemini directory, or None for default.

        Returns:
            Tuple of (is_valid, list_of_errors, resolved_path).
        """
        errors: list[str] = []

        # Use custom path if provided, otherwise default to ~/.gemini
        if gemini_cli_oauth_path:
            creds_path = Path(gemini_cli_oauth_path) / "oauth_creds.json"
        else:
            home_dir = Path.home()
            creds_path = home_dir / ".gemini" / "oauth_creds.json"

        if not creds_path.exists():
            errors.append(f"OAuth credentials file not found at {creds_path}")
            return False, errors, creds_path

        if not creds_path.is_file():
            errors.append(
                f"OAuth credentials path exists but is not a file: {creds_path}"
            )
            return False, errors, creds_path

        try:
            with open(creds_path, encoding="utf-8") as f:
                credentials = json.load(f)

            # Validate the loaded credentials
            is_valid, validation_errors = (
                CredentialLoader.validate_credentials_structure(credentials)
            )
            errors.extend(validation_errors)

            return is_valid, errors, creds_path

        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON in credentials file: {e}")
            return False, errors, creds_path
        except PermissionError:
            errors.append(f"Permission denied reading credentials file: {creds_path}")
            return False, errors, creds_path
        except Exception as e:
            errors.append(f"Unexpected error reading credentials file: {e}")
            return False, errors, creds_path

    @staticmethod
    def validate_active_credentials_path(
        credentials_path: Path | None,
        gemini_cli_oauth_path: str | None,
    ) -> tuple[bool, list[str]]:
        """Validate the currently used credentials path, if known.

        This avoids incorrectly validating a different credential source (e.g.,
        oauth_creds.json when a connector uses an alternate database file).

        Args:
            credentials_path: The currently active credentials path.
            gemini_cli_oauth_path: Custom path to .gemini directory.

        Returns:
            Tuple of (is_valid, list_of_errors).
        """
        if credentials_path:
            errors: list[str] = []
            try:
                if not credentials_path.exists():
                    errors.append(f"Credentials path not found: {credentials_path}")
                elif not credentials_path.is_file():
                    errors.append(
                        f"Credentials path exists but is not a file: {credentials_path}"
                    )
            except OSError as exc:
                errors.append(
                    f"Error accessing credentials path {credentials_path}: {exc}"
                )

            return len(errors) == 0, errors

        is_valid, errors, _ = CredentialLoader.validate_credentials_file_exists(
            gemini_cli_oauth_path
        )
        return is_valid, errors

    @staticmethod
    def compute_credentials_fingerprint(credentials: dict[str, Any]) -> str:
        """Return a stable fingerprint for the provided credentials.

        Args:
            credentials: The credentials dictionary.

        Returns:
            SHA-256 hash of the relevant credential fields.
        """
        relevant = {
            "access_token": credentials.get("access_token", ""),
            "refresh_token": credentials.get("refresh_token", ""),
            "expiry_date": credentials.get("expiry_date"),
        }
        payload = json.dumps(relevant, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8", "ignore")).hexdigest()

    @staticmethod
    async def load_oauth_credentials(
        storage: CredentialStorage,
        force_reload: bool = False,
        silent: bool = False,
    ) -> bool:
        """Load OAuth credentials from oauth_creds.json file.

        Args:
            storage: Object providing credential storage.
            force_reload: If True, bypass cache and force reload from file.
            silent: If True, suppress INFO level logging.

        Returns:
            True if credentials loaded successfully, False otherwise.
        """
        try:
            # Use custom path if provided, otherwise default to ~/.gemini
            if storage.gemini_cli_oauth_path:
                creds_path = Path(storage.gemini_cli_oauth_path) / "oauth_creds.json"
            else:
                home_dir = Path.home()
                creds_path = home_dir / ".gemini" / "oauth_creds.json"
            storage._credentials_path = creds_path

            if not creds_path.exists():
                logger.warning(f"Gemini OAuth credentials not found at {creds_path}")
                return False

            # Check if file has been modified since last load (unless force_reload is True)
            if not force_reload:
                try:
                    current_modified = creds_path.stat().st_mtime
                    if (
                        current_modified == storage._last_modified
                        and storage._oauth_credentials
                    ):
                        # File hasn't changed and credentials are in memory, no need to reload
                        logger.debug(
                            "Gemini OAuth credentials file not modified, using cached."
                        )
                        return True
                except OSError:
                    # If cannot get file stats, proceed with reading
                    pass

            # Update last modified time
            try:
                current_modified = creds_path.stat().st_mtime
                storage._last_modified = current_modified
            except OSError:
                pass

            raw_text = creds_path.read_text(encoding="utf-8")
            credentials = json.loads(raw_text)

            # Validate essential fields
            if "access_token" not in credentials:
                logger.warning(
                    "Malformed Gemini OAuth credentials: missing access_token"
                )
                return False

            storage._oauth_credentials = credentials
            storage._credentials_fingerprint = (
                CredentialLoader.compute_credentials_fingerprint(credentials)
            )
            storage._credentials_file_hash = hashlib.sha256(
                raw_text.encode("utf-8", "ignore")
            ).hexdigest()
            storage._last_credentials_event_hash = storage._credentials_file_hash
            if not silent and logger.isEnabledFor(logging.INFO):
                log_msg = "Successfully loaded Gemini OAuth credentials"
                if force_reload:
                    log_msg += " (force reload)"
                logger.info(log_msg + ".")
            return True
        except json.JSONDecodeError as e:
            logger.error(
                f"Error decoding Gemini OAuth credentials JSON: {e}",
                exc_info=True,
            )
            return False
        except OSError as e:
            logger.error(f"Error loading Gemini OAuth credentials: {e}", exc_info=True)
            return False

    @staticmethod
    async def save_oauth_credentials(credentials: dict[str, Any]) -> None:
        """Save OAuth credentials to oauth_creds.json file.

        Args:
            credentials: The credentials dictionary to save.
        """
        try:
            home_dir = Path.home()
            gemini_dir = home_dir / ".gemini"
            gemini_dir.mkdir(parents=True, exist_ok=True)  # Ensure directory exists
            creds_path = gemini_dir / "oauth_creds.json"

            with open(creds_path, "w", encoding="utf-8") as f:
                json.dump(credentials, f, indent=4)
            logger.info(f"Gemini OAuth credentials saved to {creds_path}")
        except OSError as e:
            logger.error(f"Error saving Gemini OAuth credentials: {e}", exc_info=True)


__all__ = [
    "CredentialLoader",
    "CredentialStorage",
]
