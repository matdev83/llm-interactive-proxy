from typing import Any

from pydantic import BaseModel, Field


class ProcessedResult(BaseModel):
    """
    Represents the result of processing a list of messages for commands.
    """

    modified_messages: list[Any] = Field(
        ..., description="The list of messages after processing."
    )
    command_executed: bool = Field(..., description="Whether a command was executed.")
    command_results: list[Any] = Field(
        ..., description="A list of results from executed commands."
    )
