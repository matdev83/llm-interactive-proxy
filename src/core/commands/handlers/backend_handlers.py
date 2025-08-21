from __future__ import annotations

import logging
from typing import Any

from src.core.commands.handlers.base_handler import (
    BaseCommandHandler,
    CommandHandlerResult,
)
from src.core.constants.command_output_constants import (
    BACKEND_AND_MODEL_SET_MESSAGE,
    BACKEND_MUST_BE_STRING_MESSAGE,
    BACKEND_NOT_FUNCTIONAL_MESSAGE,
    BACKEND_NOT_SUPPORTED_MESSAGE,
    BACKEND_SET_MESSAGE,
    MODEL_BACKEND_NOT_SUPPORTED_MESSAGE,
    MODEL_MUST_BE_STRING_MESSAGE,
    MODEL_SET_MESSAGE,
    MODEL_UNSET_MESSAGE,
    OPENAI_URL_MUST_BE_STRING_MESSAGE,
    OPENAI_URL_MUST_START_WITH_HTTP_MESSAGE,
    OPENAI_URL_SET_MESSAGE,
)
from src.core.domain.command_context import CommandContext
from src.core.domain.configuration.session_state_builder import SessionStateBuilder
from src.core.domain.session import SessionStateAdapter
from src.core.interfaces.domain_entities_interface import ISessionState

logger = logging.getLogger(__name__)


class BackendHandler(BaseCommandHandler):
    """Handler for setting the backend."""

    def __init__(self, functional_backends: set[str] | None = None) -> None:
        """Initialize the backend handler.

        Args:
            functional_backends: Optional set of functional backends
        """
        super().__init__("backend")
        self.functional_backends = functional_backends

    @property
    def description(self) -> str:
        """Description of the parameter."""
        return "Set backend to use for this session"

    @property
    def examples(self) -> list[str]:
        """Examples of using this parameter."""
        return ["!/set(backend=openai)", "~/set(backend=openrouter)"]

    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle setting the backend.

        Args:
            param_value: The backend value to set
            current_state: The current session state
            context: Optional command context

        Returns:
            Result of the operation
        """
        if not isinstance(param_value, str):
            return CommandHandlerResult(
                success=False, message=BACKEND_MUST_BE_STRING_MESSAGE
            )

        backend_val: str = param_value.strip().lower()
        if context:
            # Get BackendRegistry from service provider
            from src.core.services.backend_registry import backend_registry

            if backend_val not in backend_registry.get_registered_backends():
                return CommandHandlerResult(
                    success=False, message=BACKEND_NOT_SUPPORTED_MESSAGE.format(backend=backend_val)
                )

        # Check against functional_backends if provided
        if (
            self.functional_backends is not None
            and backend_val not in self.functional_backends
        ):
            # Create new state with backend override unset
            builder = SessionStateBuilder(current_state)
            unset_state: ISessionState = SessionStateAdapter(
                builder.with_backend_type(None).build()
            )

            return CommandHandlerResult(
                success=True,
                message=BACKEND_NOT_FUNCTIONAL_MESSAGE.format(backend=backend_val),
                new_state=unset_state,
            )

        # Create new state with backend override set
        builder = SessionStateBuilder(current_state)
        set_state: ISessionState = SessionStateAdapter(
            builder.with_backend_type(backend_val).build()
        )

        return CommandHandlerResult(
            success=True, message=BACKEND_SET_MESSAGE.format(backend=backend_val), new_state=set_state
        )


class ModelHandler(BaseCommandHandler):
    """Handler for setting the model."""

    def __init__(self) -> None:
        """Initialize the model handler."""
        super().__init__("model")

    @property
    def description(self) -> str:
        """Description of the parameter."""
        return "Set model to use for this session"

    @property
    def examples(self) -> list[str]:
        """Examples of using this parameter."""
        return [
            "~/set(model=gpt-4)",
            "~/set(model=openrouter:claude-3-opus)",
            "~/set(model=gemini:gemini-pro)",
        ]

    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle setting the model.

        Args:
            param_value: The model value to set
            current_state: The current session state
            context: Optional command context

        Returns:
            Result of the operation
        """
        # If no value provided, treat this as an unset request
        if param_value is None:
            # Create new backend config with model unset
            new_backend_config = current_state.backend_config.with_model(None)
            # Create new state with updated backend config
            new_state: ISessionState = current_state.with_backend_config(new_backend_config)
            return CommandHandlerResult(
                success=True, message=MODEL_UNSET_MESSAGE, new_state=new_state
            )

        if not isinstance(param_value, str):
            return CommandHandlerResult(
                success=False, message=MODEL_MUST_BE_STRING_MESSAGE
            )

        model_val: str = param_value.strip()

        # Check if the value contains a backend prefix
        if ":" in model_val:
            backend_prefix: str
            model_name: str
            backend_prefix, model_name = model_val.split(":", 1)

            if context:
                # Get BackendRegistry from service provider
                from src.core.services.backend_registry import backend_registry

                if backend_prefix not in backend_registry.get_registered_backends():
                    return CommandHandlerResult(
                        success=False,
                        message=MODEL_BACKEND_NOT_SUPPORTED_MESSAGE.format(backend=backend_prefix, model=model_val),
                    )

            # Set both backend and model
            builder = SessionStateBuilder(current_state)
            new_state = SessionStateAdapter(
                builder.with_backend_type(backend_prefix).with_model(model_name).build()
            )

            return CommandHandlerResult(
                success=True,
                message=BACKEND_AND_MODEL_SET_MESSAGE.format(backend=backend_prefix, model=model_name),
                new_state=new_state,
            )
        else:
            # Just set the model
            builder = SessionStateBuilder(current_state)
            new_state = SessionStateAdapter(builder.with_model(model_val).build())

            return CommandHandlerResult(
                success=True, message=MODEL_SET_MESSAGE.format(model=model_val), new_state=new_state
            )


class OpenAIUrlHandler(BaseCommandHandler):
    """Handler for setting the OpenAI URL."""

    def __init__(self) -> None:
        """Initialize the OpenAI URL handler."""
        super().__init__("openai-url", ["openai_url"])

    @property
    def description(self) -> str:
        """Description of the parameter."""
        return "Set custom URL for OpenAI API calls"

    @property
    def examples(self) -> list[str]:
        """Examples of using this parameter."""
        return ["!/set(openai-url=https://api.example.com/v1)"]

    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle setting the OpenAI URL.

        Args:
            param_value: The URL value to set
            current_state: The current session state
            context: Optional command context

        Returns:
            Result of the operation
        """
        if not isinstance(param_value, str):
            return CommandHandlerResult(
                success=False, message=OPENAI_URL_MUST_BE_STRING_MESSAGE
            )

        url_val: str = param_value.strip()

        # Validate URL format
        if not url_val.startswith(("http://", "https://")):
            return CommandHandlerResult(
                success=False, message=OPENAI_URL_MUST_START_WITH_HTTP_MESSAGE
            )

        # Update the state
        builder: SessionStateBuilder = SessionStateBuilder(current_state)
        new_state: SessionStateAdapter = SessionStateAdapter(
            builder.with_backend_config(
                current_state.backend_config.with_openai_url(url_val)
            ).build()
        )

        return CommandHandlerResult(
            success=True, message=OPENAI_URL_SET_MESSAGE.format(url=url_val), new_state=new_state
        )