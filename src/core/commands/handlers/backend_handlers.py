from __future__ import annotations

import logging
from typing import Any

from src.core.commands.handlers.base_handler import (
    BaseCommandHandler,
    CommandHandlerResult,
)
from src.core.domain.command_context import CommandContext
from src.core.domain.configuration.session_state_builder import SessionStateBuilder
from src.core.domain.session import SessionStateAdapter
from src.core.interfaces.domain_entities_interface import ISessionState

logger = logging.getLogger(__name__)


class BackendHandler(BaseCommandHandler):
    """Handler for setting the backend."""

    def __init__(self, functional_backends: set[str] | None = None):
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
        return ["!/set(backend=openai)", "!/set(backend=openrouter)"]

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
                success=False, message="Backend value must be a string"
            )

        backend_val = param_value.strip().lower()
        if context:
            # Get BackendRegistry from service provider
            from src.core.services.backend_registry_service import backend_registry

            if backend_val not in backend_registry.get_registered_backends():
                return CommandHandlerResult(
                    success=False, message=f"Backend {backend_val} not supported"
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
                message=f"Backend {backend_val} not functional (session override unset)",
                new_state=unset_state,
            )

        # Create new state with backend override set
        builder = SessionStateBuilder(current_state)
        set_state: ISessionState = SessionStateAdapter(
            builder.with_backend_type(backend_val).build()
        )

        return CommandHandlerResult(
            success=True, message=f"Backend set to {backend_val}", new_state=set_state
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
            "!/set(model=gpt-4)",
            "!/set(model=openrouter:claude-3-opus)",
            "!/set(model=gemini:gemini-pro)",
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
        if not isinstance(param_value, str):
            return CommandHandlerResult(
                success=False, message="Model value must be a string"
            )

        model_val = param_value.strip()

        # Check if the value contains a backend prefix
        if ":" in model_val:
            backend_prefix, model_name = model_val.split(":", 1)

            if context:
                # Get BackendRegistry from service provider
                from src.core.services.backend_registry_service import backend_registry

                if backend_prefix not in backend_registry.get_registered_backends():
                    return CommandHandlerResult(
                        success=False,
                        message=f"Backend {backend_prefix} in model {model_val} not supported",
                    )

            # Set both backend and model
            builder = SessionStateBuilder(current_state)
            new_state = SessionStateAdapter(
                builder.with_backend_type(backend_prefix).with_model(model_name).build()
            )

            return CommandHandlerResult(
                success=True,
                message=f"Backend set to {backend_prefix} with model {model_name}",
                new_state=new_state,
            )
        else:
            # Just set the model
            builder = SessionStateBuilder(current_state)
            new_state = SessionStateAdapter(builder.with_model(model_val).build())

            return CommandHandlerResult(
                success=True, message=f"Model set to {model_val}", new_state=new_state
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
                success=False, message="OpenAI URL value must be a string"
            )

        url_val = param_value.strip()

        # Validate URL format
        if not url_val.startswith(("http://", "https://")):
            return CommandHandlerResult(
                success=False, message="OpenAI URL must start with http:// or https://"
            )

        # Update the state
        builder = SessionStateBuilder(current_state)
        new_state = SessionStateAdapter(
            builder.with_backend_config(
                current_state.backend_config.with_openai_url(url_val)
            ).build()
        )

        return CommandHandlerResult(
            success=True, message=f"OpenAI URL set to {url_val}", new_state=new_state
        )
