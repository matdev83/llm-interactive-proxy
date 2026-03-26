"""Load first-user-message append suffix from configured file at startup."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.config.app_config import AppConfig

logger = logging.getLogger(__name__)


def hydrate_auto_append_first_prompt(cfg: AppConfig) -> None:
    """Read ``auto_append_first_prompt_filename`` into ``auto_append_first_prompt_text``.

    Clears ``auto_append_first_prompt_text`` when filename is unset. Raises
    ``ValueError`` when a path is set but is not a readable regular file.
    """
    raw = getattr(cfg, "auto_append_first_prompt_filename", None)
    if raw is None or not isinstance(raw, str) or not raw.strip():
        cfg.auto_append_first_prompt_text = None
        return

    path = Path(raw.strip()).expanduser()
    resolved = path.resolve()
    if not path.is_file():
        raise ValueError(
            f"auto_append_first_prompt_filename: file not found or not a file: {resolved}"
        )

    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    cfg.auto_append_first_prompt_text = stripped if stripped else None

    if stripped:
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Auto-append first prompt: loaded %d characters from %s",
                len(stripped),
                resolved,
            )
    elif logger.isEnabledFor(logging.INFO):
        logger.info(
            "Auto-append first prompt: file %s is empty or whitespace-only; "
            "nothing will be appended",
            resolved,
        )
