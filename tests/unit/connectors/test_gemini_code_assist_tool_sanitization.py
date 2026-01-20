from src.connectors.gemini_base.tool_sanitizer import (
    normalize_code_assist_request_tools,
)
from src.connectors.gemini_oauth_base import GeminiOAuthBaseConnector
from src.core.domain.chat import CanonicalChatRequest, ChatMessage


def test_sanitize_code_assist_tools_strips_custom_and_rebuilds_functions() -> None:
    canonical = CanonicalChatRequest(
        model="antigravity-oauth",
        messages=[ChatMessage(role="user", content="hi")],
        tools=[
            {"type": "custom", "custom": {"input_schema": {"type": "object"}}},
            {
                "function": {
                    "name": "do_thing",
                    "description": "Do the thing",
                    "parameters": {
                        "$schema": "http://json-schema.org/draft-07/schema#",
                        "type": "object",
                        "properties": {"id": {"type": "string", "format": "uuid"}},
                    },
                }
            },
        ],
        tool_choice={"type": "function", "function": {"name": "do_thing"}},
    )

    code_assist_request = {
        "tools": [
            {"custom": {"input_schema": {"type": "object"}}},
            {"function_declarations": [{"name": "placeholder"}]},
        ],
        "toolConfig": {"functionCallingConfig": {"allowedFunctionNames": ["do_thing"]}},
    }

    GeminiOAuthBaseConnector._sanitize_code_assist_tools(canonical, code_assist_request)

    tools = code_assist_request.get("tools")
    assert isinstance(tools, list) and len(tools) == 1
    declarations = tools[0].get("function_declarations")
    assert isinstance(declarations, list) and len(declarations) == 1

    func = declarations[0]
    assert func["name"] == "do_thing"
    assert func["description"] == "Do the thing"
    # format and $schema should be stripped
    assert func["parameters"] == {
        "type": "object",
        "properties": {"id": {"type": "string"}},
    }

    tool_config = code_assist_request.get("toolConfig", {})
    assert isinstance(tool_config, dict)
    fcc = tool_config.get("functionCallingConfig", {})
    assert fcc.get("allowedFunctionNames") == ["do_thing"]


def test_sanitize_code_assist_tools_drops_existing_custom_entries() -> None:
    """Custom tool entries from existing request should be removed."""
    canonical = CanonicalChatRequest(
        model="antigravity-oauth",
        messages=[ChatMessage(role="user", content="hi")],
        tools=None,
    )

    code_assist_request = {
        "tools": [
            {"custom": {"input_schema": {"type": "object"}}},
            {"function_declarations": [{"name": "keep_me"}]},
        ],
        "toolConfig": {"functionCallingConfig": {"allowedFunctionNames": ["keep_me"]}},
    }

    GeminiOAuthBaseConnector._sanitize_code_assist_tools(canonical, code_assist_request)

    tools = code_assist_request.get("tools")
    assert isinstance(tools, list) and len(tools) == 1
    declarations = tools[0].get("function_declarations")
    assert isinstance(declarations, list) and declarations[0]["name"] == "keep_me"


def test_sanitize_code_assist_tools_handles_direct_name_format() -> None:
    """Tools with direct name/description/parameters format should be converted.

    This is the format used by some agents like Droid/Factory CLI.
    """
    canonical = CanonicalChatRequest(
        model="antigravity-oauth",
        messages=[ChatMessage(role="user", content="hi")],
        tools=[
            {
                "name": "read_file",
                "description": "Read a file from the filesystem",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        ],
    )

    code_assist_request: dict = {}

    GeminiOAuthBaseConnector._sanitize_code_assist_tools(canonical, code_assist_request)

    tools = code_assist_request.get("tools")
    assert isinstance(tools, list) and len(tools) == 1
    declarations = tools[0].get("function_declarations")
    assert isinstance(declarations, list) and len(declarations) == 1

    func = declarations[0]
    assert func["name"] == "read_file"
    assert func["description"] == "Read a file from the filesystem"
    assert func["parameters"] == {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }


def test_sanitize_code_assist_tools_converts_properties_list() -> None:
    """Map-style properties lists should be converted to properties dicts."""
    canonical = CanonicalChatRequest(
        model="antigravity-oauth",
        messages=[ChatMessage(role="user", content="hi")],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "tool_test",
                    "description": "Test tool",
                    "parameters": {
                        "type": "object",
                        "properties": [
                            {"key": "path", "value": {"type": "string"}},
                            {
                                "key": "options",
                                "value": {
                                    "type": "object",
                                    "properties": [
                                        {
                                            "key": "recursive",
                                            "value": {"type": "boolean"},
                                        }
                                    ],
                                },
                            },
                        ],
                        "required": ["path"],
                    },
                },
            }
        ],
    )

    code_assist_request: dict = {}

    GeminiOAuthBaseConnector._sanitize_code_assist_tools(canonical, code_assist_request)

    tools = code_assist_request.get("tools")
    assert isinstance(tools, list) and len(tools) == 1
    declarations = tools[0].get("function_declarations")
    assert isinstance(declarations, list) and len(declarations) == 1

    func = declarations[0]
    assert func["parameters"]["properties"]["path"]["type"] == "string"
    assert (
        func["parameters"]["properties"]["options"]["properties"]["recursive"]["type"]
        == "boolean"
    )


