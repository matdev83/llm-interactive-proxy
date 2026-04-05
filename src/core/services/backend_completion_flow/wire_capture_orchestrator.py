"""Wire capture orchestration collaborator."""

# pyright: reportPrivateUsage=false
from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from typing import cast

from pydantic.types import JsonValue

from src.core.config.app_config import AppConfig, BackendConfig
from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.usage_canonical_record import CanonicalUsageRecord
from src.core.interfaces.backend_completion_collaborators import (
    IWireCaptureOrchestrator,
)
from src.core.interfaces.backend_config_provider_interface import IBackendConfigProvider
from src.core.interfaces.configuration_interface import IAppIdentityConfig, IConfig
from src.core.interfaces.domain_entities_interface import ISession
from src.core.interfaces.wire_capture_interface import IWireCapture

logger = logging.getLogger(__name__)


def _collect_api_keys_from_env(base_name: str) -> dict[str, str]:
    """Collect API keys from environment.

    Mirrors the legacy config_loader._collect_api_keys behavior without importing
    the deprecated module (which emits DeprecationWarning).
    """

    single_key = os.getenv(base_name)
    numbered_keys: dict[str, str] = {}
    for i in range(1, 21):
        key = os.getenv(f"{base_name}_{i}")
        if key:
            numbered_keys[f"{base_name}_{i}"] = key

    if single_key and numbered_keys:
        logger.warning(
            "Both %s and %s_<n> environment variables are set. Prioritizing %s_<n> and ignoring %s.",
            base_name,
            base_name,
            base_name,
            base_name,
        )
        return numbered_keys

    if single_key:
        return {base_name: single_key}

    return numbered_keys


