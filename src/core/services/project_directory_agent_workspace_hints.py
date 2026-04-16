"""Agent-specific startup line patterns for project directory auto-detection.

Each coding agent tends to inject workspace / CWD context in slightly different
wording. Generic hints live on :class:`ProjectDirectoryResolutionService`; this
module holds **narrow** patterns keyed off the HTTP ``agent`` string so we do
not widen matching for unrelated clients.
"""

from __future__ import annotations

import re


def is_opencode_agent(agent: str | None) -> bool:
    """True when the client identifies as OpenCode (or a compatible fork)."""

    if not agent:
        return False
    return "opencode" in agent.strip().lower()


def opencode_extra_startup_hint_patterns() -> tuple[re.Pattern[str], ...]:
    """Line prefixes after which an absolute path may appear (OpenCode, Claude Code, Cline).

    OpenCode's environment block commonly uses a ``Working directory:`` line
    (``SystemPrompt.environment()`` style) with an absolute path. The generic
    trusted hints use ``current working directory`` but not this shorter label.

    Anthropic's Claude Code CLI uses the same ``Working directory:`` wording in
    injected environment text (system prompt by default, or the first user
    message when ``--exclude-dynamic-system-prompt-sections`` is set).

    Cline and Roo Code may use the same label inside their VS Code environment
    preamble.
    """

    return (re.compile(r"(?i)\bworking\s+directory\b" r"\s*(?:[:=]|is|at|->)\s*"),)


def vscode_fork_workspace_line_patterns() -> tuple[re.Pattern[str], ...]:
    """Labels like ``Workspace folder:`` used by Cline / Roo / Kilo (not only ``workspace path``)."""

    return (
        re.compile(
            r"(?i)\bworkspace(?:\s+(?:path|folder|directory|dir|root))?\b"
            r"\s*(?:[:=]|is|at|->)\s*"
        ),
    )


_CLINE_USER_AGENT = re.compile(r"(?i)\bcline/")
_ROO_CODE_USER_AGENT = re.compile(r"(?i)\bRoo(?:Code)?/")
_KILO_CODE_USER_AGENT = re.compile(r"(?i)\bKilo-Code/")
_FACTORY_CLI_PWD_LINE = re.compile(r"^\s*(?:%|\$)\s*pwd\s*$", re.IGNORECASE)


def is_claude_code_agent(agent: str | None) -> bool:
    """True when the client identifies as Anthropic's Claude Code CLI."""

    if not agent:
        return False
    lowered = agent.strip().lower()
    return "claude-cli" in lowered


def is_cline_agent(agent: str | None) -> bool:
    """True when the HTTP client identifies as the Cline VS Code extension."""

    if not agent:
        return False
    return bool(_CLINE_USER_AGENT.search(agent.strip()))


def is_roo_code_agent(agent: str | None) -> bool:
    """True when the HTTP client identifies as Roo Code (VS Code extension)."""

    if not agent:
        return False
    return bool(_ROO_CODE_USER_AGENT.search(agent.strip()))


def is_kilo_code_agent(agent: str | None) -> bool:
    """True when the HTTP client identifies as Kilo Code (Cline-family VS Code extension)."""

    if not agent:
        return False
    return bool(_KILO_CODE_USER_AGENT.search(agent.strip()))


def is_vscode_coding_fork_agent(agent: str | None) -> bool:
    """Cline-style VS Code coding extensions that share environment-in-user patterns."""

    return (
        is_cline_agent(agent) or is_roo_code_agent(agent) or is_kilo_code_agent(agent)
    )


def is_factory_droid_agent(agent: str | None) -> bool:
    """True when the HTTP client identifies as Factory's ``droid`` CLI."""

    if not agent:
        return False
    lowered = agent.strip().lower()
    return lowered.startswith("factory-cli") or "factory-cli/" in lowered


def iter_factory_droid_pwd_directory_hint_lines(text: str) -> tuple[str, ...]:
    """Lines immediately after a ``% pwd`` / ``$ pwd`` transcript line.

    Factory Droid injects the real cwd in the **user** message as a shell-style
    transcript: a line that is only ``% pwd`` (or ``$ pwd``), then the next
    non-empty line is the absolute working directory. Other absolute paths in
    the same message (for example linked sibling repositories in docs) are not
    reliable project roots, so we surface these lines first for resolution.
    """

    lines = text.splitlines()
    out: list[str] = []
    for i, line in enumerate(lines):
        if not _FACTORY_CLI_PWD_LINE.match(line.strip()):
            continue
        for j in range(i + 1, len(lines)):
            nxt = lines[j].strip()
            if not nxt:
                continue
            out.append(nxt)
            break
    return tuple(out)


__all__ = [
    "is_claude_code_agent",
    "is_cline_agent",
    "is_factory_droid_agent",
    "is_kilo_code_agent",
    "is_opencode_agent",
    "is_roo_code_agent",
    "is_vscode_coding_fork_agent",
    "iter_factory_droid_pwd_directory_hint_lines",
    "opencode_extra_startup_hint_patterns",
    "vscode_fork_workspace_line_patterns",
]
