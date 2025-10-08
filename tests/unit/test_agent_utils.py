import json

from src.agents import (
    convert_cline_marker_to_gemini_function_call,
    detect_agent,
    wrap_proxy_message,
)


def test_detect_agent_cline() -> None:
    prompt = "You are Cline, use tools with XML-style tags"
    assert detect_agent(prompt) == "cline"


def test_detect_agent_roocode() -> None:
    prompt = "You are Roo, follow RooCode rules"
    assert detect_agent(prompt) == "roocode"


def test_detect_agent_aider() -> None:
    prompt = "Please use the V4A diff format.*** Begin Patch"
    assert detect_agent(prompt) == "aider"


def test_wrap_proxy_message_cline() -> None:
    out = wrap_proxy_message("cline", "hi")
    assert out == "hi"  # wrap_proxy_message is now pass-through for cline


def test_wrap_proxy_message_aider() -> None:
    out = wrap_proxy_message("aider", "line1\nline2")
    assert out.splitlines()[0] == "*** Begin Patch"
    assert out.splitlines()[-1] == "*** End Patch"


def test_convert_cline_marker_to_gemini_function_call() -> None:
    marker = (
        "__CLINE_TOOL_CALL_MARKER__do the thing__END_CLINE_TOOL_CALL_MARKER__"
    )
    result = convert_cline_marker_to_gemini_function_call(marker)

    parsed = json.loads(result)
    assert "functionCall" in parsed
    assert parsed["functionCall"]["name"] == "attempt_completion"
    assert parsed["functionCall"]["args"] == {"result": "do the thing"}
