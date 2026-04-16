"""Tests for agent-specific project directory hint patterns."""

from __future__ import annotations

import re

from src.core.services.project_directory_agent_workspace_hints import (
    is_claude_code_agent,
    is_cline_agent,
    is_factory_droid_agent,
    is_kilo_code_agent,
    is_opencode_agent,
    is_roo_code_agent,
    is_vscode_coding_fork_agent,
    iter_factory_droid_pwd_directory_hint_lines,
    opencode_extra_startup_hint_patterns,
    vscode_fork_workspace_line_patterns,
)


def test_is_opencode_agent_matches_user_agent_strings() -> None:
    assert is_opencode_agent("opencode/1.2.26 foo") is True
    assert is_opencode_agent("OpenCode/2") is True
    assert is_opencode_agent("claude-code/1.0") is False
    assert is_opencode_agent(None) is False


def test_is_claude_code_agent_matches_user_agent_strings() -> None:
    assert is_claude_code_agent("claude-cli/2.1.92 (external, cli)") is True
    assert is_claude_code_agent("foo claude-cli/2 bar") is True
    assert is_claude_code_agent("opencode/1.0") is False
    assert is_claude_code_agent("claude-code/1.0") is False
    assert is_claude_code_agent(None) is False


def test_is_cline_agent_matches_user_agent_strings() -> None:
    assert is_cline_agent("Cline/3.78.0") is True
    assert is_cline_agent("foo Cline/3 bar") is True
    assert is_cline_agent("opencode/1.0") is False
    assert is_cline_agent("decline/1.0") is False
    assert is_cline_agent(None) is False


def test_is_roo_code_agent_matches_user_agent_strings() -> None:
    assert is_roo_code_agent("RooCode/3.52.1") is True
    assert is_roo_code_agent("Roo/2.0.0") is True
    assert is_roo_code_agent("foo RooCode/3 bar") is True
    assert is_roo_code_agent("opencode/1.0") is False
    assert is_roo_code_agent(None) is False


def test_is_kilo_code_agent_matches_user_agent_strings() -> None:
    ua = "Kilo-Code/7.2.10 ai-sdk/provider-utils/4.0.21 runtime/bun/1.3.11"
    assert is_kilo_code_agent(ua) is True
    assert is_kilo_code_agent("Kilo-Code/4.111.0") is True
    assert is_kilo_code_agent("opencode/1.0") is False
    assert is_kilo_code_agent(None) is False


def test_is_vscode_coding_fork_agent_unions_forks() -> None:
    assert is_vscode_coding_fork_agent("Cline/3.78.0") is True
    assert is_vscode_coding_fork_agent("RooCode/3.52.1") is True
    assert (
        is_vscode_coding_fork_agent(
            "Kilo-Code/7.2.10 ai-sdk/provider-utils/4.0.21 runtime/bun/1.3.11"
        )
        is True
    )
    assert is_vscode_coding_fork_agent("claude-cli/2.0") is False


def test_vscode_fork_workspace_folder_pattern_matches_line() -> None:
    pat = vscode_fork_workspace_line_patterns()[0]
    assert pat.search(
        r"Workspace folder: C:\Users\Mateusz\source\repos\llm-interactive-proxy"
    )
    assert pat.search("Workspace directory: /home/dev/proj")
    assert pat.search("Workspace root: /opt/kilo-workspace")


def test_opencode_working_directory_pattern_matches_line() -> None:
    pat = opencode_extra_startup_hint_patterns()[0]
    line = r"Working directory: C:\Users\Mateusz\source\repos\turbodom"
    assert pat.search(line)
    line_unix = "Working directory: /home/mateusz/source/repos/turbodom"
    assert pat.search(line_unix)
    assert pat.search("working directory -> /tmp/foo") is not None


def test_opencode_pattern_does_not_match_bare_path() -> None:
    pat = opencode_extra_startup_hint_patterns()[0]
    assert pat.search(r"C:\Users\Mateusz\source\repos\turbodom") is None


def test_patterns_are_compiled_regex() -> None:
    for p in opencode_extra_startup_hint_patterns():
        assert isinstance(p, re.Pattern)


def test_is_factory_droid_agent_recognizes_factory_cli_user_agent() -> None:
    assert is_factory_droid_agent("factory-cli/0.99.0") is True
    assert is_factory_droid_agent("Foo factory-cli/0.1 bar") is True
    assert is_factory_droid_agent("opencode/1.0") is False
    assert is_factory_droid_agent(None) is False


def test_iter_factory_droid_pwd_directory_hint_lines() -> None:
    text = (
        "Some header\n"
        "% pwd\n"
        r"C:\Users\Dev\source\repos\turbodom"
        "\n\nAlso coupled to "
        r"C:\Users\Dev\source\repos\other-repo"
        "\n"
    )
    assert iter_factory_droid_pwd_directory_hint_lines(text) == (
        r"C:\Users\Dev\source\repos\turbodom",
    )


def test_iter_factory_droid_pwd_accepts_dollar_prompt() -> None:
    text = "$ pwd\n/home/dev/source/repos/turbodom\n"
    assert iter_factory_droid_pwd_directory_hint_lines(text) == (
        "/home/dev/source/repos/turbodom",
    )
