from __future__ import annotations

from pydantic import ConfigDict

from src.core.interfaces.model_bases import DomainModel


class ModelAliasRule(DomainModel):
    """A rule for rewriting a model name."""

    model_config = ConfigDict(frozen=True)

    pattern: str
    replacement: str


class RewritingConfig(DomainModel):
    """Configuration for content rewriting."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    config_path: str = "config/replacements"


class EditPrecisionConfig(DomainModel):
    """Configuration for automated edit-precision tuning.

    When enabled, detects agent edit-failure prompts and lowers sampling
    parameters for the next single call to improve precision.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    temperature: float = 0.1
    min_top_p: float | None = 0.3
    override_top_p: bool = False
    override_top_k: bool = False
    target_top_k: int | None = None
    exclude_agents_regex: str | None = None
