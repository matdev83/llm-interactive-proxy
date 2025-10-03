"""
Tests for ProjectConfiguration class.

This module tests the project configuration functionality including
project name and directory settings.
"""

from src.core.domain.configuration.project_config import ProjectConfiguration


class TestProjectConfiguration:
    """Tests for ProjectConfiguration class."""

    def test_default_initialization(self) -> None:
        """Test default initialization."""
        config = ProjectConfiguration()

        assert config.project is None
        assert config.project_dir is None

    def test_initialization_with_values(self) -> None:
        """Test initialization with specific values."""
        config = ProjectConfiguration(
            project="my-project",
            project_dir="/path/to/project",
        )

        assert config.project == "my-project"
        assert config.project_dir == "/path/to/project"

    def test_with_project_method(self) -> None:
        """Test with_project method."""
        config = ProjectConfiguration(project=None)

        new_config = config.with_project("test-project")

        assert new_config.project == "test-project"
        assert new_config is not config

    def test_with_project_dir_method(self) -> None:
        """Test with_project_dir method."""
        config = ProjectConfiguration(project_dir=None)

        new_config = config.with_project_dir("/home/user/project")

        assert new_config.project_dir == "/home/user/project"
        assert new_config is not config

    def test_immutability(self) -> None:
        """Test that configurations are immutable (methods return new instances)."""
        config = ProjectConfiguration(
            project="original-project",
            project_dir="/original/path",
        )

        # All with_* methods should return new instances
        new_config = config.with_project("new-project")
        assert new_config is not config

        new_config2 = config.with_project_dir("/new/path")
        assert new_config2 is not config
        assert new_config2 is not new_config

        # Original config should be unchanged
        assert config.project == "original-project"
        assert config.project_dir == "/original/path"

    def test_comprehensive_configuration(self) -> None:
        """Test comprehensive configuration setup."""
        config = ProjectConfiguration()

        # Chain multiple configuration updates
        new_config = config.with_project("my-app").with_project_dir("/workspace/my-app")

        assert new_config.project == "my-app"
        assert new_config.project_dir == "/workspace/my-app"

    def test_none_values(self) -> None:
        """Test configuration with None values."""
        config = ProjectConfiguration(
            project=None,
            project_dir=None,
        )

        assert config.project is None
        assert config.project_dir is None

    def test_empty_strings(self) -> None:
        """Test configuration with empty string values."""
        config = ProjectConfiguration(
            project="",
            project_dir="",
        )

        assert config.project == ""
        assert config.project_dir == ""

    def test_special_characters(self) -> None:
        """Test configuration with special characters in paths."""
        config = ProjectConfiguration(
            project="my-project_123",
            project_dir="/path/with spaces/and_special-chars!",
        )

        assert config.project == "my-project_123"
        assert config.project_dir == "/path/with spaces/and_special-chars!"

    def test_relative_paths(self) -> None:
        """Test configuration with relative paths."""
        config = ProjectConfiguration(
            project="test-app",
            project_dir="./relative/path",
        )

        assert config.project == "test-app"
        assert config.project_dir == "./relative/path"

    def test_windows_paths(self) -> None:
        """Test configuration with Windows-style paths."""
        config = ProjectConfiguration(
            project="windows-app",
            project_dir="C:\\Users\\test\\project",
        )

        assert config.project == "windows-app"
        assert config.project_dir == "C:\\Users\\test\\project"

    def test_unix_paths(self) -> None:
        """Test configuration with Unix-style paths."""
        config = ProjectConfiguration(
            project="unix-app",
            project_dir="/home/user/projects/my-app",
        )

        assert config.project == "unix-app"
        assert config.project_dir == "/home/user/projects/my-app"
