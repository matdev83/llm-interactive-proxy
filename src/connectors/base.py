from __future__ import annotations

import abc
import time
from typing import TYPE_CHECKING, Any, cast

from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO

if TYPE_CHECKING:
    from src.core.interfaces.response_processor_interface import IResponseProcessor


def strip_vendor_prefix(model: str, vendor: str) -> str:
    """Strip vendor prefix from model name if present.

    This utility helps single-vendor backends accept both vendor-prefixed
    and non-prefixed model names for backward compatibility.

    Args:
        model: Model name (e.g., "google/gemini-2.5-pro" or "gemini-2.5-pro")
        vendor: Expected vendor prefix (e.g., "google")

    Returns:
        Model name without vendor prefix (e.g., "gemini-2.5-pro")
    """
    prefix = f"{vendor}/"
    if model.startswith(prefix):
        return model[len(prefix) :]
    return model


def add_vendor_prefix(model: str, vendor: str) -> str:
    """Add vendor prefix to model name if not present.

    This utility helps single-vendor backends return fully qualified
    model names in get_available_models() for unified model routing.

    Args:
        model: Model name (e.g., "gemini-2.5-pro")
        vendor: Vendor prefix to add (e.g., "google")

    Returns:
        Model name with vendor prefix (e.g., "google/gemini-2.5-pro")
    """
    prefix = f"{vendor}/"
    if model.startswith(prefix):
        return model
    return f"{prefix}{model}"


class LLMBackend(abc.ABC):
    """
    Abstract base class for Large Language Model (LLM) backends.
    Defines the interface for interacting with different LLM providers.
    """

    backend_type: str

    def __init__(
        self, config: AppConfig, response_processor: IResponseProcessor | None = None
    ) -> None:  # Modified
        self._response_processor = response_processor
        self.config = config  # Stored config
        self._retry_after_until: float | None = None

    @abc.abstractmethod
    async def chat_completions(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list,  # Messages after command processing (domain objects or dicts)
        effective_model: str,  # Model after considering override
        identity: IAppIdentityConfig | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """
        Forwards a chat completion request to the LLM backend.

        Args:
            request_data: The request payload as a domain `ChatRequest`.
            processed_messages: The list of messages after command processing.
            effective_model: The model name to be used after considering any overrides.
            **kwargs: Additional keyword arguments for the backend.

        Returns:
            Either a ResponseEnvelope for non-streaming requests or
            a StreamingResponseEnvelope for streaming requests.
        """

    @abc.abstractmethod
    async def initialize(self, **kwargs: Any) -> None:
        """
        Initialize the backend with configuration.

        Args:
            **kwargs: Configuration parameters for the backend.
        """

    @abc.abstractmethod
    def get_available_models(self) -> list[str]:
        """
        Get a list of available models for this backend.

        IMPORTANT: All implementations MUST return model names with vendor prefixes
        in the format "<vendor>/<model-name>" for unified model routing.

        Examples:
            - ["google/gemini-2.5-pro", "google/gemini-2.5-flash"]
            - ["anthropic/claude-3-opus", "anthropic/claude-3-sonnet"]
            - ["openai/gpt-4", "openai/gpt-3.5-turbo"]

        For multi-vendor backends (like OpenRouter), models should already
        include the vendor prefix from the upstream provider.

        Use the `add_vendor_prefix()` utility function to ensure consistent
        prefixing when returning models from single-vendor backends.

        Returns:
            A list of model identifiers with vendor prefixes (e.g., "vendor/model-name").
        """

    def set_retry_after(self, retry_after_seconds: float) -> None:
        """
        Set the retry-after timestamp for this backend instance.

        Args:
            retry_after_seconds: Number of seconds to wait before retrying
        """
        if not hasattr(self, "_retry_after_until"):
            self._retry_after_until = None
        self._retry_after_until = time.time() + retry_after_seconds

    def get_retry_after_remaining(self) -> float | None:
        """
        Get the remaining seconds until retry-after expires.

        Returns:
            Remaining seconds if retry-after is active, None otherwise
        """
        retry_until = cast(float | None, getattr(self, "_retry_after_until", None))
        if retry_until is None:
            return None

        remaining = retry_until - time.time()
        if remaining <= 0:
            self._retry_after_until = None
            return None

        return remaining

    def is_rate_limited(self) -> bool:
        """
        Check if this backend is currently rate limited.

        Returns:
            True if rate limited, False otherwise
        """
        return self.get_retry_after_remaining() is not None

    def is_backend_functional(self) -> bool:
        """
        Check if this backend is currently functional.
        Default implementation returns True. Subclasses can override.
        """
        return True

    async def _validate_runtime_credentials(self) -> bool:
        """
        Attempt to validate runtime credentials and recover if possible.
        Default implementation returns False (no recovery attempt). Subclasses can override.
        """
        return False

    def get_validation_errors(self) -> list[str]:
        """
        Get a list of validation errors if the backend is not functional.
        Default implementation returns an empty list. Subclasses can override.
        """
        return []
