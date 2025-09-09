import re
from re import Pattern
from typing import NamedTuple


class DangerousCommandRule(NamedTuple):
    pattern: Pattern[str]
    name: str
    description: str


class DangerousCommandConfig(NamedTuple):
    tool_names: list[str]
    rules: list[DangerousCommandRule]


# Default configuration with patterns for dangerous git commands
DEFAULT_DANGEROUS_COMMAND_RULES: list[DangerousCommandRule] = [
    # High-risk commands that discard local changes or files
    DangerousCommandRule(
        pattern=re.compile(r"git\s+reset\s+--hard(?:\s+\S+)?"),
        name="git-reset-hard",
        description="Discards all local changes to tracked files and moves HEAD.",
    ),
    # Submodule foreach performing aggressive clean inside submodules (more specific; keep before generic clean)
    DangerousCommandRule(
        pattern=re.compile(r"git\s+submodule\s+foreach\s+.*git\s+clean\s+.*-f.*"),
        name="git-submodule-foreach-clean-force",
        description="Runs clean -f in submodules via foreach.",
    ),
    # git clean with -f (optionally with -d/-x), but not when -n/--dry-run is present anywhere
    DangerousCommandRule(
        pattern=re.compile(
            r"^(?=.*\bgit\s+clean\b)(?=.*\s-[^\s]*f[^\s]*)(?!.*(?:\s-n|--dry-run)).*"
        ),
        name="git-clean-force",
        description="Deletes untracked files/directories; blocked unless dry-run.",
    ),
    DangerousCommandRule(
        pattern=re.compile(
            r"git\s+restore\s+--worktree(?:\s+--staged)?\s+(?:--source=\S+\s+)?(?:\.\.|:/$|--pathspec-from-file|\.)"
        ),
        name="git-restore-worktree",
        description="Overwrites the working tree with HEAD or a specified source.",
    ),
    DangerousCommandRule(
        pattern=re.compile(r"git\s+checkout\s+--\s*(?:\.|:/$)"),
        name="git-checkout-destructive",
        description="Overwrites the working tree with the index; a legacy, dangerous form of restore.",
    ),
    # Forced switch/checkout
    DangerousCommandRule(
        pattern=re.compile(r"git\s+(?:switch|checkout)\s+-f(?:\s|$)"),
        name="git-switch-checkout-force",
        description="Forced checkout/switch can discard local changes.",
    ),
    # Checkout orphan branch
    DangerousCommandRule(
        pattern=re.compile(r"git\s+checkout\s+--orphan\s+\S+"),
        name="git-checkout-orphan",
        description="Creates an orphan branch; may reset index/working tree.",
    ),
    # Remove tracked files from disk (no --cached)
    DangerousCommandRule(
        pattern=re.compile(r"git\s+rm\b(?!.*--cached).*--force(?:\s|$)"),
        name="git-rm-force",
        description="Removes tracked files from disk when --cached is not used.",
    ),
    # High-risk history rewriting commands
    DangerousCommandRule(
        pattern=re.compile(
            r"git\s+rebase(?:\s+-i|\s+--interactive|\s+--rebase-merges|\s|$)"
        ),
        name="git-rebase",
        description="Rewrites commit history; dangerous if already pushed.",
    ),
    DangerousCommandRule(
        pattern=re.compile(r"git\s+commit\s+--amend(?:\s|$)"),
        name="git-commit-amend",
        description="Rewrites the most recent commit.",
    ),
    DangerousCommandRule(
        pattern=re.compile(r"git\s+filter-branch(?:\s|$)"),
        name="git-filter-branch",
        description="Performs a global history rewrite; deprecated and dangerous.",
    ),
    DangerousCommandRule(
        pattern=re.compile(r"git\s+filter-repo(?:\s|$)"),
        name="git-filter-repo",
        description="Powerful repository rewrite.",
    ),
    DangerousCommandRule(
        pattern=re.compile(r"git\s+replace\s+"),
        name="git-replace",
        description="Alters object mapping; can disrupt history semantics.",
    ),
    # High-risk remote operations
    DangerousCommandRule(
        pattern=re.compile(r"git\s+push\s+(?:-f|--force)(?:\s|$)"),
        name="git-push-force",
        description="Overwrites remote history; can cause loss of work for collaborators.",
    ),
    DangerousCommandRule(
        pattern=re.compile(r"git\s+push\s+--force-with-lease(?:\S*)?(?:\s|$)"),
        name="git-push-force-with-lease",
        description="A safer force push, but still a rewrite; blocked as a precaution.",
    ),
    DangerousCommandRule(
        pattern=re.compile(r"git\s+push\s+(?:--delete|-d)\s+\S+"),
        name="git-push-delete-branch",
        description="Deletes a remote branch.",
    ),
    DangerousCommandRule(
        pattern=re.compile(r"git\s+push\s+\S+\s+:\S+"),
        name="git-push-delete-ref-legacy",
        description="Deletes a remote ref using legacy syntax.",
    ),
    DangerousCommandRule(
        pattern=re.compile(r"git\s+push\s+--mirror(?:\s|$)"),
        name="git-push-mirror",
        description="Forces remote to exactly match local (additions/deletions).",
    ),
    # Medium-to-high-risk local reference deletions
    DangerousCommandRule(
        pattern=re.compile(r"git\s+branch\s+-D\s+\S+"),
        name="git-branch-force-delete",
        description="Forcibly deletes a local branch, even if unmerged.",
    ),
    DangerousCommandRule(
        pattern=re.compile(r"git\s+branch\s+-d\s+\S+"),
        name="git-branch-delete",
        description="Deletes a local branch (may remove unmerged branch).",
    ),
    DangerousCommandRule(
        pattern=re.compile(r"git\s+tag\s+-d\s+\S+"),
        name="git-tag-delete",
        description="Deletes a local tag.",
    ),
    DangerousCommandRule(
        pattern=re.compile(r"git\s+update-ref\s+-d\s+\S+"),
        name="git-update-ref-delete",
        description="Deletes a ref directly.",
    ),
    DangerousCommandRule(
        pattern=re.compile(r"git\s+reflog\s+expire\s+--expire=now\s+--all"),
        name="git-reflog-expire-now",
        description="Expires reflog immediately for all refs.",
    ),
    # Pruning / GC
    DangerousCommandRule(
        pattern=re.compile(r"git\s+gc\s+--prune=now(?:\s|$)"),
        name="git-gc-prune-now",
        description="Immediate GC prune of unreachable objects.",
    ),
    DangerousCommandRule(
        pattern=re.compile(r"git\s+prune(?:\s|$)"),
        name="git-prune",
        description="Removes unreachable objects.",
    ),
    DangerousCommandRule(
        pattern=re.compile(r"git\s+repack\s+-d(?:\s|$)"),
        name="git-repack-delete",
        description="Repack with deletion of redundant packs.",
    ),
    DangerousCommandRule(
        pattern=re.compile(r"git\s+lfs\s+prune(?:\s|$)"),
        name="git-lfs-prune",
        description="Deletes unused LFS content locally.",
    ),
    # Worktrees and submodules
    DangerousCommandRule(
        pattern=re.compile(r"git\s+worktree\s+remove\s+--force\s+\S+"),
        name="git-worktree-remove-force",
        description="Removes a worktree forcefully.",
    ),
    DangerousCommandRule(
        pattern=re.compile(r"git\s+worktree\s+prune(?:\s|$)"),
        name="git-worktree-prune",
        description="Prunes worktrees.",
    ),
    DangerousCommandRule(
        pattern=re.compile(r"git\s+submodule\s+deinit\s+-f(?:\s|$)"),
        name="git-submodule-deinit-force",
        description="Force deinit submodules.",
    ),
]

DEFAULT_DANGEROUS_COMMAND_CONFIG = DangerousCommandConfig(
    tool_names=[
        "bash",
        "exec_command",
        "execute_command",
        "run_shell_command",
        "shell",
        "local_shell",
        "container.exec",
    ],
    rules=DEFAULT_DANGEROUS_COMMAND_RULES,
)
