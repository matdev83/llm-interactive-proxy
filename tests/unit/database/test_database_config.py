"""Unit tests for database configuration."""

import pytest
from src.core.database.config import DatabaseConfig


class TestDatabaseConfig:
    """Tests for DatabaseConfig model."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = DatabaseConfig()

        assert config.url == "sqlite+aiosqlite:///./var/db/proxy.db"
        assert config.pool_size == 5
        assert config.max_overflow == 10
        assert config.pool_timeout == 30
        assert config.echo is False
        assert config.echo_pool is False
        assert config.auto_migrate is True

    def test_custom_sqlite_url(self) -> None:
        """Test custom SQLite URL."""
        config = DatabaseConfig(url="sqlite+aiosqlite:///./custom/test.db")
        assert config.url == "sqlite+aiosqlite:///./custom/test.db"
        assert config.is_sqlite is True
        assert config.is_async is True

    def test_postgresql_url(self) -> None:
        """Test PostgreSQL URL configuration."""
        config = DatabaseConfig(
            url="postgresql+asyncpg://user:pass@localhost:5432/testdb"
        )
        assert config.is_sqlite is False
        assert config.is_async is True

    def test_sync_sqlite_url(self) -> None:
        """Test sync SQLite URL detection."""
        config = DatabaseConfig(url="sqlite:///./test.db")
        assert config.is_sqlite is True
        assert config.is_async is False

    def test_invalid_url_format(self) -> None:
        """Test that invalid URL format raises error."""
        with pytest.raises(ValueError, match="Invalid database URL format"):
            DatabaseConfig(url="invalid-url")

    def test_empty_url_raises_error(self) -> None:
        """Test that empty URL raises error."""
        with pytest.raises(ValueError, match="cannot be empty"):
            DatabaseConfig(url="")

    def test_pool_size_validation(self) -> None:
        """Test pool size validation."""
        # Valid range
        config = DatabaseConfig(pool_size=10)
        assert config.pool_size == 10

        # Out of range
        with pytest.raises(ValueError):
            DatabaseConfig(pool_size=0)

        with pytest.raises(ValueError):
            DatabaseConfig(pool_size=101)

    def test_max_overflow_validation(self) -> None:
        """Test max_overflow validation."""
        config = DatabaseConfig(max_overflow=20)
        assert config.max_overflow == 20

        with pytest.raises(ValueError):
            DatabaseConfig(max_overflow=-1)

    def test_pool_timeout_validation(self) -> None:
        """Test pool_timeout validation."""
        config = DatabaseConfig(pool_timeout=60)
        assert config.pool_timeout == 60

        with pytest.raises(ValueError):
            DatabaseConfig(pool_timeout=0)

    def test_echo_settings(self) -> None:
        """Test echo settings."""
        config = DatabaseConfig(echo=True, echo_pool=True)
        assert config.echo is True
        assert config.echo_pool is True

    def test_auto_migrate_setting(self) -> None:
        """Test auto_migrate setting."""
        config = DatabaseConfig(auto_migrate=False)
        assert config.auto_migrate is False

    def test_config_is_frozen(self) -> None:
        """Test that config is immutable (frozen)."""
        from pydantic import ValidationError

        config = DatabaseConfig()
        with pytest.raises(ValidationError):
            config.url = "other://url"  # type: ignore
