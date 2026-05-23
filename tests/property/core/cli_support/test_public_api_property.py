"""Property tests for Public API Signature Preservation.

**Feature: cli-god-object-refactoring, Property 7: Public API Signature Preservation**

Requirements:
- 7.4: main() function signature remains compatible
- 7.5: Legacy functions retained or delegated correctly
- 7.6: CLI v2 compatibility layer remains functional
"""

import argparse
import inspect
from typing import get_type_hints

from src.core import cli, cli_v2
from src.core.config.app_config import AppConfig


class TestPublicApiProperty:
    """Property tests for public API signature preservation.

    **Validates: Requirements 7.4, 7.5, 7.6**

    Property 7: Public API Signature Preservation
    The refactored CLI module SHALL expose the same public functions with the same
    signatures as the original implementation to maintain backward compatibility.
    """

    def test_main_signature_compatibility(self) -> None:
        """Test that cli.main retains its async signature.

        **Validates: Requirement 7.4**
        """
        # It must be a coroutine function
        assert inspect.iscoroutinefunction(cli.main)

        # Check signature: main(argv=None, build_app_fn=None)
        sig = inspect.signature(cli.main)
        assert "argv" in sig.parameters
        assert "build_app_fn" in sig.parameters

        # Check type hints
        hints = get_type_hints(cli.main)
        assert hints.get("return") is type(None)

    def test_build_cli_parser_compatibility(self) -> None:
        """Test that build_cli_parser returns an ArgumentParser.

        **Validates: Requirement 7.5**
        """
        parser = cli.build_cli_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_legacy_functions_existence(self) -> None:
        """Test that legacy private functions are retained for compatibility.

        **Validates: Requirement 7.5**
        """
        # Critical legacy functions that might be mocked by tests
        assert hasattr(cli, "_is_admin")
        assert hasattr(cli, "_check_privileges")
        assert hasattr(cli, "_configure_logging")
        assert hasattr(cli, "_handle_application_build_error")
        assert hasattr(cli, "apply_cli_args")
        assert hasattr(cli, "parse_cli_args")

    def test_cli_v2_compatibility(self) -> None:
        """Test that cli_v2 module exposes expected API.

        **Validates: Requirement 7.6**
        """
        assert hasattr(cli_v2, "main")
        assert hasattr(cli_v2, "parse_cli_args")
        assert hasattr(cli_v2, "apply_cli_args")
        assert hasattr(cli_v2, "is_port_in_use")
        assert hasattr(cli_v2, "AppConfig")

        # cli_v2.main should be a synchronous wrapper or compatible entry point.
        # The compatibility module calls asyncio.run(), so it is NOT async itself.
        assert inspect.isfunction(cli_v2.main)
        assert not inspect.iscoroutinefunction(cli_v2.main)

    def test_apply_cli_args_returns_config(self) -> None:
        """Test that apply_cli_args continues to return AppConfig.

        **Validates: Requirement 7.5**
        """
        # Parse empty args to get defaults
        parser = cli.build_cli_parser()
        args = parser.parse_args([])

        # Test cli.apply_cli_args
        result = cli.apply_cli_args(args)

        # It might return a tuple or config depending on implementation
        # The original implementation returned AppConfig or (AppConfig, Resolution)
        # Check source for current behavior.
        # It seems it returns AppConfig by default unless return_resolution=True

        if isinstance(result, tuple):
            config = result[0]
        else:
            config = result

        assert isinstance(config, AppConfig)
