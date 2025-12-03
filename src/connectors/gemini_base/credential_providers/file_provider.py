"""
File-based credential provider for Gemini OAuth connectors.

Loads OAuth credentials from the standard gemini-cli oauth_creds.json file.
"""

import datetime
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FileCredentialProvider:
    """Credential provider that loads from JSON file (oauth_creds.json).

    This provider implements the ICredentialProvider protocol and is used by
    the standard gemini-oauth-plan and gemini-oauth-free backends.
    """

    def __init__(self, gemini_cli_oauth_path: str | None = None) -> None:
        """Initialize the file credential provider.

        Args:
            gemini_cli_oauth_path: Custom path to .gemini directory, or None for default.
        """
        self._gemini_cli_oauth_path = gemini_cli_oauth_path
        self._credentials_path: Path | None = None
        self._last_modified: float = 0
        self._cached_credentials: dict[str, Any] | None = None
        self._credentials_fingerprint: str | None = None
        self._credentials_file_hash: str | None = None

    def get_path(self) -> Path | None:
        """Get the path to the credentials file.

        Returns:
            Path to the oauth_creds.json file.
        """
        if self._credentials_path:
            return self._credentials_path

        if self._gemini_cli_oauth_path:
            return Path(self._gemini_cli_oauth_path) / "oauth_creds.json"
        return Path.home() / ".gemini" / "oauth_creds.json"

    def validate(
        self, credentials: dict[str, Any], silent: bool = False
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
                # Record expired status without failing validation
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

    def compute_fingerprint(self, credentials: dict[str, Any]) -> str:
        """Compute a stable fingerprint for the credentials.

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

    async def load(
        self, force_reload: bool = False, silent: bool = False
    ) -> dict[str, Any] | None:
        """Load OAuth credentials from oauth_creds.json file.

        Args:
            force_reload: If True, bypass cache and force reload from file.
            silent: If True, suppress INFO level logging.

        Returns:
            Credentials dictionary or None if loading failed.
        """
        try:
            creds_path = self.get_path()
            if creds_path is None:
                logger.warning("No credentials path configured")
                return None

            self._credentials_path = creds_path

            if not creds_path.exists():
                logger.warning(f"Gemini OAuth credentials not found at {creds_path}")
                return None

            # Check if file has been modified since last load
            if not force_reload:
                try:
                    current_modified = creds_path.stat().st_mtime
                    if (
                        current_modified == self._last_modified
                        and self._cached_credentials
                    ):
                        logger.debug(
                            "Gemini OAuth credentials file not modified, using cached."
                        )
                        return self._cached_credentials
                except OSError:
                    pass

            # Update last modified time
            try:
                current_modified = creds_path.stat().st_mtime
                self._last_modified = current_modified
            except OSError:
                pass

            # Validate essential fields
            credentials = cast(dict[str, Any], json.loads(raw_text))

            if "access_token" not in credentials:
                logger.warning(
                    "Malformed Gemini OAuth credentials: missing access_token"
                )
                return None

            self._cached_credentials = credentials
            self._credentials_fingerprint = self.compute_fingerprint(credentials)
            self._credentials_file_hash = hashlib.sha256(
                raw_text.encode("utf-8", "ignore")
            ).hexdigest()

            if not silent and logger.isEnabledFor(logging.INFO):
                log_msg = "Successfully loaded Gemini OAuth credentials"
                if force_reload:
                    log_msg += " (force reload)"
                logger.info(log_msg + ".")

            return credentials

        except json.JSONDecodeError as e:
            logger.error(
                f"Error decoding Gemini OAuth credentials JSON: {e}",
                exc_info=True,
            )
            return None
        except OSError as e:
            logger.error(f"Error loading Gemini OAuth credentials: {e}", exc_info=True)
            return None

    async def save(self, credentials: dict[str, Any]) -> bool:
        """Save OAuth credentials to oauth_creds.json file.

        Args:
            credentials: The credentials dictionary to save.

        Returns:
            True if save succeeded, False otherwise.
        """
        try:
            home_dir = Path.home()
            gemini_dir = home_dir / ".gemini"
            gemini_dir.mkdir(parents=True, exist_ok=True)
            creds_path = gemini_dir / "oauth_creds.json"

            with open(creds_path, "w", encoding="utf-8") as f:
                json.dump(credentials, f, indent=4)
            logger.info(f"Gemini OAuth credentials saved to {creds_path}")
            return True
        except OSError as e:
            logger.error(f"Error saving Gemini OAuth credentials: {e}", exc_info=True)
            return False

    def get_fingerprint(self) -> str | None:
        """Get the current credentials fingerprint.

        Returns:
            The fingerprint string or None if not computed.
        """
        return self._credentials_fingerprint

    def get_file_hash(self) -> str | None:
        """Get the current credentials file hash.

        Returns:
            The file hash string or None if not computed.
        """
        return self._credentials_file_hash

    def get_last_modified(self) -> float:
        """Get the last modified timestamp.

        Returns:
            The last modified timestamp.
        """
        return self._last_modified


__all__ = ["FileCredentialProvider"]
