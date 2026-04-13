from __future__ import annotations

from pydantic import ConfigDict

from src.core.interfaces.model_bases import DomainModel


class ResolvedAppConfig(DomainModel):
    """Startup-resolved configuration values derived from AppConfig."""

    model_config = ConfigDict(frozen=True)

    auto_append_first_prompt_text: str | None = None
