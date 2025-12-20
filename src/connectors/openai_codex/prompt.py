"""Prompt resolver for OpenAI Codex connector.

This module provides prompt resolution and instruction merging functionality.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.contracts import CodexConnectorSettings
from src.connectors.openai_codex.interfaces import IPromptResolver

# Constants matching OpenAICodexConnector
CODEX_PROMPT_RESOURCE_PACKAGE = "src.resources.codex"
CODEX_PROMPT_RESOURCE_NAME = "gpt_5_codex_prompt.md"


class PromptResolver(IPromptResolver):
    """Service for resolving system prompts and user instructions.

    Handles prompt mode selection, section combination, and sanitization.
    """

    def resolve_system_prompt(
        self,
        settings: CodexConnectorSettings,
        capabilities: CodexClientCapabilities,
    ) -> str:
        """Return the resolved system prompt for the request.

        Args:
            settings: Connector settings
            capabilities: Client capabilities

        Returns:
            Resolved and sanitized system prompt
        """
        prompt_mode = (capabilities.prompt_mode or "codex_default").lower()
        prompt_cfg = settings.prompt

        default_prompt_template = prompt_cfg.get("template")
        default_prompt = (
            default_prompt_template
            if isinstance(default_prompt_template, str)
            and default_prompt_template.strip()
            else self._codex_system_prompt()
        )
        prepend_sections = list(prompt_cfg.get("prepend", []))
        append_sections = list(prompt_cfg.get("append", []))
        deduplicate = bool(prompt_cfg.get("deduplicate", True))
        fallback_to_default = bool(prompt_cfg.get("fallback_to_default", True))

        if prompt_mode == "codex_default":
            combined = [
                *prepend_sections,
                default_prompt,
                *append_sections,
            ]
            result = self._combine_prompt_sections(combined, deduplicate)
            return result if result is not None else ""

        if prompt_mode == "merge_custom":
            # In merge_custom mode, custom instructions are handled separately
            # via resolve_instructions, so we just return default prompt
            combined = [
                *prepend_sections,
                default_prompt,
                *append_sections,
            ]
            result = self._combine_prompt_sections(combined, deduplicate)
            return result if result is not None else ""

        if prompt_mode == "custom_only":
            # Custom-only mode: only use prepend/append, fallback to default if empty
            combined = prepend_sections + append_sections
            merged = self._combine_prompt_sections(combined, deduplicate)
            if merged:
                return merged
            if not fallback_to_default:
                return ""
            fallback_combined = [*prepend_sections, default_prompt, *append_sections]
            result = self._combine_prompt_sections(fallback_combined, deduplicate)
            return result if result is not None else ""

        # Fallback to default
        fallback_combined = [*prepend_sections, default_prompt, *append_sections]
        result = self._combine_prompt_sections(fallback_combined, deduplicate)
        return result if result is not None else ""

    def resolve_instructions(
        self,
        settings: CodexConnectorSettings,
        user_instructions: str | None,
    ) -> str | None:
        """Return merged instructions or None if not applicable.

        Args:
            settings: Connector settings
            user_instructions: Optional user-provided instructions

        Returns:
            Merged instructions wrapped in <user_instructions> tags or None
        """
        if not user_instructions:
            return None

        # Sanitize and wrap instructions
        sanitized = self._sanitize_codex_instructions(user_instructions.strip())
        if not sanitized:
            return None

        return f"<user_instructions>\n\n{sanitized}\n\n</user_instructions>"

    @staticmethod
    def _combine_prompt_sections(
        sections: Sequence[str], deduplicate: bool
    ) -> str | None:
        """Combine prompt sections with optional deduplication.

        Args:
            sections: List of prompt sections
            deduplicate: Whether to remove duplicate sections

        Returns:
            Combined prompt string or None if empty
        """
        seen: set[str] = set()
        ordered: list[str] = []
        for section in sections:
            if not isinstance(section, str):
                continue
            normalized = section.strip()
            if not normalized:
                continue
            key = normalized if deduplicate else f"{normalized}_{len(ordered)}"
            if deduplicate:
                if key in seen:
                    continue
                seen.add(key)
            # Keep the original section content (preserving trailing newlines)
            ordered.append(section)
        if not ordered:
            return None

        # If only one section, return it as-is
        if len(ordered) == 1:
            return ordered[0]

        # When joining multiple sections, use "\n\n" between them
        return "\n\n".join(ordered)

    @staticmethod
    def _sanitize_codex_instructions(text: str) -> str:
        """Remove or normalize characters that the Codex API rejects in instructions.

        Args:
            text: Text to sanitize

        Returns:
            Sanitized text with special characters replaced
        """
        replacements: dict[str, str] = {
            "\u2010": "-",  # hyphen
            "\u2011": "-",  # non-breaking hyphen
            "\u2012": "-",  # figure dash
            "\u2013": "-",  # en dash
            "\u2014": "--",  # em dash
            "\u2015": "--",  # horizontal bar
            "\u2026": "...",  # ellipsis
            "\u2192": "->",  # arrow
        }
        normalized_parts: list[str] = []
        for char in text:
            if ord(char) < 128:
                normalized_parts.append(char)
            else:
                normalized_parts.append(replacements.get(char, ""))
        return "".join(normalized_parts)

    @classmethod
    @lru_cache(maxsize=1)
    def _codex_system_prompt(cls) -> str:
        """Load the Codex system prompt from bundled resources or vendor sources.

        Returns:
            Codex system prompt text

        Raises:
            RuntimeError: If prompt file cannot be found
        """
        import logging

        logger = logging.getLogger(__name__)

        try:
            from importlib import resources as importlib_resources

            return importlib_resources.read_text(
                CODEX_PROMPT_RESOURCE_PACKAGE,
                CODEX_PROMPT_RESOURCE_NAME,
                encoding="utf-8",
            )
        except (FileNotFoundError, ModuleNotFoundError):
            pass
        except Exception as exc:  # pragma: no cover - diagnostic path
            logger.warning(
                "Failed to load Codex system prompt from package resources: %s", exc
            )

        fallback_paths = [
            Path(__file__).resolve().parents[2]
            / "dev"
            / "thrdparty"
            / "codex"
            / "codex-rs"
            / "core"
            / CODEX_PROMPT_RESOURCE_NAME,
            Path(__file__).resolve().parents[1]
            / "resources"
            / "codex"
            / CODEX_PROMPT_RESOURCE_NAME,
        ]
        for candidate in fallback_paths:
            try:
                if candidate.exists():
                    return candidate.read_text(encoding="utf-8")
            except Exception as exc:  # pragma: no cover - diagnostic path
                logger.warning(
                    "Failed loading Codex prompt from %s: %s", candidate, exc
                )

        raise RuntimeError(
            "Codex system prompt not found. Ensure gpt_5_codex_prompt.md is bundled."
        )
