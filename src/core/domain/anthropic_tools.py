"""
Pydantic models for Anthropic tool definitions.

This module defines the data structures for Anthropic tool definitions,
replacing manual dictionary construction with type-safe Pydantic models.
"""

import logging
from typing import Any

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


def _is_flat_anthropic_format(tool: dict[str, Any]) -> bool:
    """
    Detect if a tool definition is in flat Anthropic format.

    Flat format: {"name": "...", "description": "...", "input_schema": {...}}
    Nested format: {"type": "tool", "function": {"name": "...", "input_schema": {...}}}

    A tool is considered flat if:
    - It has "name" at root level, AND
    - Either no "function" key, OR the "function" value is not a dict with "name" in it
    """
    if "name" not in tool:
        return False

    function_value = tool.get("function")
    if function_value is None:
        return True
    if not isinstance(function_value, dict):
        return True
    # If "function" is a dict but doesn't have "name", it's not a proper nested format
    return "name" not in function_value


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
        # Check if this is the flat Anthropic API format
        if _is_flat_anthropic_format(anthropic_tool):
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
            # Attempt to validate as nested format
            try:
                anthropic_tool = AnthropicToolDefinition.model_validate(anthropic_tool)
            except ValidationError as e:
                # If nested validation fails, try falling back to flat format processing
                # This handles edge cases where the structure is ambiguous
                logger.debug(
                    "Nested format validation failed, attempting flat format fallback: %s",
                    e,
                )
                # At this point we know anthropic_tool is a dict (model_validate only accepts dicts)
                # but mypy needs help understanding this
                tool_dict: dict[str, Any] = anthropic_tool  # type: ignore[assignment]

                # Extract name from root level or function if available
                fallback_name = tool_dict.get("name", "")
                if not fallback_name:
                    func = tool_dict.get("function", {})
                    if isinstance(func, dict):
                        fallback_name = func.get("name", "")

                if not fallback_name:
                    # Cannot determine name - re-raise the original error
                    raise

                fallback_description = tool_dict.get("description")
                if not fallback_description:
                    func = tool_dict.get("function", {})
                    if isinstance(func, dict):
                        fallback_description = func.get("description")

                fallback_input_schema = tool_dict.get("input_schema", {})
                if not fallback_input_schema:
                    func = tool_dict.get("function", {})
                    if isinstance(func, dict):
                        fallback_input_schema = func.get("input_schema", {})

                fallback_params: dict[str, Any] = {}
                if isinstance(fallback_input_schema, dict):
                    fallback_params["type"] = fallback_input_schema.get(
                        "type", "object"
                    )
                    fallback_params["properties"] = fallback_input_schema.get(
                        "properties", {}
                    )
                    if fallback_input_schema.get("required"):
                        fallback_params["required"] = fallback_input_schema["required"]

                openai_function = OpenAIToolFunction(
                    name=fallback_name,
                    description=fallback_description,
                    parameters=fallback_params,
                )
                return OpenAIToolDefinition(type="function", function=openai_function)

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
