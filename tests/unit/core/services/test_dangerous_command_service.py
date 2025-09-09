import pytest
from src.core.domain.chat import FunctionCall, ToolCall
from src.core.domain.configuration.dangerous_command_config import (
    DEFAULT_DANGEROUS_COMMAND_CONFIG,
)
from src.core.services.dangerous_command_service import DangerousCommandService


@pytest.fixture
def dangerous_command_service() -> DangerousCommandService:
    """Provides a DangerousCommandService instance with default rules."""
    return DangerousCommandService(config=DEFAULT_DANGEROUS_COMMAND_CONFIG)


@pytest.mark.parametrize(
    "command, expected_rule_name",
    [
        ("git reset --hard", "git-reset-hard"),
        ("git clean -f", "git-clean-force"),
        ("git rebase -i", "git-rebase"),
        ("git commit --amend", "git-commit-amend"),
        ("git push --force", "git-push-force"),
        ("git branch -D my-branch", "git-branch-force-delete"),
        ("git branch -d old", "git-branch-delete"),
        ("git tag -d v1.0.0", "git-tag-delete"),
        ("git update-ref -d refs/heads/feature", "git-update-ref-delete"),
        ("git reflog expire --expire=now --all", "git-reflog-expire-now"),
        ("git push --force-with-lease", "git-push-force-with-lease"),
        ("git push --delete origin branch", "git-push-delete-branch"),
        ("git push origin :branch", "git-push-delete-ref-legacy"),
        ("git push --mirror", "git-push-mirror"),
        ("git gc --prune=now", "git-gc-prune-now"),
        ("git prune", "git-prune"),
        ("git repack -d", "git-repack-delete"),
        ("git lfs prune", "git-lfs-prune"),
        ("git worktree remove --force ../wt1", "git-worktree-remove-force"),
        ("git worktree prune", "git-worktree-prune"),
        ("git submodule deinit -f", "git-submodule-deinit-force"),
        ("git submodule foreach 'git clean -fdx'", "git-submodule-foreach-clean-force"),
        ("git switch -f main", "git-switch-checkout-force"),
        ("git checkout -f main", "git-switch-checkout-force"),
        ("git checkout --orphan new-branch", "git-checkout-orphan"),
        ("git filter-repo --path README.md --invert-paths", "git-filter-repo"),
        ("git replace abcdef ghijkl", "git-replace"),
        ("git rm -r --force src/", "git-rm-force"),
    ],
)
def test_scan_tool_call_detects_dangerous_commands(
    dangerous_command_service: DangerousCommandService,
    command: str,
    expected_rule_name: str,
):
    """
    Tests that the service correctly identifies various dangerous git commands.
    """
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="execute_command", arguments=command),
        type="function",
    )

    result = dangerous_command_service.scan_tool_call(tool_call)

    assert result is not None
    matched_rule, matched_command = result
    assert matched_rule.name == expected_rule_name
    assert matched_command == command


def test_scan_tool_call_ignores_safe_commands(
    dangerous_command_service: DangerousCommandService,
):
    """
    Tests that the service does not flag safe commands.
    """
    safe_command = "git status"
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="execute_command", arguments=safe_command),
        type="function",
    )

    result = dangerous_command_service.scan_tool_call(tool_call)

    assert result is None


def test_scan_tool_call_ignores_commands_with_safe_tool_names(
    dangerous_command_service: DangerousCommandService,
):
    """
    Tests that the service ignores commands executed through a tool not on the
    dangerous list.
    """
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="safe_tool", arguments="git reset --hard"),
        type="function",
    )

    result = dangerous_command_service.scan_tool_call(tool_call)

    assert result is None


def test_scan_tool_call_extracts_command_from_json_arguments(
    dangerous_command_service: DangerousCommandService,
):
    """
    Tests that the service extracts 'command' field from JSON arguments.
    """
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(
            name="execute_command", arguments='{"command": "git reset --hard"}'
        ),
        type="function",
    )

    result = dangerous_command_service.scan_tool_call(tool_call)

    assert result is not None
    matched_rule, matched_command = result
    assert matched_rule.name == "git-reset-hard"
    assert matched_command == "git reset --hard"


def test_clean_with_dry_run_is_ignored(
    dangerous_command_service: DangerousCommandService,
) -> None:
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="execute_command", arguments="git clean -n -fdx"),
        type="function",
    )
    result = dangerous_command_service.scan_tool_call(tool_call)
    assert result is None


def test_git_rm_cached_force_is_ignored(
    dangerous_command_service: DangerousCommandService,
) -> None:
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(
            name="execute_command", arguments="git rm --cached --force file.txt"
        ),
        type="function",
    )
    result = dangerous_command_service.scan_tool_call(tool_call)
    assert result is None


def test_extracts_command_from_cmd_field(
    dangerous_command_service: DangerousCommandService,
) -> None:
    tool_call = ToolCall(
        id="call_1",
        function=FunctionCall(name="shell", arguments='{"cmd": "git push --mirror"}'),
        type="function",
    )
    result = dangerous_command_service.scan_tool_call(tool_call)
    assert result is not None
    assert result[0].name == "git-push-mirror"


def test_extracts_command_from_nested_input(
    dangerous_command_service: DangerousCommandService,
) -> None:
    tool_call = ToolCall(
        id="call_2",
        function=FunctionCall(
            name="bash",
            arguments='{"input": {"command": "git push --delete origin dead"}}',
        ),
        type="function",
    )
    result = dangerous_command_service.scan_tool_call(tool_call)
    assert result is not None
    assert result[0].name == "git-push-delete-branch"


def test_extracts_command_from_args_array(
    dangerous_command_service: DangerousCommandService,
) -> None:
    args_json = '{"args": ["git", "rebase", "--interactive"]}'
    tool_call = ToolCall(
        id="call_3",
        function=FunctionCall(name="local_shell", arguments=args_json),
        type="function",
    )
    result = dangerous_command_service.scan_tool_call(tool_call)
    assert result is not None
    assert result[0].name == "git-rebase"


def test_detects_git_in_mixed_command_string(
    dangerous_command_service: DangerousCommandService,
) -> None:
    mixed = "echo start && git push --mirror && echo done"
    tool_call = ToolCall(
        id="call_4",
        function=FunctionCall(name="execute_command", arguments=mixed),
        type="function",
    )
    result = dangerous_command_service.scan_tool_call(tool_call)
    assert result is not None
    assert result[0].name == "git-push-mirror"


@pytest.mark.parametrize(
    "command, expected_rule",
    [
        ("  git   push   --mirror  ", "git-push-mirror"),
        ("git\tpush --mirror", "git-push-mirror"),
        ("git\n push --mirror", "git-push-mirror"),
        ("'git reset --hard'", "git-reset-hard"),
    ],
)
def test_whitespace_and_quotes_variants(
    dangerous_command_service: DangerousCommandService, command: str, expected_rule: str
) -> None:
    tool_call = ToolCall(
        id="call_5",
        function=FunctionCall(name="shell", arguments=command),
        type="function",
    )
    result = dangerous_command_service.scan_tool_call(tool_call)
    assert result is not None
    assert result[0].name == expected_rule
