from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest
from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall
from src.core.domain.dynamic_compression import ToolOutputContentType
from src.core.services import tool_identity_resolver as resolver_module
from src.core.services.tool_identity_resolver import ToolIdentityResolver


def _build_messages(command: str, output: str) -> list[ChatMessage]:
    return [
        ChatMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="tc-1",
                    function=FunctionCall(
                        name="shell",
                        arguments=f'{{"command":"{command}"}}',
                    ),
                )
            ],
        ),
        ChatMessage(role="tool", tool_call_id="tc-1", content=output),
    ]


class _CountingResolver(ToolIdentityResolver):
    def __init__(self) -> None:
        super().__init__()
        self.lookup_build_calls = 0

    def build_tool_call_lookup(
        self,
        messages: Sequence[ChatMessage],
    ) -> dict[str, tuple[str, str | dict[str, Any] | None]]:
        self.lookup_build_calls += 1
        return super().build_tool_call_lookup(messages)


def test_safe_split_is_deterministic_for_quoted_commands() -> None:
    resolver = ToolIdentityResolver()

    tokens = resolver._safe_split('cmd /c "echo hello world"')

    assert tokens == ["cmd", "/c", "echo hello world"]


@pytest.mark.parametrize(
    "payload, expected",
    [
        (
            "<root><item key='1'>value</item><item key='2'>other</item></root>",
            ToolOutputContentType.XML,
        ),
        ("<root><item>value</root>", ToolOutputContentType.TEXT),
        ("2 < 3 > 1", ToolOutputContentType.TEXT),
        ("< not-xml >", ToolOutputContentType.TEXT),
    ],
)
def test_detect_content_type_handles_xml_edge_cases(
    payload: str,
    expected: ToolOutputContentType,
) -> None:
    resolver = ToolIdentityResolver()

    assert resolver._detect_content_type(payload) == expected


@pytest.mark.parametrize(
    "command",
    [
        'cmd /c "echo hello world"',
        '"C:/Program Files/Git/bin/git" status --short',
        'env FOO=bar git -C "repo with spaces" rev-parse HEAD',
        "python -c \"print('x')\"",
        'git commit -m "unterminated quote',
    ],
)
def test_safe_split_is_deterministic_across_command_shapes(command: str) -> None:
    resolver = ToolIdentityResolver()

    first = resolver._safe_split(command)
    second = resolver._safe_split(command)
    third = resolver._safe_split(command)

    assert first == second == third
    assert bool(first) is bool(command.strip())


@pytest.mark.parametrize(
    "command, expected_signature, expected_prefix",
    [
        ('cmd /c "echo hello world"', "cmd", "cmd /c"),
        (
            '"/usr/local/bin/git" -C "/tmp/repo with spaces" status --short',
            "git",
            "git status",
        ),
        ("env FOO=bar git -C repo rev-parse HEAD", "git", "git rev-parse"),
        ('git commit -m "unterminated quote', "git", "git commit"),
    ],
)
def test_extract_command_identity_is_deterministic_across_command_shapes(
    command: str,
    expected_signature: str,
    expected_prefix: str,
) -> None:
    resolver = ToolIdentityResolver()

    first_signature, first_prefix = resolver._extract_command_identity(command)
    second_signature, second_prefix = resolver._extract_command_identity(command)

    assert (first_signature, first_prefix) == (second_signature, second_prefix)
    assert (first_signature, first_prefix) == (expected_signature, expected_prefix)


@pytest.mark.parametrize(
    "command, expected_prefix",
    [
        ("git status --short", "git status"),
        ("npm test -- --watch", "npm test"),
        ("go test ./...", "go test"),
        ("uv pip install requests", "uv pip install"),
    ],
)
def test_extract_command_identity_preserves_common_safe_subcommand_prefixes(
    command: str,
    expected_prefix: str,
) -> None:
    resolver = ToolIdentityResolver()

    signature, prefix = resolver._extract_command_identity(command)

    assert signature is not None
    assert prefix == expected_prefix


