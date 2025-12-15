"""Unit tests for MemoryConfiguration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from src.core.memory.config import MemoryConfiguration


class TestMemoryConfiguration:
    """Tests for MemoryConfiguration Pydantic model."""

    def test_default_configuration(self) -> None:
        """Test default configuration values."""
        config = MemoryConfiguration()

        assert config.available is False
        assert config.default_enabled is False
        assert config.summary_model is None
        assert config.context_model is None
        assert config.database_path == "./var/memory.sqlite3"
        assert config.session_timeout_minutes == 30
        assert config.max_sessions_to_consider == 10
        assert config.max_context_tokens == 2000
        assert config.max_summary_tokens == 800
        assert config.max_transcript_chars == 50_000
        assert config.summary_completion_tokens == 10_000
        assert config.context_relevance_threshold == 0.5
        assert config.retention_days == 90
        assert config.max_buffer_size_bytes == 10 * 1024 * 1024
        assert config.analysis_queue_maxsize == 100
        assert config.analysis_timeout_seconds == 30
        assert config.max_concurrent_analyses == 4
        assert config.single_user_mode is False
        assert config.fixed_user_id is None
        assert config.require_project_discovery is True
        assert config.project_discovery_mode == "any"
        assert config.summary_schema_version == "v1"
        assert config.summary_prompt_version == "v1"

    def test_configuration_with_valid_values(self) -> None:
        """Test configuration with custom valid values."""
        config = MemoryConfiguration(
            available=True,
            default_enabled=True,
            summary_model="openai:gpt-4o",
            context_model="anthropic:claude-3-sonnet",
            database_path="/custom/path/memory.db",
            session_timeout_minutes=60,
            max_sessions_to_consider=20,
            max_context_tokens=4000,
            retention_days=180,
            summary_schema_version="v2",
        )

        assert config.available is True
        assert config.default_enabled is True
        assert config.summary_model == "openai:gpt-4o"
        assert config.context_model == "anthropic:claude-3-sonnet"
        assert config.database_path == "/custom/path/memory.db"
        assert config.session_timeout_minutes == 60
        assert config.max_sessions_to_consider == 20
        assert config.max_context_tokens == 4000
        assert config.retention_days == 180
        assert config.summary_schema_version == "v2"

    def test_invalid_model_spec_missing_colon(self) -> None:
        """Test that model spec without colon raises ValidationError."""
        with pytest.raises(ValueError, match="backend:model"):
            MemoryConfiguration(summary_model="gpt-4o-without-backend")

    def test_invalid_model_spec_context_model(self) -> None:
        """Test that context model spec without colon raises ValidationError."""
        with pytest.raises(ValueError, match="backend:model"):
            MemoryConfiguration(context_model="claude-sonnet")

    def test_valid_model_spec(self) -> None:
        """Test valid model specs are accepted."""
        config = MemoryConfiguration(
            summary_model="gemini:gemini-2.0-flash",
            context_model="openai:gpt-4o-mini",
        )
        assert config.summary_model == "gemini:gemini-2.0-flash"
        assert config.context_model == "openai:gpt-4o-mini"

    def test_invalid_prompt_path_extension(self) -> None:
        """Test that prompt path with invalid extension raises ValidationError."""
        with pytest.raises(ValueError, match=r"\.txt or \.md"):
            MemoryConfiguration(summary_prompt="/path/to/prompt.yaml")

    def test_valid_prompt_paths(self) -> None:
        """Test valid prompt paths are accepted."""
        config = MemoryConfiguration(
            summary_prompt="/path/to/summary.md",
            context_prompt="/path/to/context.txt",
        )
        assert config.summary_prompt == "/path/to/summary.md"
        assert config.context_prompt == "/path/to/context.txt"

    def test_invalid_redaction_pattern_regex(self) -> None:
        """Test that invalid regex pattern raises ValidationError."""
        with pytest.raises(ValueError, match="Invalid regex pattern"):
            MemoryConfiguration(redaction_patterns=["[invalid(regex"])

    def test_valid_redaction_patterns(self) -> None:
        """Test valid regex patterns are accepted."""
        patterns = [
            r"sk-[a-zA-Z0-9]+",
            r"api_key\s*=\s*['\"][^'\"]+['\"]",
            r"password:\s*\S+",
        ]
        config = MemoryConfiguration(redaction_patterns=patterns)
        assert config.redaction_patterns == patterns

    def test_single_user_mode_requires_fixed_user_id(self) -> None:
        """Test that single_user_mode=True requires fixed_user_id."""
        with pytest.raises(ValueError, match="fixed_user_id must be set"):
            MemoryConfiguration(single_user_mode=True, fixed_user_id=None)

    def test_single_user_mode_with_fixed_user_id(self) -> None:
        """Test single_user_mode with valid fixed_user_id."""
        config = MemoryConfiguration(
            single_user_mode=True,
            fixed_user_id="default-user-123",
        )
        assert config.single_user_mode is True
        assert config.fixed_user_id == "default-user-123"

    def test_context_relevance_threshold_bounds(self) -> None:
        """Test context_relevance_threshold validation bounds."""
        # Valid value at lower bound
        config = MemoryConfiguration(context_relevance_threshold=0.0)
        assert config.context_relevance_threshold == 0.0

        # Valid value at upper bound
        config = MemoryConfiguration(context_relevance_threshold=1.0)
        assert config.context_relevance_threshold == 1.0

        # Invalid value below lower bound
        with pytest.raises(ValueError):
            MemoryConfiguration(context_relevance_threshold=-0.1)

        # Invalid value above upper bound
        with pytest.raises(ValueError):
            MemoryConfiguration(context_relevance_threshold=1.1)

    def test_project_discovery_mode_values(self) -> None:
        """Test project_discovery_mode accepts valid literal values."""
        for mode in ["deterministic", "nondeterministic", "any"]:
            config = MemoryConfiguration(project_discovery_mode=mode)  # type: ignore[arg-type]
            assert config.project_discovery_mode == mode

    def test_disabled_users_and_clients(self) -> None:
        """Test disabled_users and disabled_clients sets."""
        config = MemoryConfiguration(
            disabled_users={"user1", "user2"},
            disabled_clients={"client-a", "client-b"},
        )
        assert config.disabled_users == {"user1", "user2"}
        assert config.disabled_clients == {"client-a", "client-b"}

    def test_configuration_is_frozen(self) -> None:
        """Test that configuration is immutable (frozen)."""
        config = MemoryConfiguration(available=True)

        with pytest.raises(ValidationError):  # ValidationError for frozen model
            config.available = False  # type: ignore[misc]

    def test_empty_redaction_patterns_default(self) -> None:
        """Test that redaction_patterns defaults to empty list."""
        config = MemoryConfiguration()
        assert config.redaction_patterns == []

    def test_none_model_specs_allowed(self) -> None:
        """Test that None model specs are allowed (feature disabled)."""
        config = MemoryConfiguration(
            summary_model=None,
            context_model=None,
        )
        assert config.summary_model is None
        assert config.context_model is None
