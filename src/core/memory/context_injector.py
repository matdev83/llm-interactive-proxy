"""Context injector for ProxyMem feature.

Retrieves and injects relevant historical context into new sessions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.memory.config import MemoryConfiguration
from src.core.memory.prompt_loader import PromptLoader

if TYPE_CHECKING:
    from src.core.memory.models import SessionSummary
    from src.core.memory.repository import IMemoryRepository

logger = logging.getLogger(__name__)


class ContextInjector:
    """Retrieves and formats historical context for new sessions."""

    def __init__(
        self,
        config: MemoryConfiguration,
        repository: IMemoryRepository,
        prompt_loader: PromptLoader | None = None,
        llm_caller: object = None,
    ):
        """Initialize the context injector.

        Args:
            config: Memory configuration.
            repository: Repository for retrieving summaries.
            prompt_loader: Optional prompt loader.
            llm_caller: Optional LLM caller for context generation.
        """
        self._config = config
        self._repository = repository
        self._prompt_loader = prompt_loader or PromptLoader(
            context_prompt_path=config.context_prompt,
        )
        self._llm_caller = llm_caller

    async def get_context_for_session(
        self,
        user_id: str,
        current_prompt: str,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        project_root: str | None = None,
    ) -> str | None:
        """Retrieve relevant historical context for a new session.

        Args:
            user_id: The user identifier.
            current_prompt: The user's current prompt/message.
            tenant_id: Optional tenant identifier.
            project_id: Optional project identifier.
            project_root: Optional project root path.

        Returns:
            Formatted context string or None if no relevant context.
        """
        # Retrieve recent summaries
        summaries = await self._repository.get_recent_sessions(
            user_id,
            limit=self._config.max_sessions_to_consider,
            tenant_id=tenant_id,
            project_id=project_id,
            project_root=project_root,
        )

        if not summaries:
            logger.debug("No historical sessions found for user %s", user_id)
            return None

        # Format summaries for context
        formatted_summaries = self._format_summaries(summaries)

        # If no LLM caller, return simple formatted context
        if self._llm_caller is None:
            return self._build_simple_context(summaries)

        # Use LLM to generate relevant context
        context = await self._generate_context_with_llm(
            current_prompt=current_prompt,
            summaries=formatted_summaries,
            user_id=user_id,
            tenant_id=tenant_id,
            project_id=project_id,
            project_root=project_root,
        )

        return context

    def _format_summaries(self, summaries: list[SessionSummary]) -> str:
        """Format summaries for context prompt input."""
        parts = []

        for i, summary in enumerate(summaries, 1):
            parts.append(f"--- Session {i} ---")
            parts.append(f"Date: {summary.session_start.isoformat()}")
            parts.append(f"Title: {summary.title}")

            if summary.scope:
                parts.append(f"Scope: {summary.scope}")

            if summary.goals:
                parts.append("Goals:")
                for goal in summary.goals[:3]:  # Limit goals
                    parts.append(f"  - {goal}")

            if summary.key_decisions:
                parts.append("Key Decisions:")
                for decision in summary.key_decisions[:3]:
                    parts.append(f"  - {decision}")

            if summary.remaining_tasks:
                parts.append("Remaining Tasks:")
                for task in summary.remaining_tasks[:3]:
                    parts.append(f"  - [{task.status}] {task.description}")

            if summary.modified_files:
                files = [f.path for f in summary.modified_files[:5]]
                parts.append(f"Modified Files: {', '.join(files)}")

            if summary.errors:
                parts.append("Errors:")
                for error in summary.errors[:2]:
                    parts.append(f"  - {error}")

            if summary.risks_or_warnings:
                parts.append("Warnings:")
                for warning in summary.risks_or_warnings[:2]:
                    parts.append(f"  - {warning}")

            parts.append(f"Status: {summary.completion_status}")

            if summary.branch:
                parts.append(f"Branch: {summary.branch}")

            parts.append("")

        return "\n".join(parts)

    def _build_simple_context(self, summaries: list[SessionSummary]) -> str:
        """Build simple context without LLM call."""
        if not summaries:
            return ""

        parts = ["Prior Context:"]

        for summary in summaries[:3]:  # Limit to 3 most recent
            parts.append(
                f"- [{summary.session_start.strftime('%Y-%m-%d')}] {summary.title}"
            )

            if summary.remaining_tasks:
                open_tasks = [t for t in summary.remaining_tasks if t.status == "open"]
                if open_tasks:
                    parts.append(f"  Pending: {open_tasks[0].description}")

            if summary.key_decisions:
                parts.append(f"  Decision: {summary.key_decisions[0]}")

            if summary.risks_or_warnings:
                parts.append(f"  Warning: {summary.risks_or_warnings[0]}")

        return "\n".join(parts)

    async def _generate_context_with_llm(
        self,
        current_prompt: str,
        summaries: str,
        user_id: str,
        tenant_id: str | None,
        project_id: str | None,
        project_root: str | None,
    ) -> str | None:
        """Generate context using LLM call."""
        prompt_template = self._prompt_loader.load_context_prompt()

        variables = {
            "user_prompt": current_prompt,
            "session_summaries": summaries,
            "user_id": user_id,
            "tenant_id": tenant_id or "NONE",
            "project_id": project_id or "NONE",
            "project_root": project_root or "UNKNOWN",
            "max_tokens": str(self._config.max_context_tokens),
        }

        prompt = self._prompt_loader.substitute_variables(prompt_template, variables)

        try:
            response = await self._llm_caller(prompt)  # type: ignore
            return response if response else None
        except Exception as e:
            logger.warning("Failed to generate context with LLM: %s", e)
            return None

    def format_context_for_injection(self, context: str) -> str:
        """Format context for injection into system prompt.

        Args:
            context: The raw context string.

        Returns:
            Formatted context ready for injection.
        """
        if not context:
            return ""

        if self._config.context_template:
            return self._config.context_template.replace("{context}", context)

        return f"""<prior_session_context>
{context}
</prior_session_context>"""
