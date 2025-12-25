from __future__ import annotations

from typing import Annotated, Any

from pydantic import ConfigDict, Field, SkipValidation

from src.core.commands.models import CommandResultWrapper
from src.core.domain.chat import ChatMessage
from src.core.interfaces.model_bases import DomainModel


class ProcessedResult(DomainModel):
    """
    Represents the result of processing a list of messages for commands.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Use SkipValidation to prevent Pydantic from converting dicts to ChatMessage objects.
    # This preserves the original message types from upstream components.
    modified_messages: Annotated[list[ChatMessage | Any], SkipValidation] = Field(
        ..., description="The list of messages after processing."
    )
    command_executed: bool = Field(..., description="Whether a command was executed.")
    command_results: list[CommandResultWrapper | Any] = Field(
        ..., description="A list of results from executed commands."
    )