@pytest.mark.parametrize(
    "command, expected_prefix",
    [
        (
            "curl https://internal.example.local/path?api_key=topsecret",
            "curl",
        ),
        ("cat C:/Users/Mateusz/private-secrets.txt", "cat"),
        ("python ./scripts/run_sensitive_task.py --token abc123", "python"),
    ],
)
def test_extract_command_identity_sanitizes_unsafe_argument_like_prefix_tokens(
    command: str,
    expected_prefix: str,
) -> None:
    resolver = ToolIdentityResolver()

    signature, prefix = resolver._extract_command_identity(command)

    assert signature is not None
    assert prefix == expected_prefix


def test_detect_content_type_bounds_ndjson_scan_by_line_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = ToolIdentityResolver()
    original_json_loads = json.loads
    calls = 0

    def _counting_loads(payload: str) -> object:
        nonlocal calls
        calls += 1
        return original_json_loads(payload)

    monkeypatch.setattr(
        "src.core.services.tool_identity_resolver.json.loads",
        _counting_loads,
    )

    payload = "\n".join("1" for _ in range(resolver_module._NDJSON_MAX_SCAN_LINES + 20))
    detected = resolver._detect_content_type(payload)

    assert detected == ToolOutputContentType.TEXT
    assert calls <= resolver_module._NDJSON_MAX_SCAN_LINES


def test_detect_content_type_applies_ndjson_size_cap() -> None:
    resolver = ToolIdentityResolver()
    line = '{"key":"' + ("x" * 8192) + '"}'
    payload = "\n".join(line for _ in range(40))
    assert len(payload) > resolver_module._NDJSON_MAX_SCAN_BYTES

    detected = resolver._detect_content_type(payload)

    assert detected == ToolOutputContentType.TEXT


def test_resolve_tool_output_reuses_supplied_tool_lookup() -> None:
    resolver = _CountingResolver()
    messages = _build_messages("git status", "ok")
    lookup = resolver.build_tool_call_lookup(messages)
    assert resolver.lookup_build_calls == 1

    context = resolver.resolve_tool_output(
        messages=messages,
        tool_message=messages[1],
        tool_lookup=lookup,
    )

    assert context is not None
    assert resolver.lookup_build_calls == 1


@pytest.mark.parametrize(
    "tool_name, arguments",
    [
        ("shell", '{"command":"pytest -q tests/unit"}'),
        ("bash", {"command": "python -m pytest tests/unit -q"}),
        ("exec_command", {"cmd": "py.test -q"}),
        ("container.exec", {"args": ["python", "-m", "pytest", "-q"]}),
        ("shell", {"command": "uv run pytest -q tests/unit"}),
        ("shell", {"command": "uv run -m pytest -q tests/unit"}),
        ("shell", {"command": "poetry run pytest -q tests/unit"}),
        ("shell", {"command": "pipenv run pytest -q tests/unit"}),
    ],
)
def test_scan_for_pytest_matches_legacy_detection_contract(
    tool_name: str,
    arguments: str | dict[str, object],
) -> None:
    resolver = ToolIdentityResolver()

    detected = resolver.scan_for_pytest(tool_name=tool_name, arguments=arguments)

    assert detected is not None
    assert "pytest" in detected.lower() or "py.test" in detected.lower()


@pytest.mark.parametrize(
    "tool_name, arguments",
    [
        ("read_file", '{"command":"pytest -q tests/unit"}'),
        ("shell", '{"command":"python -m unittest -q"}'),
        ("shell", {"command": "echo pytest"}),
        ("shell", {"command": "uv pip install pytest"}),
        ("shell", {"command": "uv run --with pytest python app.py"}),
        ("shell", {"command": "poetry run echo pytest"}),
        ("shell", {"command": "pipenv run python -m unittest -q"}),
    ],
)
def test_scan_for_pytest_ignores_non_matching_inputs(
    tool_name: str,
    arguments: str | dict[str, object],
) -> None:
    resolver = ToolIdentityResolver()

    detected = resolver.scan_for_pytest(tool_name=tool_name, arguments=arguments)

    assert detected is None


def test_resolve_tool_output_normalizes_python_m_pytest_as_pytest_signature() -> None:
    resolver = ToolIdentityResolver()
    messages = _build_messages("python -m pytest tests/unit -q", "FAILED one\nsummary")

    context = resolver.resolve_tool_output(messages=messages, tool_message=messages[1])

    assert context is not None
    assert context.identity.command_signature == "pytest"
    assert context.identity.command_prefix is not None
    assert context.identity.command_prefix.startswith("pytest")
