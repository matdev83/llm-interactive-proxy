import re
from typing import Optional, List


def detect_agent(prompt: str) -> Optional[str]:
    p = prompt.lower()
    if "cline" in p or "xml-style" in p or "tool use" in p:
        return "cline"
    if "roocode" in p or re.search(r"you are\s+roo", p):
        return "roocode"
    if "v4a diff" in p or "*** begin patch" in p or "aider" in p:
        return "aider"
    return None


def wrap_proxy_message(agent: Optional[str], text: str) -> str:
    if not text: # Keep this check
        return text

    # The Cline/RooCode block is removed.
    # if agent in {"cline", "roocode"}:
    #     return f"[Proxy Result]\n\n{text}"

    if agent == "aider":
        lines = text.splitlines()
        patch = ["*** Begin Patch", "*** Add File: PROXY_OUTPUT.txt"]
        patch += ["+" + line for line in lines]
        patch.append("*** End Patch")
        return "\n".join(patch)
    return text


def format_command_response_for_agent(content_lines: List[str], agent: Optional[str]) -> str:
    joined_content = "\n".join(content_lines)

    if agent in {"cline", "roocode"}:
        # Ensure the XML structure and newlines match the target format precisely
        return (
            f"<attempt_completion>\n<result>\n"
            f"<thinking>{joined_content}\n</thinking>\n"
            f"</result>\n</attempt_completion>\n"
        )
    else:
        return joined_content
