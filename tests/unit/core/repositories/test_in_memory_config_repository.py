"""
Tests for InMemoryConfigRepository.

This module tests the in-memory configuration repository implementation.
"""

from typing import Any

import pytest
from src.core.repositories.in_memory_config_repository import InMemoryConfigRepository


class TestInMemoryConfigRepository:
    """Tests for InMemoryConfigRepository class."""

    @pytest.fixture
    def repository(self) -> InMemoryConfigRepository:
        """Create a fresh InMemoryConfigRepository for each test."""
        return InMemoryConfigRepository()

    @pytest.fixture
    def sample_config(self) -> dict[str, Any]:
        """Create a sample configuration for testing."""
        return {
            "backend_type": "openai",
            "model": "gpt-4",
            "temperature": 0.7,
            "max_tokens": 1000,
            "timeout": 30,
        }

    def test_initialization(self, repository: InMemoryConfigRepository) -> None:
        """Test repository initialization."""
        assert repository._configs == {}

    @pytest.mark.asyncio
    async def test_get_config_empty_repository(
        self, repository: InMemoryConfigRepository
    ) -> None:
        """Test get_config on empty repository."""
        result = await repository.get_config("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_and_get_config(
        self, repository: InMemoryConfigRepository, sample_config: dict[str, Any]
    ) -> None:
        """Test setting and getting configuration."""
        key = "test-config"

        # Initially should not exist
        assert await repository.get_config(key) is None

        # Set the configuration
        await repository.set_config(key, sample_config)

        # Should now exist and match
        result = await repository.get_config(key)
        assert result == sample_config
        # Note: The current implementation returns the same object, not a copy

    @pytest.mark.asyncio
    async def test_set_config_overwrites_existing(
        self, repository: InMemoryConfigRepository, sample_config: dict[str, Any]
    ) -> None:
        """Test that set_config overwrites existing configuration."""
        key = "test-config"

        # Set initial config
        initial_config = {"initial": "value"}
        await repository.set_config(key, initial_config)
        assert await repository.get_config(key) == initial_config

        # Overwrite with new config
        await repository.set_config(key, sample_config)
        assert await repository.get_config(key) == sample_config

    @pytest.mark.asyncio
    async def test_delete_config_existing(
        self, repository: InMemoryConfigRepository, sample_config: dict[str, Any]
    ) -> None:
        """Test deleting an existing configuration."""
        key = "test-config"
        await repository.set_config(key, sample_config)

        # Verify it exists
        assert await repository.get_config(key) is not None

        # Delete it
        result = await repository.delete_config(key)
        assert result is True

        # Verify it's gone
        assert await repository.get_config(key) is None

    @pytest.mark.asyncio
    async def test_delete_config_nonexistent(
        self, repository: InMemoryConfigRepository
    ) -> None:
        """Test deleting a nonexistent configuration."""
        result = await repository.delete_config("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_multiple_configs(self, repository: InMemoryConfigRepository) -> None:
        """Test handling multiple configurations."""
        configs = {
            "config1": {"key": "value1"},
            "config2": {"key": "value2"},
            "config3": {"key": "value3"},
        }

        # Set all configurations
        for key, config in configs.items():
            await repository.set_config(key, config)

        # Verify all can be retrieved
        for key, expected_config in configs.items():
            result = await repository.get_config(key)
            assert result == expected_config

    @pytest.mark.asyncio
    async def test_config_data_types(
        self, repository: InMemoryConfigRepository
    ) -> None:
        """Test storing various data types in configuration."""
        test_configs = {
            "string_config": {"value": "string"},
            "int_config": {"value": 42},
            "float_config": {"value": 3.14},
            "bool_config": {"value": True},
            "list_config": {"value": [1, 2, 3]},
            "dict_config": {"value": {"nested": "data"}},
            "mixed_config": {
                "string": "text",
                "number": 123,
                "flag": False,
                "items": ["a", "b", "c"],
            },
        }

        # Set and verify each config
        for key, config in test_configs.items():
            await repository.set_config(key, config)
            result = await repository.get_config(key)
            assert result == config

    @pytest.mark.asyncio
    async def test_empty_config_values(
        self, repository: InMemoryConfigRepository
    ) -> None:
        """Test storing empty configuration values."""
        empty_configs = {
            "empty_dict": {},
            "empty_list": [],
            "empty_string": "",
            "none_value": None,
        }

        for key, config in empty_configs.items():
            await repository.set_config(key, config)
            result = await repository.get_config(key)
            assert result == config

    @pytest.mark.asyncio
    async def test_large_config_data(
        self, repository: InMemoryConfigRepository
    ) -> None:
        """Test storing large configuration data."""
        large_config = {
            "large_list": list(range(1000)),
            "nested_dict": {f"key_{i}": f"value_{i}" for i in range(100)},
            "big_string": "x" * 10000,
        }

        key = "large-config"
        await repository.set_config(key, large_config)

        result = await repository.get_config(key)
        assert result == large_config

    @pytest.mark.asyncio
    async def test_config_key_types(self, repository: InMemoryConfigRepository) -> None:
        """Test using different key types."""
        sample_config = {"test": "value"}

        # Test string keys
        await repository.set_config("string_key", sample_config)
        assert await repository.get_config("string_key") == sample_config

        # Test keys with special characters
        await repository.set_config("key-with-dashes", sample_config)
        assert await repository.get_config("key-with-dashes") == sample_config

        await repository.set_config("key_with_underscores", sample_config)
        assert await repository.get_config("key_with_underscores") == sample_config

        # Test numeric keys (will be converted to string)
        await repository.set_config("123", sample_config)
        assert await repository.get_config("123") == sample_config

    @pytest.mark.asyncio
    async def test_config_isolation(
        self, repository: InMemoryConfigRepository, sample_config: dict[str, Any]
    ) -> None:
        """Test that configurations are properly isolated."""
        key1, key2 = "config1", "config2"
        config1 = {"unique": "to_config1"}
        config2 = {"unique": "to_config2"}

        # Set both configurations
        await repository.set_config(key1, config1)
        await repository.set_config(key2, config2)

        # Modify one config
        config1["modified"] = True
        await repository.set_config(key1, config1)

        # Verify the other config is unchanged
        result2 = await repository.get_config(key2)
        assert result2 == config2
        assert "modified" not in result2

    @pytest.mark.asyncio
    async def test_delete_all_configs(
        self, repository: InMemoryConfigRepository, sample_config: dict[str, Any]
    ) -> None:
        """Test deleting all configurations."""
        configs = ["config1", "config2", "config3"]

        # Add all configs
        for key in configs:
            await repository.set_config(key, sample_config)

        # Delete all configs
        for key in configs:
            result = await repository.delete_config(key)
            assert result is True

        # Verify all are gone
        for key in configs:
            assert await repository.get_config(key) is None

    @pytest.mark.asyncio
    async def test_repository_state_after_operations(
        self, repository: InMemoryConfigRepository, sample_config: dict[str, Any]
    ) -> None:
        """Test repository state after various operations."""
        # Start empty
        assert repository._configs == {}

        # Add a config
        key = "test"
        await repository.set_config(key, sample_config)
        assert key in repository._configs

        # Get the config (should not modify state)
        await repository.get_config(key)
        assert repository._configs[key] == sample_config

        # Delete the config
        await repository.delete_config(key)
        assert repository._configs == {}

    @pytest.mark.asyncio
    async def test_none_config_handling(
        self, repository: InMemoryConfigRepository
    ) -> None:
        """Test handling of None configuration values."""
        key = "none-config"

        # Setting None should work
        await repository.set_config(key, None)

        # Getting None should work
        result = await repository.get_config(key)
        assert result is None

        # Deleting should work
        delete_result = await repository.delete_config(key)
        assert delete_result is True
