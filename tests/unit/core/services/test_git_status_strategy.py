"""Tests for GitStatusStrategy — lean-ctx-inspired git status compression."""

from __future__ import annotations

from src.core.domain.configuration.dynamic_compression_config import CompressionLevel
from src.core.domain.dynamic_compression import ToolOutputContext
from src.core.services.compression_strategies import GitStatusStrategy


def _ctx(
    content: str,
    *,
    command_prefix: str = "git status",
) -> ToolOutputContext:
    return ToolOutputContext.for_text(
        tool_name="shell",
        tool_category="command_execution",
        command_signature="git",
        command_prefix=command_prefix,
        content=content,
    )


_STATUS_LONG_UNSTAGED = (
    "On branch main\n"
    "Your branch is up to date with 'origin/main'.\n"
    "\n"
    "Changes not staged for commit:\n"
    '  (use "git add <file>..." to update what will be committed)\n'
    "\n"
    "\tmodified:   src/main.rs\n"
    "\tmodified:   src/lib.rs\n"
    "\n"
    'no changes added to commit (use "git add" and/or "git commit -a")\n'
)

_STATUS_LONG_STAGED_UNSTAGED_UNTRACKED = (
    "On branch feature/x\n"
    "Your branch is ahead of 'origin/feature/x' by 2 commits.\n"
    '  (use "git push" to publish your local commits)\n'
    "\n"
    "Changes to be committed:\n"
    '  (use "git restore --staged <file>..." to unstage)\n'
    "\tnew file:   src/new_module.py\n"
    "\tmodified:   src/existing.py\n"
    "\tdeleted:    src/old_module.py\n"
    "\trenamed:    src/a.py -> src/b.py\n"
    "\n"
    "Changes not staged for commit:\n"
    '  (use "git add <file>..." to update what will be committed)\n'
    "\tmodified:   src/existing.py\n"
    "\tmodified:   src/other.py\n"
    "\n"
    "Untracked files:\n"
    '  (use "git add <file>..." to include in what will be committed)\n'
    "\tnotes/scratch.md\n"
    "\ttemp/\n"
    "\n"
    'nothing added to commit but untracked files present (use "git add" to track)\n'
)

_STATUS_CLEAN = (
    "On branch main\n"
    "Your branch is up to date with 'origin/main'.\n"
    "\n"
    "nothing to commit, working tree clean\n"
)

_STATUS_PORCELAIN = (
    "## main...origin/main [ahead 2]\n"
    "M  src/staged_only.py\n"
    " M src/unstaged_only.py\n"
    "MM src/both.py\n"
    "A  src/new_staged.py\n"
    "?? notes/scratch.md\n"
    "!! build/tmp.bin\n"
)


