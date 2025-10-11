"""
Pydantic models for Anthropic tool definitions.

This module defines the data structures for Anthropic tool definitions,
replacing manual dictionary construction with type-safe Pydantic models.
"""

from typing import Any

from pydantic import BaseModel, Field


class AnthropicToolSchema(BaseModel):
    """Schema definition for Anthropic tool input parameters."""

    type: str = Field(description="Schema type, typically 'object'")
    properties: dict[str, Any] = Field(
        default_factory=dict, description="Properties definition for the schema"
    )
    required: list[str] | None = Field(
        default=None, description="List of required property names"
    )

    class Config:
        extra = "allow"  # Allow additional fields for flexibility


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

    Args:
        anthropic_tool: Anthropic tool definition (dict or Pydantic model)

    Returns:
        OpenAI tool definition as Pydantic model
    """
    # Convert dict to Pydantic model if needed
    if isinstance(anthropic_tool, dict):
        anthropic_tool = AnthropicToolDefinition.model_validate(anthropic_tool)

    # Convert the input_schema to parameters format
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
