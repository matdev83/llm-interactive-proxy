import abc
from typing import Union, Dict, Any, Callable
import httpx
from starlette.responses import StreamingResponse
# Assuming ChatCompletionRequest is defined in models.py or a similar location
# from ...models import ChatCompletionRequest # Placeholder if models is outside src
# For now, let's assume ChatCompletionRequest will be imported where it's used or defined later.
# To make this file runnable standalone for now, we can use a forward reference or Any.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models import ChatCompletionRequest # Corrected path assuming models.py is in src

class LLMBackend(abc.ABC):
    """
    Abstract base class for Large Language Model (LLM) backends.
    Defines the interface for interacting with different LLM providers.
    """

    @abc.abstractmethod
    async def chat_completions(
        self,
        request_data: 'ChatCompletionRequest',
        processed_messages: list,  # Messages after command processing
        effective_model: str,  # Model after considering override
        openrouter_api_base_url: str,  # This might need to be more generic if we have more backends
        openrouter_headers_provider: Callable[[], Dict[str, str]],  # Same as above
        project: str | None = None,
    ) -> Union[StreamingResponse, Dict[str, Any]]:
        """
        Forwards a chat completion request to the LLM backend.

        Args:
            request_data: The request payload, conforming to ChatCompletionRequest model.
            processed_messages: The list of messages after command processing.
            effective_model: The model name to be used after considering any overrides.
            openrouter_api_base_url: The base URL for the OpenRouter API.
                                     (Will need generalization if supporting other backends)
            openrouter_headers_provider: A callable that returns a dictionary of headers
                                         required for OpenRouter API. (Needs generalization)

        Returns:
            A StreamingResponse if the request is for a stream, or a dictionary
            representing the JSON response for a non-streaming request.
        """
        pass
