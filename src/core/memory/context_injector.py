"""Context injector for ProxyMem feature.

Retrieves and injects relevant historical context into new sessions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.core.memory.config import MemoryConfiguration
from src.core.memory.interfaces import LLMCaller
from src.core.memory.prompt_loader import PromptLoader

if TYPE_CHECKING:
    from src.core.memory.models import SessionSummary
    from src.core.memory.repository import IMemoryRepository

logger = logging.getLogger(__name__)

# Marker per Req 8.11 - inserted when no context is injected
NO_PRIOR_CONTEXT_MARKER = "[NO_PRIOR_CONTEXT_PROVIDED]"


@dataclass
class ScoredSummary:
    """Summary with relevance score for ranking."""

    summary: SessionSummary
    score: float


class ContextInjector:
    """Retrieves and formats historical context for new sessions.

    Implements relevance scoring, token limiting, and proper scoping
    as specified in Requirements 8, 9, 17, and 18.
    """

    def __init__(
        self,
        config: MemoryConfiguration,
        repository: IMemoryRepository,
        prompt_loader: PromptLoader | None = None,
        llm_caller: LLMCaller | None = None,
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

        Context is scoped by user_id, tenant_id, and project (Req 17, 18).
        Only summaries above the relevance threshold are included (Req 8.10).
        Context is limited to max_context_tokens (Req 8.4).

        Args:
            user_id: The user identifier.
            current_prompt: The user's current prompt/message.
            tenant_id: Optional tenant identifier.
            project_id: Optional project identifier.
            project_root: Optional project root path.

        Returns:
            Formatted context string or None if no relevant context.
        """
        # Retrieve recent summaries (scoped by user/tenant/project per Req 17, 18)
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

        # Score summaries by relevance (Req 8.10)
        scored = self._score_summaries(summaries, current_prompt)

        # Filter by relevance threshold (Req 8.10)
        threshold = self._config.context_relevance_threshold
        relevant = [s for s in scored if s.score >= threshold]

        if not relevant:
            logger.debug(
                "No summaries above relevance threshold %.2f for user %s",
                threshold,
                user_id,
            )
            return None

        # Sort by score (descending), then by recency for ties
        relevant.sort(key=lambda x: (-x.score, -x.summary.session_start.timestamp()))

        # Extract summaries
        filtered_summaries = [s.summary for s in relevant]

        # Format summaries for context
        formatted_summaries = self._format_summaries(filtered_summaries)

        # If no LLM caller, return simple formatted context
        if self._llm_caller is None:
            context = self._build_simple_context(filtered_summaries)
            # Apply token limiting (Req 8.4)
            return self._limit_tokens(context)

        # Use LLM to generate relevant context
        llm_context = await self._generate_context_with_llm(
            current_prompt=current_prompt,
            summaries=formatted_summaries,
            user_id=user_id,
            tenant_id=tenant_id,
            project_id=project_id,
            project_root=project_root,
        )

        if llm_context:
            # Apply token limiting (Req 8.4)
            return self._limit_tokens(llm_context)

        return None

    def _score_summaries(
        self, summaries: list[SessionSummary], current_prompt: str
    ) -> list[ScoredSummary]:
        """Score summaries by relevance to current prompt.

        Scoring strategy (Req 8.10):
        - File/feature overlap: +0.3 per matching file/component
        - Topic/goal match: +0.2 per matching keyword
        - Recency bonus: +0.2 for sessions within last 24h, +0.1 within 7d
        - Branch match: +0.1 if same branch

        Args:
            summaries: List of session summaries.
            current_prompt: The current user prompt.

        Returns:
            List of scored summaries.
        """
        prompt_lower = current_prompt.lower()
        prompt_words = set(prompt_lower.split())
        now = datetime.now(timezone.utc)

        scored = []
        for summary in summaries:
            score = 0.0

            # File/component overlap
            for file_change in summary.modified_files:
                file_path = file_change.path.lower()
                # Check if any file path component appears in prompt
                parts = file_path.replace("\\", "/").split("/")
                for part in parts:
                    if part and len(part) > 3 and part in prompt_lower:
                        score += 0.15
                        break

            # Topic/goal match - keywords from goals and scope
            keywords = set()
            if summary.scope:
                keywords.update(summary.scope.lower().split())
            for goal in summary.goals:
                keywords.update(goal.lower().split())
            if summary.title:
                keywords.update(summary.title.lower().split())

            # Filter common words
            common_words = {
                "the",
                "a",
                "an",
                "and",
                "or",
                "to",
                "for",
                "in",
                "on",
                "of",
                "with",
                "is",
                "are",
                "was",
                "were",
                "be",
                "been",
                "being",
            }
            keywords = keywords - common_words

            matching_keywords = prompt_words & keywords
            score += len(matching_keywords) * 0.1  # +0.1 per matching keyword

            # Recency bonus
            age = now - summary.session_start
            if age.days < 1:
                score += 0.2
            elif age.days < 7:
                score += 0.1

            # Remaining tasks bonus (incomplete work is more relevant)
            if summary.remaining_tasks:
                open_tasks = [t for t in summary.remaining_tasks if t.status == "open"]
                if open_tasks:
                    score += 0.15

            # Cap score at 1.0
            score = min(score, 1.0)

            scored.append(ScoredSummary(summary=summary, score=score))

        return scored

    def _limit_tokens(self, context: str) -> str | None:
        """Limit context to max_context_tokens (Req 8.4, 16.4).

        Uses simple word-based estimation (avg 4 chars per token).

        Args:
            context: The context string.

        Returns:
            Truncated context or None if cannot fit.
        """
        if not context:
            return None

        max_tokens = self._config.max_context_tokens
        # Estimate: ~4 characters per token on average
        max_chars = max_tokens * 4

        if len(context) <= max_chars:
            return context

        # Truncate to fit
        truncated = context[:max_chars]
        # Try to truncate at a sentence or line boundary
        last_newline = truncated.rfind("\n")
        last_period = truncated.rfind(". ")

        if last_newline > max_chars * 0.7:
            truncated = truncated[: last_newline + 1]
        elif last_period > max_chars * 0.7:
            truncated = truncated[: last_period + 1]

        logger.debug(
            "Context truncated from %d to %d chars (max_tokens=%d)",
            len(context),
            len(truncated),
            max_tokens,
        )

        return truncated + "\n[Context truncated due to token limit]"

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
            # Check for NO_RELEVANT_CONTEXT response
            if response and "NO_RELEVANT_CONTEXT" in response:
                return None
            return response if response else None
        except Exception as e:
            logger.warning("Failed to generate context with LLM: %s", e)
            return None

    def format_context_for_injection(self, context: str | None) -> str:
        """Format context for injection into request.

        Per Req 8.11: If no context available, return the marker.

        Args:
            context: The raw context string or None.

        Returns:
            Formatted context ready for injection, or marker if none.
        """
        if not context:
            # Per Req 8.11: Insert marker when no context
            return NO_PRIOR_CONTEXT_MARKER

        if self._config.context_template:
            return self._config.context_template.replace("{context}", context)

        return f"""<prior_session_context>
{context}
</prior_session_context>"""

    def get_no_context_marker(self) -> str:
        """Get the marker string for no prior context.

        Returns:
            The NO_PRIOR_CONTEXT_PROVIDED marker string.
        """
        return NO_PRIOR_CONTEXT_MARKER
