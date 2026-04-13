"""Resolve first-user-message append suffix from configured file at startup."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from src.core.config.models.resolved_app_config import ResolvedAppConfig

if TYPE_CHECKING:
    from src.core.config.app_config import AppConfig

logger = logging.getLogger(__name__)


def resolve_auto_append_first_prompt_text(cfg: AppConfig) -> str | None:
    """Resolve ``auto_append_first_prompt_filename`` into text content.

    Returns ``None`` when filename is unset. Raises ``ValueError`` when a path is
    set but is not a readable regular file.
    """

    raw = getattr(cfg, "auto_append_first_prompt_filename", None)
    if raw is None or not isinstance(raw, str) or not raw.strip():
        return None

    path = Path(raw.strip()).expanduser()
    resolved = path.resolve()
    if not path.is_file():
        raise ValueError(
            f"auto_append_first_prompt_filename: file not found or not a file: {resolved}"
        )

    text = path.read_text(encoding="utf-8")
    stripped = text.strip()

    if stripped:
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Auto-append first prompt: loaded %d characters from %s",
                len(stripped),
                resolved,
            )
        return stripped

    if logger.isEnabledFor(logging.INFO):
        logger.info(
            "Auto-append first prompt: file %s is empty or whitespace-only; "
            "nothing will be appended",
            resolved,
        )
    return None


def resolve_app_config(cfg: AppConfig) -> ResolvedAppConfig:
    """Resolve startup-derived configuration values for runtime use."""

    return ResolvedAppConfig(
        auto_append_first_prompt_text=resolve_auto_append_first_prompt_text(cfg)
    )
