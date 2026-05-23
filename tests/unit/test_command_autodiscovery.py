"""
Tests for command auto-discovery mechanism.

These tests verify that commands are automatically discovered and registered
without requiring hardcoded imports.
"""

from pathlib import Path

import pytest
from src.core.domain.commands.command_registry import DomainCommandRegistry


class TestCommandAutoDiscovery:
    """Test suite for command auto-discovery functionality."""

    def test_all_commands_auto_registered(self):
        """Test that all domain command modules are automatically discovered and registered."""
        # Import commands to ensure auto-discovery has happened
        import src.core.domain.commands  # noqa: F401
        from src.core.domain.commands.command_registry import domain_command_registry

        # Get all registered commands
        registered = domain_command_registry.get_registered_commands()

        # Verify we have commands registered
        assert len(registered) > 0, "No commands were auto-discovered"

        # Expected failover commands (these should always be present)
        expected_commands = [
            "create-failover-route",
            "delete-failover-route",
            "list-failover-routes",
            "route-append",
            "route-clear",
            "route-list",
            "route-prepend",
        ]

        # Check that all expected commands are registered
        for command_name in expected_commands:
            assert command_name in registered, (
                f"Command '{command_name}' was not auto-discovered. "
                f"Registered commands: {registered}"
            )

        # Verify no duplicates
        assert len(registered) == len(
            set(registered)
        ), "Duplicate commands detected in registry"

    def test_command_modules_discovered_without_hardcoded_imports(self):
        """Test that command modules are discovered dynamically, not from hardcoded list."""
        # Read the commands __init__.py file
        commands_init = Path("src/core/domain/commands/__init__.py")
        content = commands_init.read_text()

        # Verify it uses pkgutil.iter_modules for discovery
        assert (
            "pkgutil.iter_modules" in content
        ), "Command discovery should use pkgutil.iter_modules for auto-discovery"

        # Verify it doesn't have hardcoded command imports (except base classes)
        # Check that we're not importing specific commands by name
        forbidden_patterns = [
            "from .failover_commands import CreateFailoverRouteCommand",
            "from .failover_commands import DeleteFailoverRouteCommand",
            "from .model_command import",
            "from .temperature_command import",
        ]

        for pattern in forbidden_patterns:
            assert pattern not in content, (
                f"Found hardcoded import '{pattern}' in commands __init__.py. "
                "Commands should be auto-discovered, not hardcoded."
            )

    def test_new_command_would_be_auto_discovered(self):
        """Test that command files with registration calls are discovered."""
        # Import commands to ensure auto-discovery has happened
        import src.core.domain.commands  # noqa: F401
        from src.core.domain.commands.command_registry import domain_command_registry

        commands_path = Path("src/core/domain/commands")

        # Get all Python files that have registration calls
        skip_files = (
            "__init__",
            "base_command",
            "secure_base_command",
            "command_registry",
        )
        files_with_registration = []
        for f in commands_path.glob("*.py"):
            if f.stem not in skip_files and not f.stem.startswith("_"):
                content = f.read_text()
                if "domain_command_registry.register_command" in content:
                    files_with_registration.append(f.stem)

        # At minimum, failover_commands.py should have registrations
        assert (
            "failover_commands" in files_with_registration
        ), "failover_commands.py should have registration calls"

        # Verify that files with registration calls resulted in registered commands
        registered = domain_command_registry.get_registered_commands()
        assert (
            len(registered) > 0
        ), "No commands registered despite having registration calls in files"

    def test_base_modules_not_auto_imported(self):
        """Test that base.py and other utility modules are not auto-imported."""
        # Import commands to ensure auto-discovery has happened
        import src.core.domain.commands  # noqa: F401
        from src.core.domain.commands.command_registry import domain_command_registry

        # base modules should not register any commands with these names
        registered = domain_command_registry.get_registered_commands()
        assert "base" not in registered, "base.py should not register a command"
        assert (
            "base_command" not in registered
        ), "base_command.py should not register a command"
        assert (
            "secure_base_command" not in registered
        ), "secure_base_command.py should not register a command"

    def test_failed_command_import_doesnt_break_others(self):
        """Test that if one command fails to import, others still load."""
        # This is more of a documentation test showing the resilient behavior
        # The actual implementation logs warnings but continues

        commands_init = Path("src/core/domain/commands/__init__.py")
        content = commands_init.read_text()

        # Verify we have exception handling
        assert (
            "except Exception" in content
        ), "Auto-discovery should handle import failures gracefully"
        assert "logger.warning" in content, "Failed imports should be logged"

    def test_domain_command_registry_singleton_pattern(self):
        """Test that domain_command_registry is a singleton."""
        from src.core.domain.commands.command_registry import (
            domain_command_registry as reg1,
        )
        from src.core.domain.commands.command_registry import (
            domain_command_registry as reg2,
        )

        # Should be the same instance
        assert reg1 is reg2, "domain_command_registry should be a singleton"


class TestDomainCommandRegistryInterface:
    """Test the DomainCommandRegistry class interface."""

    def test_register_command_basic(self):
        """Test basic command registration."""
        registry = DomainCommandRegistry()

        def mock_factory():
            pass

        registry.register_command("test-command", mock_factory)

        assert "test-command" in registry.get_registered_commands()
        assert registry.get_command_factory("test-command") == mock_factory

    def test_register_command_duplicate_raises_error(self):
        """Test that registering duplicate command raises error."""
        registry = DomainCommandRegistry()

        def mock_factory():
            pass

        registry.register_command("test-command", mock_factory)

        with pytest.raises(ValueError, match="already registered"):
            registry.register_command("test-command", mock_factory)

    def test_get_nonexistent_command_raises_error(self):
        """Test that getting non-existent command raises error."""
        registry = DomainCommandRegistry()

        with pytest.raises(ValueError, match="not registered"):
            registry.get_command_factory("nonexistent-command")

    def test_register_command_invalid_name_raises_error(self):
        """Test that invalid command name raises error."""
        registry = DomainCommandRegistry()

        def mock_factory():
            pass

        with pytest.raises(ValueError, match="non-empty string"):
            registry.register_command("", mock_factory)

        with pytest.raises(ValueError, match="non-empty string"):
            registry.register_command(None, mock_factory)  # type: ignore

    def test_register_command_invalid_factory_raises_error(self):
        """Test that invalid factory raises error."""
        registry = DomainCommandRegistry()

        with pytest.raises(TypeError, match="must be a callable"):
            registry.register_command("test-command", "not-a-callable")  # type: ignore

    def test_has_command(self):
        """Test the has_command method."""
        registry = DomainCommandRegistry()

        def mock_factory():
            pass

        assert not registry.has_command("test-command")

        registry.register_command("test-command", mock_factory)

        assert registry.has_command("test-command")
        assert not registry.has_command("other-command")