def test_normalize_code_assist_request_tools() -> None:
    request_body = {
        "request": {
            "tools": [
                {
                    "function_declarations": [
                        {
                            "name": "tool_test",
                            "parameters": {
                                "type": "object",
                                "properties": [
                                    {"key": "path", "value": {"type": "string"}},
                                ],
                                "required": ["path"],
                            },
                        }
                    ]
                }
            ]
        }
    }

    normalize_code_assist_request_tools(request_body)

    request_section = request_body.get("request", {})
    assert isinstance(request_section, dict)
    tools = request_section.get("tools")
    assert isinstance(tools, list)
    declarations = tools[0].get("function_declarations")
    assert isinstance(declarations, list)
    params = declarations[0].get("parameters")
    assert isinstance(params, dict)
    assert params["properties"]["path"]["type"] == "string"


def test_sanitize_code_assist_tools_handles_anthropic_input_schema_format() -> None:
    """Tools with input_schema (Anthropic format) should be converted.

    Anthropic uses input_schema instead of parameters.
    """
    canonical = CanonicalChatRequest(
        model="antigravity-oauth",
        messages=[ChatMessage(role="user", content="hi")],
        tools=[
            {
                "name": "execute_command",
                "description": "Execute a shell command",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "workdir": {"type": "string"},
                    },
                    "required": ["command"],
                },
            },
        ],
    )

    code_assist_request: dict = {}

    GeminiOAuthBaseConnector._sanitize_code_assist_tools(canonical, code_assist_request)

    tools = code_assist_request.get("tools")
    assert isinstance(tools, list) and len(tools) == 1
    declarations = tools[0].get("function_declarations")
    assert isinstance(declarations, list) and len(declarations) == 1

    func = declarations[0]
    assert func["name"] == "execute_command"
    assert func["description"] == "Execute a shell command"
    assert func["parameters"]["type"] == "object"
    assert "command" in func["parameters"]["properties"]


def test_sanitize_code_assist_tools_drops_invalid_function_names() -> None:
    canonical = CanonicalChatRequest(
        model="antigravity-oauth",
        messages=[ChatMessage(role="user", content="hi")],
        tools=[
            {
                "function": {
                    "name": "1invalid-name",
                    "description": "Invalid function name",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                }
            }
        ],
    )

    code_assist_request: dict = {}

    GeminiOAuthBaseConnector._sanitize_code_assist_tools(canonical, code_assist_request)

    assert "tools" not in code_assist_request