class WireCaptureOrchestrator(IWireCaptureOrchestrator):
    """Handles wire capture operations."""

    def __init__(
        self,
        wire_capture: IWireCapture | None,
        config: IConfig,
        backend_config_service: IBackendConfigProvider,
    ):
        """Initialize the wire capture orchestrator.

        Args:
            wire_capture: Wire capture service (optional)
            config: Application configuration
            backend_config_service: Backend configuration provider
        """
        self._wire_capture = wire_capture
        self._config = config
        self._backend_config_service = backend_config_service

    @staticmethod
    def _is_cbor_capture_service(wire_capture: IWireCapture | None) -> bool:
        if wire_capture is None:
            return False
        return type(wire_capture).__name__ == "CborWireCaptureService"

    async def prepare_wire_capture_context(
        self, backend_type: str, session: ISession | None
    ) -> IAppIdentityConfig | None:
        """Prepare identity and backend config for wire capture.

        Args:
            backend_type: The backend name
            session: Optional session object

        Returns:
            Identity object with session context (IAppIdentityConfig or None)
        """
        app_config_typed: AppConfig = cast(AppConfig, self._config)

        # Fetch config from provider
        provider_backend_config = None
        if self._backend_config_service:
            config_or_app = self._backend_config_service.get_backend_config(
                backend_type
            )
            if isinstance(config_or_app, BackendConfig):
                provider_backend_config = config_or_app

        # Determine identity
        if provider_backend_config and getattr(
            provider_backend_config, "identity", None
        ):
            identity = provider_backend_config.identity
        else:
            backend_config_from_app = app_config_typed.backends.get(backend_type)
            identity = (
                backend_config_from_app.identity
                if backend_config_from_app and backend_config_from_app.identity
                else app_config_typed.identity
            )

        # Populate session turn count if session is available
        if session and hasattr(session, "history") and identity:
            identity = identity.model_copy(
                update={"session_turn_count": len(session.history)}
            )

        return identity

    async def capture_wire_outbound(
        self,
        backend_type: str,
        effective_model: str,
        domain_request: CanonicalChatRequest,
        context: RequestContext | None,
    ) -> None:
        """Capture outbound wire payload (best-effort).

        Args:
            backend_type: The backend name
            effective_model: The model name
            domain_request: The request to capture
            context: Optional request context
        """
        try:
            if self._wire_capture and self._wire_capture.enabled():
                # CBOR capture now records backend HTTP boundary bytes in connector
                # transport handlers; skip pre-connector domain payload snapshots.
                if self._is_cbor_capture_service(self._wire_capture):
                    return
                key_name = self.detect_key_name(backend_type)
                session_id = getattr(context, "session_id", None)
                await self._wire_capture.capture_outbound_request(
                    context=context,
                    session_id=session_id,
                    backend=backend_type,
                    model=effective_model,
                    key_name=key_name,
                    request_payload=domain_request,
                    capture_metadata=self._extract_capture_metadata(context),
                )
        except (ValueError, TypeError, AttributeError, RuntimeError, OSError):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Wire capture (request) failed for backend %s with model %s",
                    backend_type,
                    effective_model,
                    exc_info=True,
                )
        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Wire capture (request) failed for backend %s with model %s: %s",
                    backend_type,
                    effective_model,
                    str(e),
                    exc_info=True,
                )

    def detect_key_name(self, backend_type: str) -> str | None:
        """Derive API key name (env var) for the backend when possible.

        Args:
            backend_type: The backend name

        Returns:
            The key name or backend_type if not found
        """
        try:
            app_config: AppConfig = cast(AppConfig, self._config)
            backend_cfg = app_config.backends.get(backend_type)
            api_key_value: str | None = None
            if backend_cfg and getattr(backend_cfg, "api_key", None):
                keys = backend_cfg.api_key
                api_key_value = keys[0] if keys else None
            if not api_key_value:
                return backend_type

            env_base = {
                "openrouter": "OPENROUTER_API_KEY",
                "gemini": "GEMINI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "zai": "ZAI_API_KEY",
                "zenmux": "ZENMUX_API_KEY",
                "minimax": "MINIMAX_API_KEY",
            }.get(backend_type)
            if not env_base:
                return backend_type
            mapping = _collect_api_keys_from_env(env_base)
            for name, value in mapping.items():
                if value == api_key_value:
                    return name
        except (ValueError, TypeError, AttributeError, KeyError):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("_detect_key_name failed", exc_info=True)
        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "_detect_key_name failed unexpectedly: %s", str(e), exc_info=True
                )
        return backend_type

    @staticmethod
    def _extract_capture_metadata(
        context: RequestContext | None,
    ) -> dict[str, JsonValue] | None:
        if context is None:
            return None
        metadata: dict[str, JsonValue] = {}
        for key in ("account_id", "retry_attempt", "is_retry", "call_purpose"):
            if key in context.extensions:
                metadata[key] = context.extensions[key]
        return metadata or None

    async def capture_inbound_response(
        self,
        context: RequestContext | None,
        session_id: str | None,
        backend_type: str,
        effective_model: str,
        key_name: str | None,
        response_content: dict[str, JsonValue] | bytes | None,
        canonical_usage: CanonicalUsageRecord | None = None,
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> None:
        """Capture inbound response payload (best-effort).

        Args:
            context: Request context
            session_id: Session ID
            backend_type: Backend type
            effective_model: Model name
            key_name: Key name for redaction
            response_content: The response content (JSON-serializable dict, bytes, or None)
            canonical_usage: Optional canonical usage record
        """
        try:
            if self._wire_capture and self._wire_capture.enabled():
                # CBOR capture records backend HTTP boundary responses at connector
                # transport boundaries; skip post-translation envelope snapshots.
                if self._is_cbor_capture_service(self._wire_capture):
                    return
                await self._wire_capture.capture_inbound_response(
                    context=context,
                    session_id=session_id,
                    backend=backend_type,
                    model=effective_model,
                    key_name=key_name,
                    response_content=response_content,
                    canonical_usage=canonical_usage,
                    capture_metadata=capture_metadata,
                )
        except (ValueError, TypeError, AttributeError, RuntimeError, OSError):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Wire capture (response) failed for backend %s with model %s",
                    backend_type,
                    effective_model,
                    exc_info=True,
                )
        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Wire capture (response) failed for backend %s with model %s: %s",
                    backend_type,
                    effective_model,
                    str(e),
                    exc_info=True,
                )

    def wrap_inbound_stream(
        self,
        context: RequestContext | None,
        session_id: str | None,
        backend_type: str,
        effective_model: str,
        key_name: str | None,
        stream: AsyncIterator[bytes],
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> AsyncIterator[bytes]:
        """Wrap inbound stream for wire capture.

        Args:
            context: Request context
            session_id: Session ID
            backend_type: Backend type
            effective_model: Model name
            key_name: Key name for redaction
            stream: The input byte stream

        Returns:
            Wrapped byte stream
        """
        try:
            if self._wire_capture and self._wire_capture.enabled():
                return self._wire_capture.wrap_inbound_stream(
                    context=context,
                    session_id=session_id,
                    backend=backend_type,
                    model=effective_model,
                    key_name=key_name,
                    stream=stream,
                    capture_metadata=capture_metadata,
                )
        except (ValueError, TypeError, AttributeError, RuntimeError, OSError):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Wire capture (stream wrap) failed for backend %s with model %s",
                    backend_type,
                    effective_model,
                    exc_info=True,
                )
        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Wire capture (stream wrap) failed for backend %s with model %s: %s",
                    backend_type,
                    effective_model,
                    str(e),
                    exc_info=True,
                )
        return stream

    async def capture_stream_completion(
        self,
        context: RequestContext | None,
        session_id: str | None,
        backend_type: str,
        effective_model: str,
        key_name: str | None,
        canonical_usage: CanonicalUsageRecord | None = None,
        eos_metadata: dict[str, JsonValue] | None = None,
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> None:
        """Capture canonical usage for completed streaming response (best-effort).

        Args:
            context: Request context
            session_id: Session ID
            backend_type: Backend type
            effective_model: Model name
            key_name: Key name for redaction
            canonical_usage: Optional canonical usage record
            eos_metadata: Optional End-of-Session metadata (JSON-serializable values only)
        """
        try:
            if self._wire_capture and self._wire_capture.enabled():
                await self._wire_capture.capture_stream_completion(
                    context=context,
                    session_id=session_id,
                    backend=backend_type,
                    model=effective_model,
                    key_name=key_name,
                    canonical_usage=canonical_usage,
                    eos_metadata=eos_metadata,
                    capture_metadata=capture_metadata,
                )
        except (ValueError, TypeError, AttributeError, RuntimeError, OSError):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Wire capture (stream completion) failed for backend %s with model %s",
                    backend_type,
                    effective_model,
                    exc_info=True,
                )
        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Wire capture (stream completion) failed for backend %s with model %s: %s",
                    backend_type,
                    effective_model,
                    str(e),
                    exc_info=True,
                )
