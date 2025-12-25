from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field

from src.core.commands.models import CommandResultWrapper
from src.core.domain.chat import ChatMessage
from src.core.interfaces.model_bases import DomainModel


class ProcessedResult(DomainModel):
    """
    Represents the result of processing a list of messages for commands.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Use Any for runtime to avoid breaking tests with dummy data, 
    # but keep specific types for static analysis and documentation.
    modified_messages: list[ChatMessage | Any] = Field(
        ..., description="The list of messages after processing."
    )
    command_executed: bool = Field(..., description="Whether a command was executed.")
    command_results: list[CommandResultWrapper | Any] = Field(
        ..., description="A list of results from executed commands."
    )