def test_sanitize_code_assist_tools_handles_mixed_formats() -> None:
    """A mix of OpenAI, Anthropic, and direct formats should all be converted."""
    canonical = CanonicalChatRequest(
        model="antigravity-oauth",
        messages=[ChatMessage(role="user", content="hi")],
        tools=[
            # OpenAI standard format
            {
                "type": "function",
                "function": {
                    "name": "openai_tool",
                    "description": "OpenAI format tool",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            # Direct format with parameters
            {
                "name": "direct_tool",
                "description": "Direct format tool",
                "parameters": {"type": "object", "properties": {}},
            },
            # Anthropic format with input_schema
            {
                "name": "anthropic_tool",
                "description": "Anthropic format tool",
                "input_schema": {"type": "object", "properties": {}},
            },
            # Custom format without name - should be skipped
            {"type": "custom", "custom": {"input_schema": {"type": "object"}}},
        ],
    )

    code_assist_request: dict = {}

    GeminiOAuthBaseConnector._sanitize_code_assist_tools(canonical, code_assist_request)

    tools = code_assist_request.get("tools")
    assert isinstance(tools, list) and len(tools) == 1
    declarations = tools[0].get("function_declarations")
    # Should have 3 tools (custom without name is skipped)
    assert isinstance(declarations, list) and len(declarations) == 3

    names = {d["name"] for d in declarations}
    assert names == {"openai_tool", "direct_tool", "anthropic_tool"}


def test_sanitize_gemini_parameters_strips_problematic_fields() -> None:
    """JSON Schema fields that cause draft 2020-12 validation errors should be stripped."""
    from src.core.domain.translation import Translation

    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": "some-id",
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "format": "email",
                "minLength": 1,
                "maxLength": 100,
                "pattern": "^[a-z]+$",
                "default": "test",
                "examples": ["foo", "bar"],
            },
            "count": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "exclusiveMinimum": 0,
                "exclusiveMaximum": 100,
            },
        },
        "required": ["name"],
        "additionalProperties": False,
        "strict": True,
        "title": "TestSchema",
        "$defs": {"helper": {"type": "string"}},
    }

    sanitized = Translation._sanitize_gemini_parameters(schema)

    # Core structure should be preserved
    assert sanitized["type"] == "object"
    assert "properties" in sanitized
    assert sanitized["required"] == ["name"]

    # Problematic fields should be stripped
    assert "$schema" not in sanitized
    assert "$id" not in sanitized
    assert "additionalProperties" not in sanitized
    assert "strict" not in sanitized
    assert "title" not in sanitized
    assert "$defs" not in sanitized

    # Nested problematic fields should also be stripped
    assert "format" not in sanitized["properties"]["name"]
    assert "minLength" not in sanitized["properties"]["name"]
    assert "maxLength" not in sanitized["properties"]["name"]
    assert "pattern" not in sanitized["properties"]["name"]
    assert "default" not in sanitized["properties"]["name"]
    assert "examples" not in sanitized["properties"]["name"]
    assert "minimum" not in sanitized["properties"]["count"]
    assert "maximum" not in sanitized["properties"]["count"]
    assert "exclusiveMinimum" not in sanitized["properties"]["count"]
    assert "exclusiveMaximum" not in sanitized["properties"]["count"]

    # Type should be preserved in nested properties
    assert sanitized["properties"]["name"]["type"] == "string"
    assert sanitized["properties"]["count"]["type"] == "integer"


def test_sanitize_gemini_parameters_validates_required_references() -> None:
    """Required array entries that reference non-existent properties should be removed.

    The Gemini API rejects schemas where required[i] references a property that
    doesn't exist in the properties object.
    """
    from src.core.domain.translation import Translation

    schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        # "nonexistent" property doesn't exist in properties
        "required": ["path", "nonexistent", "content"],
    }

    sanitized = Translation._sanitize_gemini_parameters(schema)

    # Only valid required entries should remain
    assert sanitized["required"] == ["path", "content"]
    assert "nonexistent" not in sanitized["required"]


def test_sanitize_gemini_parameters_removes_required_if_all_invalid() -> None:
    """If all required entries are invalid, remove the required field entirely."""
    from src.core.domain.translation import Translation

    schema = {
        "type": "object",
        "properties": {
            "actual_prop": {"type": "string"},
        },
        "required": ["nonexistent1", "nonexistent2"],
    }

    sanitized = Translation._sanitize_gemini_parameters(schema)

    # Required should be removed since no entries are valid
    assert "required" not in sanitized


def test_sanitize_gemini_parameters_validates_nested_required() -> None:
    """Required validation should work recursively in nested objects."""
    from src.core.domain.translation import Translation

    schema = {
        "type": "object",
        "properties": {
            "config": {
                "type": "object",
                "properties": {
                    "enabled": {"type": "boolean"},
                },
                "required": ["enabled", "missing_prop"],
            },
        },
        "required": ["config"],
    }

    sanitized = Translation._sanitize_gemini_parameters(schema)

    # Top-level required should be valid
    assert sanitized["required"] == ["config"]

    # Nested required should only contain valid entries
    nested_required = sanitized["properties"]["config"]["required"]
    assert nested_required == ["enabled"]
    assert "missing_prop" not in nested_required
