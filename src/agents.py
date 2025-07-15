import re
from typing import List, Optional


def detect_agent(prompt: str) -> Optional[str]:
    prompt_lower = prompt.lower()
    if ("cline" in prompt_lower or
            "xml-style" in prompt_lower or
            "tool use" in prompt_lower):
        return "cline"
    if "roocode" in prompt_lower or re.search(r"you are\s+roo", prompt_lower):
        return "roocode"
    if ("v4a diff" in prompt_lower or
            "*** begin patch" in prompt_lower or
            "aider" in prompt_lower):
        return "aider"
    return None


def wrap_proxy_message(agent: Optional[str], text: str) -> str:
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
        content_lines: List[str],
        agent: Optional[str]) -> str:
    joined_content = "\n".join(content_lines)

    if agent in {"cline", "roocode"}:
        # Format according to CLINE_FORKS.md specification - no <command> element
        return (
            f"<attempt_completion>\n<result>\n"
            f"{joined_content}\n"
            f"</result>\n</attempt_completion>\n"
        )
    return joined_content
