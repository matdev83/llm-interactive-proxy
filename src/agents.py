import re

# Public helpers re-exported for external tests
__all__ = [
    "convert_cline_marker_to_anthropic_tool_use",
    "convert_cline_marker_to_gemini_function_call",
    "convert_cline_marker_to_openai_tool_call",
    "create_openai_attempt_completion_tool_call",
    "detect_agent",
    "detect_frontend_api",
    "format_command_response_for_agent",
    "wrap_proxy_message",
]


def detect_frontend_api(request_path: str) -> str:
    """
    Detect the frontend API type based on the request path.

    Args:
        request_path: The request path (e.g., "/v2/chat/completions", "/anthropic/v1/messages")

    Returns:
        Frontend API type: "openai", "anthropic", or "gemini"
    """
    if request_path.startswith("/anthropic/"):
        return "anthropic"
    elif request_path.startswith("/v1beta/"):
        return "gemini"
    elif request_path.startswith("/v2/"):
        # Legacy /v2/ endpoint
        return "openai"
    else:
        # Default to OpenAI /v1/ for all other paths
        return "openai"


def detect_agent(prompt: str) -> str | None:
    prompt_lower = prompt.lower()
    if (
        "cline" in prompt_lower
        or "xml-style" in prompt_lower
        or "tool use" in prompt_lower
    ):
        return "cline"
    if "roocode" in prompt_lower or re.search(r"you are\s+roo", prompt_lower):
        return "roocode"
    if (
        "v4a diff" in prompt_lower
        or "*** begin patch" in prompt_lower
        or "aider" in prompt_lower
    ):
        return "aider"
    return None


def wrap_proxy_message(agent: str | None, text: str) -> str:
    if not text:  # Keep this check
        return text

    if agent == "aider":
        lines = text.splitlines()
        patch = ["*** Begin Patch", "*** Add File: PROXY_OUTPUT.txt"]
        patch.extend([f"+{line}" for line in lines])
        patch.append("*** End Patch")
        return "\n".join(patch)
    return text


def format_command_response_for_agent(
    content_lines: list[str], agent: str | None
) -> str:
    """
    Central handler for formatting locally generated command responses.

    For Cline agents: Returns a special marker that frontends will detect and
    convert to appropriate tool call format.

    For other agents: Returns plain text content.
    """
    joined_content = "\n".join(content_lines)

    if agent in {"cline", "roocode"}:
        # Return special marker for frontend conversion to tool calls
        # This keeps the central handler frontend-agnostic
        return (
            f"__CLINE_TOOL_CALL_MARKER__{joined_content}__END_CLINE_TOOL_CALL_MARKER__"
        )

    return joined_content


def convert_cline_marker_to_openai_tool_call(content: str) -> dict:
    """
    Convert Cline marker to OpenAI tool call format.
    Frontend-specific implementation for OpenAI API.
    """
    import json
    import secrets

    # Extract content from marker
    if content.startswith("__CLINE_TOOL_CALL_MARKER__") and content.endswith(
        "__END_CLINE_TOOL_CALL_MARKER__"
    ):
        actual_content = content[
            len("__CLINE_TOOL_CALL_MARKER__") : -len("__END_CLINE_TOOL_CALL_MARKER__")
        ]
    else:
        actual_content = content

    return {
        "id": f"call_{secrets.token_hex(12)}",
        "type": "function",
        "function": {
            "name": "attempt_completion",
            "arguments": json.dumps({"result": actual_content}),
        },
    }


def convert_cline_marker_to_anthropic_tool_use(content: str) -> str:
    """
    Convert Cline marker to Anthropic tool_use format.
    Frontend-specific implementation for Anthropic API.
    """
    import json
    import secrets

    # Extract content from marker
    if content.startswith("__CLINE_TOOL_CALL_MARKER__") and content.endswith(
        "__END_CLINE_TOOL_CALL_MARKER__"
    ):
        actual_content = content[
            len("__CLINE_TOOL_CALL_MARKER__") : -len("__END_CLINE_TOOL_CALL_MARKER__")
        ]
    else:
        actual_content = content

    tool_use_block = {
        "type": "tool_use",
        "id": f"toolu_{secrets.token_hex(12)}",
        "name": "attempt_completion",
        "input": {"result": actual_content},
    }

    return json.dumps([tool_use_block])


def convert_cline_marker_to_gemini_function_call(content: str) -> str:
    """
    Convert Cline marker to Gemini function call format.
    Frontend-specific implementation for Gemini API.
    """
    import json

    # Extract content from marker
    if content.startswith("__CLINE_TOOL_CALL_MARKER__") and content.endswith(
        "__END_CLINE_TOOL_CALL_MARKER__"
    ):
        actual_content = content[
            len("__CLINE_TOOL_CALL_MARKER__") : -len("__END_CLINE_TOOL_CALL_MARKER__")
        ]
    else:
        actual_content = content

    function_response = {
        "function_call": {
            "name": "attempt_completion",
            "args": {"result": actual_content},
        }
    }

    return json.dumps(function_response)


# ---------------------------------------------------------------------------
# Convenience helpers (used by integration tests)
# ---------------------------------------------------------------------------


def create_openai_attempt_completion_tool_call(content_lines: list[str]) -> dict:
    """Return a fully-formed OpenAI tool-call dict for *attempt_completion*.

    The integration tests expect a helper that takes a list of **content**
    strings (typically split lines from a command response) and converts them
    into the exact structure produced by
    `convert_cline_marker_to_openai_tool_call`.

    Parameters
    ----------
    content_lines : List[str]
        Lines of text that constitute the *result* argument for the
        *attempt_completion* function.
    """
    joined = "\n".join(content_lines)
    # Re-use the existing conversion utility to stay DRY by wrapping the
    # joined content in the special Cline marker pair that the converter
    # recognises.
    marker_wrapped = f"__CLINE_TOOL_CALL_MARKER__{joined}__END_CLINE_TOOL_CALL_MARKER__"
    return convert_cline_marker_to_openai_tool_call(marker_wrapped)
