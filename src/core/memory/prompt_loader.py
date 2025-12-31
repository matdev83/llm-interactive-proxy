"""Prompt loader for ProxyMem feature.

Loads and validates prompt templates from files with fallback to defaults.
"""

from __future__ import annotations

import logging
from pathlib import Path
from string import Template

logger = logging.getLogger(__name__)

DEFAULT_SUMMARY_PROMPT = """Analyze the session transcript and produce a structured XML summary.

<transcript>
{session_transcript}
</transcript>

Deterministic file edits (from proxy tool calls):
{deterministic_file_edits}

Deterministic git commits (from proxy tool calls):
{deterministic_git_commits}

Use the deterministic lists as authoritative: copy file paths into <touched_files> with statuses,
and commit hashes/messages into <git_operations> (type="commit"), using UNKNOWN only when lists are empty.

Output a valid XML document with <session_summary> as the root element containing:
- title, scope, goals, key_decisions, operations_performed
- modified_files, git_operations, tests_run, errors
- remaining_tasks, open_questions, risks_or_warnings, evidence
- completion_status (completed|partial|abandoned)

Maximum tokens: {max_tokens}
"""

DEFAULT_CONTEXT_PROMPT = """Analyze historical session summaries and extract relevant context.

Current prompt:
{user_prompt}

Historical summaries:
{session_summaries}

Produce a concise context block with relevant prior work, decisions, and warnings.
Maximum tokens: {max_tokens}
"""


class PromptLoader:
    """Loads prompt templates from files with fallback to defaults."""

    def __init__(
        self,
        summary_prompt_path: str | None = None,
        context_prompt_path: str | None = None,
        prompts_dir: str | None = None,
    ):
        """Initialize the prompt loader.

        Args:
            summary_prompt_path: Path to custom summary prompt file.
            context_prompt_path: Path to custom context prompt file.
            prompts_dir: Base directory for prompt files.
        """
        self._prompts_dir = Path(prompts_dir) if prompts_dir else Path("config/prompts")
        self._summary_prompt_path = summary_prompt_path
        self._context_prompt_path = context_prompt_path
        self._summary_template: str | None = None
        self._context_template: str | None = None

    def load_summary_prompt(self) -> str:
        """Load the summary generation prompt.

        Returns:
            The prompt template string.
        """
        if self._summary_template is not None:
            return self._summary_template

        self._summary_template = self._load_prompt(
            self._summary_prompt_path,
            "memory_summary.md",
            DEFAULT_SUMMARY_PROMPT,
        )
        return self._summary_template

    def load_context_prompt(self) -> str:
        """Load the context retrieval prompt.

        Returns:
            The prompt template string.
        """
        if self._context_template is not None:
            return self._context_template

        self._context_template = self._load_prompt(
            self._context_prompt_path,
            "memory_context.md",
            DEFAULT_CONTEXT_PROMPT,
        )
        return self._context_template

    def _load_prompt(
        self,
        custom_path: str | None,
        default_filename: str,
        fallback_content: str,
    ) -> str:
        """Load a prompt from file with fallback.

        Args:
            custom_path: Optional custom file path.
            default_filename: Default filename in prompts directory.
            fallback_content: Hardcoded fallback if no file found.

        Returns:
            The prompt template string.
        """
        paths_to_try = []

        if custom_path:
            paths_to_try.append(Path(custom_path))

        paths_to_try.append(self._prompts_dir / default_filename)

        for path in paths_to_try:
            if path.exists():
                try:
                    content = path.read_text(encoding="utf-8")
                    logger.debug("Loaded prompt from %s", path)
                    return content
                except Exception as e:
                    logger.warning(
                        "Failed to read prompt from %s: %s", path, e, exc_info=True
                    )

        logger.info("Using default fallback prompt for %s", default_filename)
        return fallback_content

    def substitute_variables(
        self,
        template: str,
        variables: dict[str, str],
    ) -> str:
        """Substitute variables in a prompt template.

        Uses Python's string.Template for safe substitution.

        Args:
            template: The template string with {variable} placeholders.
            variables: Dictionary of variable names to values.

        Returns:
            The template with variables substituted.
        """
        # Convert {var} to $var for Template
        converted = template
        for key in variables:
            converted = converted.replace(f"{{{key}}}", f"${key}")

        tmpl = Template(converted)
        return tmpl.safe_substitute(variables)

    def validate_paths(self) -> list[str]:
        """Validate that configured prompt paths exist.

        Returns:
            List of error messages for invalid paths.
        """
        errors = []

        if self._summary_prompt_path:
            path = Path(self._summary_prompt_path)
            if not path.exists():
                errors.append(f"Summary prompt not found: {path}")

        if self._context_prompt_path:
            path = Path(self._context_prompt_path)
            if not path.exists():
                errors.append(f"Context prompt not found: {path}")

        return errors
