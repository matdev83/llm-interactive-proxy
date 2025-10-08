import re

# Public helpers re-exported for external tests
__all__ = [
    "detect_agent",
    "detect_frontend_api",
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