class TestGitStatusLongFormat:
    def test_preserves_branch_name(self) -> None:
        strategy = GitStatusStrategy()
        result = strategy.compress(
            _STATUS_LONG_UNSTAGED,
            context=_ctx(_STATUS_LONG_UNSTAGED),
            level=CompressionLevel.BALANCED,
        )
        assert "main" in result

    def test_preserves_modified_files(self) -> None:
        strategy = GitStatusStrategy()
        result = strategy.compress(
            _STATUS_LONG_UNSTAGED,
            context=_ctx(_STATUS_LONG_UNSTAGED),
            level=CompressionLevel.BALANCED,
        )
        assert "src/main.rs" in result
        assert "src/lib.rs" in result

    def test_uses_change_kind_markers(self) -> None:
        strategy = GitStatusStrategy()
        result = strategy.compress(
            _STATUS_LONG_STAGED_UNSTAGED_UNTRACKED,
            context=_ctx(_STATUS_LONG_STAGED_UNSTAGED_UNTRACKED),
            level=CompressionLevel.BALANCED,
        )
        assert "+" in result or "new" in result.lower()
        assert "~" in result or "mod" in result.lower()
        assert "-" in result or "del" in result.lower()

    def test_separates_staged_unstaged_untracked(self) -> None:
        strategy = GitStatusStrategy()
        result = strategy.compress(
            _STATUS_LONG_STAGED_UNSTAGED_UNTRACKED,
            context=_ctx(_STATUS_LONG_STAGED_UNSTAGED_UNTRACKED),
            level=CompressionLevel.BALANCED,
        )
        result_lower = result.lower()
        assert "staged" in result_lower
        assert "unstaged" in result_lower
        assert "untracked" in result_lower

    def test_preserves_staged_file_names(self) -> None:
        strategy = GitStatusStrategy()
        result = strategy.compress(
            _STATUS_LONG_STAGED_UNSTAGED_UNTRACKED,
            context=_ctx(_STATUS_LONG_STAGED_UNSTAGED_UNTRACKED),
            level=CompressionLevel.BALANCED,
        )
        assert "src/new_module.py" in result
        assert "src/existing.py" in result
        assert "src/old_module.py" in result

    def test_preserves_untracked_files(self) -> None:
        strategy = GitStatusStrategy()
        result = strategy.compress(
            _STATUS_LONG_STAGED_UNSTAGED_UNTRACKED,
            context=_ctx(_STATUS_LONG_STAGED_UNSTAGED_UNTRACKED),
            level=CompressionLevel.BALANCED,
        )
        assert "notes/scratch.md" in result

    def test_skips_long_format_untracked_summary_sentence(self) -> None:
        strategy = GitStatusStrategy()
        result = strategy.compress(
            _STATUS_LONG_STAGED_UNSTAGED_UNTRACKED,
            context=_ctx(_STATUS_LONG_STAGED_UNSTAGED_UNTRACKED),
            level=CompressionLevel.BALANCED,
        )
        assert "nothing added to commit but untracked files present" not in result

    def test_preserves_ahead_info(self) -> None:
        strategy = GitStatusStrategy()
        result = strategy.compress(
            _STATUS_LONG_STAGED_UNSTAGED_UNTRACKED,
            context=_ctx(_STATUS_LONG_STAGED_UNSTAGED_UNTRACKED),
            level=CompressionLevel.BALANCED,
        )
        assert "ahead" in result.lower() or "2" in result

    def test_clean_status_shows_clean(self) -> None:
        strategy = GitStatusStrategy()
        result = strategy.compress(
            _STATUS_CLEAN,
            context=_ctx(_STATUS_CLEAN),
            level=CompressionLevel.BALANCED,
        )
        assert "clean" in result.lower() or "nothing to commit" in result.lower()

    def test_output_is_shorter_than_input(self) -> None:
        strategy = GitStatusStrategy()
        result = strategy.compress(
            _STATUS_LONG_STAGED_UNSTAGED_UNTRACKED,
            context=_ctx(_STATUS_LONG_STAGED_UNSTAGED_UNTRACKED),
            level=CompressionLevel.BALANCED,
        )
        assert len(result) < len(_STATUS_LONG_STAGED_UNSTAGED_UNTRACKED)

    def test_pass_through_non_git_status(self) -> None:
        strategy = GitStatusStrategy()
        content = "some random output\n"
        result = strategy.compress(
            content,
            context=_ctx(content, command_prefix="git log"),
            level=CompressionLevel.BALANCED,
        )
        assert result == content

    def test_pass_through_non_git(self) -> None:
        strategy = GitStatusStrategy()
        content = "some random output\n"
        result = strategy.compress(
            content,
            context=ToolOutputContext.for_text(
                tool_name="shell",
                tool_category="command_execution",
                command_signature="npm",
                command_prefix="npm test",
                content=content,
            ),
            level=CompressionLevel.BALANCED,
        )
        assert result == content

    def test_empty_input_passthrough(self) -> None:
        strategy = GitStatusStrategy()
        result = strategy.compress(
            "",
            context=_ctx(""),
            level=CompressionLevel.BALANCED,
        )
        assert result == ""

    def test_deterministic_output(self) -> None:
        strategy = GitStatusStrategy()
        ctx = _ctx(_STATUS_LONG_STAGED_UNSTAGED_UNTRACKED)
        first = strategy.compress(
            _STATUS_LONG_STAGED_UNSTAGED_UNTRACKED,
            context=ctx,
            level=CompressionLevel.BALANCED,
        )
        second = strategy.compress(
            _STATUS_LONG_STAGED_UNSTAGED_UNTRACKED,
            context=ctx,
            level=CompressionLevel.BALANCED,
        )
        assert first == second


class TestGitStatusPorcelainFormat:
    def test_porcelain_branch_preserved(self) -> None:
        strategy = GitStatusStrategy()
        result = strategy.compress(
            _STATUS_PORCELAIN,
            context=_ctx(_STATUS_PORCELAIN),
            level=CompressionLevel.BALANCED,
        )
        assert "main" in result

    def test_porcelain_preserves_file_names(self) -> None:
        strategy = GitStatusStrategy()
        result = strategy.compress(
            _STATUS_PORCELAIN,
            context=_ctx(_STATUS_PORCELAIN),
            level=CompressionLevel.BALANCED,
        )
        assert "src/staged_only.py" in result
        assert "src/unstaged_only.py" in result
        assert "src/both.py" in result
        assert "src/new_staged.py" in result
        assert "notes/scratch.md" in result

    def test_porcelain_groups_staged_unstaged_untracked(self) -> None:
        strategy = GitStatusStrategy()
        result = strategy.compress(
            _STATUS_PORCELAIN,
            context=_ctx(_STATUS_PORCELAIN),
            level=CompressionLevel.BALANCED,
        )
        result_lower = result.lower()
        assert "staged" in result_lower
        assert "unstaged" in result_lower
        assert "untracked" in result_lower

    def test_porcelain_ahead_preserved(self) -> None:
        strategy = GitStatusStrategy()
        result = strategy.compress(
            _STATUS_PORCELAIN,
            context=_ctx(_STATUS_PORCELAIN),
            level=CompressionLevel.BALANCED,
        )
        assert "ahead" in result.lower() or "2" in result


