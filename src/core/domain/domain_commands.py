from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class CommandResult(BaseModel):
    """
    Represents the result of processing commands from a list of messages.
    """

    processed: bool = Field(..., description="Whether any commands were processed.")
    output: str | None = Field(None, description="The output of the command, if any.")
    remaining_messages: list[Any] = Field(
        ..., description="The list of messages remaining after command processing."
    )
    success: bool = Field(False, description="Whether the command was successful.")
    message: str | None = Field(None, description="A message describing the result.")
    data: dict[str, Any] = Field(default_factory=dict, description="Additional data from the command.")
    
    class Config:
        # Allow extra fields to be provided to the constructor
        extra = "allow"
        
    def __init__(self, *args, **data: Any):
        # Handle positional arguments from test code
        if len(args) >= 2 and isinstance(args[0], str) and isinstance(args[1], bool):
            # This is the old format: name, success, message
            name = args[0]
            success = args[1]
            message = args[2] if len(args) > 2 else ""
            
            # Set the fields
            data["success"] = success
            data["message"] = message
            data["data"] = {"name": name}
            data["processed"] = True
            data["remaining_messages"] = []
        elif "success" in data and isinstance(data["success"], bool):
            if "message" in data and isinstance(data["message"], str):
                if "data" not in data:
                    data["data"] = {}
                if "processed" not in data:
                    data["processed"] = True
                if "remaining_messages" not in data:
                    data["remaining_messages"] = []
        super().__init__(**data)


class BaseCommand(ABC):
    """
    The base class for all commands.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The name of the command."""
        raise NotImplementedError

    @abstractmethod
    async def execute(self, *args: Any, **kwargs: Any) -> CommandResult:
        """
        Executes the command.

        Returns:
            A CommandResult object.
        """
        raise NotImplementedError
