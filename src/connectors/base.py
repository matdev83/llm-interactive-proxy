from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any

from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO

if TYPE_CHECKING:
    from src.core.interfaces.response_processor_interface import IResponseProcessor


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

    def get_available_models(self) -> list[str]:
        """
        Get a list of available models for this backend.

        Returns:
            A list of model identifiers supported by this backend.
        """
        return []
