import re
from typing import Optional


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
    if not text:
        return text
    if agent in {"cline", "roocode"}:
        return f"[Proxy Result]\n\n{text}"
    if agent == "aider":
        lines = text.splitlines()
        patch = ["*** Begin Patch", "*** Add File: PROXY_OUTPUT.txt"]
        patch += ["+" + line for line in lines]
        patch.append("*** End Patch")
        return "\n".join(patch)
    return text
