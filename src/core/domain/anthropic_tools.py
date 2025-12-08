"""
Pydantic models for Anthropic tool definitions.

This module defines the data structures for Anthropic tool definitions,
replacing manual dictionary construction with type-safe Pydantic models.
"""

from typing import Any
import logging

from pydantic import BaseModel, Field, ValidationError
from pydantic.config import ConfigDict

logger = logging.getLogger(__name__)


class AnthropicToolSchema(BaseModel):
    """Schema definition for Anthropic tool input parameters."""

    type: str = Field(description="Schema type, typically 'object'")
    properties: dict[str, Any] = Field(
        default_factory=dict, description="Properties definition for the schema"
    )
    required: list[str] | None = Field(
        default=None, description="List of required property names"
    )

    model_config = ConfigDict(extra="allow")  # Allow additional fields for flexibility


class AnthropicToolFunction(BaseModel):
    """Function definition for Anthropic tools."""

    name: str = Field(description="Function name")
    description: str | None = Field(default=None, description="Function description")
    input_schema: AnthropicToolSchema = Field(
        description="Input schema for the function"
    )


class AnthropicToolDefinition(BaseModel):
    """Complete Anthropic tool definition."""

    type: str = Field(default="tool", description="Tool type")
    function: AnthropicToolFunction = Field(description="Function definition")


class OpenAIToolFunction(BaseModel):
    """OpenAI function definition for tools."""

    name: str = Field(description="Function name")
    description: str | None = Field(default=None, description="Function description")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters schema (maps from Anthropic input_schema)",
    )


class OpenAIToolDefinition(BaseModel):
    """OpenAI tool definition."""

    type: str = Field(default="function", description="Tool type")
    function: OpenAIToolFunction = Field(description="Function definition")

    def model_dump(self, **kwargs) -> dict[str, Any]:
        """
        Convert to dictionary format expected by OpenAI API.

        Returns the tool definition in OpenAI format:
        {
            "type": "function",
            "function": {
                "name": str,
                "description": str,
                "parameters": {...}
            }
        }
        """
        return super().model_dump(**kwargs)


def convert_anthropic_tool_to_openai(
    anthropic_tool: dict[str, Any] | AnthropicToolDefinition,
) -> OpenAIToolDefinition:
    """
    Convert an Anthropic tool definition to OpenAI format using Pydantic models.

    Handles both Anthropic API formats:
    1. Flat format (Claude Code/standard Anthropic API):
       {"name": "...", "description": "...", "input_schema": {...}}
    2. Nested format (legacy/OpenAI-style):
       {"type": "tool", "function": {"name": "...", "description": "...", "input_schema": {...}}}

    Args:
        anthropic_tool: Anthropic tool definition (dict or Pydantic model)

    Returns:
        OpenAI tool definition as Pydantic model
    """
    if isinstance(anthropic_tool, dict):
        # Check if this is the flat Anthropic API format (name at root level)
        # This means it has a 'name' field, and either no 'function' field,
        # or the 'function' field is present but its value is not a dictionary
        if "name" in anthropic_tool and (
            "function" not in anthropic_tool
            or not isinstance(anthropic_tool.get("function"), dict)
        ):
            logger.debug("Identified as flat Anthropic tool format.")
            # Flat Anthropic format: {"name": "...", "description": "...", "input_schema": {...}}
            name = anthropic_tool.get("name", "")
            description = anthropic_tool.get("description")
            input_schema = anthropic_tool.get("input_schema", {})

            # Build parameters from input_schema
            parameters: dict[str, Any] = {}
            if isinstance(input_schema, dict):
                parameters["type"] = input_schema.get("type", "object")
                parameters["properties"] = input_schema.get("properties", {})
                if input_schema.get("required"):
                    parameters["required"] = input_schema["required"]
                # Copy additional schema fields like $schema, additionalProperties, etc.
                for key in input_schema:
                    if key not in ("type", "properties", "required"):
                        parameters[key] = input_schema[key]

            openai_function = OpenAIToolFunction(
                name=name,
                description=description,
                parameters=parameters,
            )
            return OpenAIToolDefinition(type="function", function=openai_function)
        else:
            # Assume it's a nested format that needs validation
            try:
                anthropic_tool = AnthropicToolDefinition.model_validate(anthropic_tool)
            except ValidationError as e:
                # If validation fails, it might be a flat format missing some keys from the Pydantic model
                # Re-raise if it's not related to 'function' field missing
                if "function" not in str(e) and "Field required" not in str(e):
                    raise
                # Fallback to attempt processing as flat if ValidationError is about missing 'function'
                # This branch handles cases where a flat tool might not have 'name' or 'input_schema'
                # but still shouldn't be treated as a nested tool with a missing function.
                # However, the initial check 'if "name" in anthropic_tool and "function" not in anthropic_tool:'
                # should ideally catch all intended flat tools.
                # If we reach here, it implies a dict that is neither clearly flat nor a valid nested Pydantic.
                # For now, we will re-raise the error as the initial check should be robust enough.
                # If we need to support more ambiguous formats, this logic would need to be expanded.
                raise

    # Handle Pydantic model (nested format)
    input_schema = anthropic_tool.function.input_schema
    parameters = {
        "type": input_schema.type,
        "properties": input_schema.properties,
    }

    # Add required fields if present
    if input_schema.required:
        parameters["required"] = input_schema.required

    # Create OpenAI function definition
    openai_function = OpenAIToolFunction(
        name=anthropic_tool.function.name,
        description=anthropic_tool.function.description,
        parameters=parameters,
    )

    # Create OpenAI tool definition
    return OpenAIToolDefinition(type="function", function=openai_function)