class TestGitStatusLevelScaling:
    def test_conservative_preserves_more_detail(self) -> None:
        files = [f"  modified:   src/module_{i:03d}.py\n" for i in range(30)]
        content = (
            "On branch main\n"
            "Changes not staged for commit:\n"
            + "".join(files)
            + "\nno changes added to commit\n"
        )
        strategy = GitStatusStrategy()
        result_cons = strategy.compress(
            content,
            context=_ctx(content),
            level=CompressionLevel.CONSERVATIVE,
        )
        result_aggr = strategy.compress(
            content,
            context=_ctx(content),
            level=CompressionLevel.AGGRESSIVE,
        )
        assert len(result_cons) >= len(result_aggr)

    def test_balanced_preserves_all_files_for_small_status(self) -> None:
        strategy = GitStatusStrategy()
        result = strategy.compress(
            _STATUS_LONG_STAGED_UNSTAGED_UNTRACKED,
            context=_ctx(_STATUS_LONG_STAGED_UNSTAGED_UNTRACKED),
            level=CompressionLevel.BALANCED,
        )
        assert "src/new_module.py" in result
        assert "src/existing.py" in result
        assert "src/old_module.py" in result
        assert "src/other.py" in result
        assert "notes/scratch.md" in result


class TestGitStatusExplicitFormatPassthrough:
    def test_explicit_format_passthrough(self) -> None:
        strategy = GitStatusStrategy()
        content = _STATUS_LONG_UNSTAGED
        ctx = _ctx(content)
        ctx = ctx.model_copy(
            update={
                "has_explicit_format": True,
                "identity": ctx.identity.model_copy(
                    update={"explicit_format_flags": ["--porcelain"]}
                ),
            }
        )
        result = strategy.compress(
            content,
            context=ctx,
            level=CompressionLevel.BALANCED,
        )
        assert result == content


class TestGitStatusLongFormatUnstagedNonModify:
    """Regression: long-format unstaged section must not drop deletions/renames."""

    _STATUS_LONG_UNSTAGED_DELETE_AND_RENAME = (
        "On branch main\n"
        "Your branch is up to date with 'origin/main'.\n"
        "\n"
        "Changes not staged for commit:\n"
        '  (use "git add <file>..." to update what will be committed)\n'
        "\tmodified:   src/changed.py\n"
        "\tdeleted:    src/old.py\n"
        "\trenamed:    src/a.py -> src/b.py\n"
        "\n"
        'no changes added to commit (use "git add" and/or "git commit -a")\n'
    )

    def test_unstaged_deleted_file_appears_in_output(self) -> None:
        strategy = GitStatusStrategy()
        result = strategy.compress(
            self._STATUS_LONG_UNSTAGED_DELETE_AND_RENAME,
            context=_ctx(self._STATUS_LONG_UNSTAGED_DELETE_AND_RENAME),
            level=CompressionLevel.BALANCED,
        )
        assert "src/old.py" in result
        assert "- src/old.py" in result

    def test_unstaged_renamed_file_appears_in_output(self) -> None:
        strategy = GitStatusStrategy()
        result = strategy.compress(
            self._STATUS_LONG_UNSTAGED_DELETE_AND_RENAME,
            context=_ctx(self._STATUS_LONG_UNSTAGED_DELETE_AND_RENAME),
            level=CompressionLevel.BALANCED,
        )
        assert "src/a.py -> src/b.py" in result or "->" in result

    def test_unstaged_modified_still_appears(self) -> None:
        strategy = GitStatusStrategy()
        result = strategy.compress(
            self._STATUS_LONG_UNSTAGED_DELETE_AND_RENAME,
            context=_ctx(self._STATUS_LONG_UNSTAGED_DELETE_AND_RENAME),
            level=CompressionLevel.BALANCED,
        )
        assert "src/changed.py" in result


class TestGitStatusPorcelainUnstagedChangeKind:
    """Regression: porcelain unstaged Y-column must use correct change markers."""

    def test_porcelain_unstaged_delete_shows_minus(self) -> None:
        content = "## main\n D src/old.py\n"
        strategy = GitStatusStrategy()
        result = strategy.compress(
            content, context=_ctx(content), level=CompressionLevel.BALANCED
        )
        assert "- src/old.py" in result

    def test_porcelain_unstaged_modify_shows_tilde(self) -> None:
        content = "## main\n M src/changed.py\n"
        strategy = GitStatusStrategy()
        result = strategy.compress(
            content, context=_ctx(content), level=CompressionLevel.BALANCED
        )
        assert "~ src/changed.py" in result


class TestGitStatusDottedBranchName:
    """Regression: branch names with dots must not be truncated."""

    def test_porcelain_dotted_branch_name_preserved(self) -> None:
        content = "## release/1.2...origin/release/1.2\n M src/main.py\n"
        strategy = GitStatusStrategy()
        result = strategy.compress(
            content, context=_ctx(content), level=CompressionLevel.BALANCED
        )
        assert "release/1.2" in result

    def test_porcelain_complex_dotted_branch_name(self) -> None:
        content = "## feature/v2.3.1-hotfix...origin/feature/v2.3.1-hotfix\n"
        strategy = GitStatusStrategy()
        result = strategy.compress(
            content, context=_ctx(content), level=CompressionLevel.BALANCED
        )
        assert "feature/v2.3.1-hotfix" in result
