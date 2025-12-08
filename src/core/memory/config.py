"""Configuration for ProxyMem feature."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, field_validator

from src.core.interfaces.model_bases import DomainModel


class MemoryConfiguration(DomainModel):
    """Configuration for ProxyMem feature.

    Controls all aspects of the proxy-based memory layer including:
    - Global availability and default state
    - Model configuration for summary and context generation
    - Database and storage settings
    - Privacy controls and redaction
    - Analysis queue and concurrency limits
    - Project scoping and identity controls
    """

    model_config = ConfigDict(frozen=True)

    # Global availability (gates all other settings)
    available: bool = False

    # Default state when available
    default_enabled: bool = False

    # Model configuration
    summary_model: str | None = None  # backend:model format
    context_model: str | None = None  # backend:model format

    # Prompt configuration
    summary_prompt: str | None = None  # Path to custom prompt file
    context_prompt: str | None = None  # Path to custom prompt file

    # Database configuration
    database_path: str = "./var/memory.sqlite3"

    # Behavior configuration
    session_timeout_minutes: int = 30
    summarization_delay_seconds: int = (
        120  # Delay before summarizing sessions to avoid premature summarization
    )
    max_sessions_to_consider: int = 10
    max_context_tokens: int = 2000
    max_summary_tokens: int = 800
    max_transcript_chars: int = 50_000
    summary_completion_tokens: int = 10_000
    context_relevance_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    retention_days: int = 90
    max_buffer_size_bytes: int = 10 * 1024 * 1024  # 10MB

    # Analysis queue and concurrency
    analysis_queue_maxsize: int = 100
    analysis_timeout_seconds: int = 30
    max_concurrent_analyses: int = 4

    # Context injection template
    context_template: str | None = None

    # Privacy and control
    redaction_patterns: list[str] = Field(default_factory=list)
    persist_transcript: bool = False  # defaults to discard after summary
    disabled_users: set[str] = Field(default_factory=set)
    disabled_clients: set[str] = Field(default_factory=set)

    # Identity controls
    single_user_mode: bool = False  # if true, use a fixed user_id for all sessions
    fixed_user_id: str | None = None  # used only in single_user_mode

    # Prompt/schema versioning
    summary_prompt_version: str = "v1"
    summary_schema_version: str = "v1"

    # Project scoping
    require_project_discovery: bool = True
    project_discovery_mode: Literal["deterministic", "nondeterministic", "any"] = "any"

    @field_validator("summary_model", "context_model", mode="before")
    @classmethod
    def validate_model_spec(cls, v: str | None) -> str | None:
        """Validate model specification format (backend:model)."""
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("Model spec must be a string")
        if ":" not in v:
            raise ValueError(
                f"Invalid model spec '{v}': must be in 'backend:model' format"
            )
        return v

    @field_validator("summary_prompt", "context_prompt", mode="before")
    @classmethod
    def validate_prompt_path(cls, v: str | None) -> str | None:
        """Validate prompt file path has valid extension."""
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("Prompt path must be a string")
        if not v.endswith((".txt", ".md")):
            raise ValueError(f"Invalid prompt path '{v}': must end with .txt or .md")
        return v

    @field_validator("redaction_patterns", mode="before")
    @classmethod
    def validate_redaction_patterns(cls, v: list[str] | None) -> list[str]:
        """Validate redaction patterns are valid regex strings."""
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("Redaction patterns must be a list")
        import re

        validated = []
        for pattern in v:
            if not isinstance(pattern, str):
                raise ValueError(f"Redaction pattern must be a string: {pattern}")
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(f"Invalid regex pattern '{pattern}': {e}") from e
            validated.append(pattern)
        return validated

    @field_validator("fixed_user_id", mode="after")
    @classmethod
    def validate_fixed_user_id(cls, v: str | None, info: object) -> str | None:
        """Validate fixed_user_id is set when single_user_mode is True."""
        # Access values via info.data for Pydantic v2
        data = getattr(info, "data", {})
        single_user_mode = data.get("single_user_mode", False)
        if single_user_mode and not v:
            raise ValueError("fixed_user_id must be set when single_user_mode is True")
        return v
