"""Captcha verification service for the SSO login flow."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from src.core.auth.sso.config import CaptchaConfig
from src.core.auth.sso.exceptions import AuthenticationError, ConfigurationError

logger = logging.getLogger(__name__)


@dataclass
class CaptchaVerificationResult:
    """Result of a captcha verification attempt."""

    success: bool
    error_codes: list[str] = field(default_factory=list)
    action: str | None = None
    ray_id: str | None = None


class CaptchaService:
    """Service that validates captcha challenges with a hosted provider."""

    def __init__(self, config: CaptchaConfig | None):
        """
        Initialize captcha service.

        Args:
            config: Captcha configuration or None if disabled
        """
        self.config = config

    @property
    def is_enabled(self) -> bool:
        """Return True when captcha verification is required."""
        return bool(self.config and self.config.enabled)

    async def verify(
        self, captcha_token: str | None, remote_ip: str | None = None
    ) -> CaptchaVerificationResult:
        """
        Validate a captcha token against the configured provider.

        Args:
            captcha_token: Token returned by the captcha widget
            remote_ip: Optional client IP for provider telemetry

        Returns:
            CaptchaVerificationResult describing verification outcome

        Raises:
            ConfigurationError: If required secrets are missing
            AuthenticationError: If the provider cannot be reached or returns bad data
        """
        if not self.is_enabled:
            return CaptchaVerificationResult(success=True)

        # At this point, self.config must be non-None because is_enabled checks it
        assert self.config is not None, "Config must be set when captcha is enabled"
        config = self.config

        if not config.site_key or not config.secret_key:
            raise ConfigurationError(
                "Captcha is enabled but site_key or secret_key is not configured",
                details={"provider": config.provider},
            )

        if not captcha_token:
            return CaptchaVerificationResult(
                success=False, error_codes=["missing-token"]
            )

        payload: dict[str, Any] = {
            "secret": config.secret_key,
            "response": captcha_token,
        }
        if remote_ip:
            payload["remoteip"] = remote_ip

        try:
            async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
                response = await client.post(config.verify_url, data=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Captcha provider returned HTTP error",
                exc_info=True,
                extra={
                    "status": exc.response.status_code,
                    "provider": config.provider,
                },
            )
            raise AuthenticationError(
                "Captcha verification failed",
                details={
                    "reason": "provider_http_error",
                    "status_code": exc.response.status_code,
                },
            ) from exc
        except httpx.HTTPError as exc:
            logger.error(
                "Captcha verification failed due to network error",
                exc_info=True,
                extra={"provider": config.provider},
            )
            raise AuthenticationError(
                "Captcha verification failed",
                details={"reason": "provider_unreachable"},
            ) from exc

        try:
            result_json = response.json()
        except ValueError as exc:
            raise AuthenticationError(
                "Captcha verification failed",
                details={"reason": "invalid_response"},
            ) from exc

        success = bool(result_json.get("success"))
        error_codes = [str(code) for code in result_json.get("error-codes", []) if code]
        return CaptchaVerificationResult(
            success=success,
            error_codes=error_codes,
            action=result_json.get("action"),
            ray_id=result_json.get("ray_id")
            or result_json.get("cdata")
            or result_json.get("rayid"),
        )
