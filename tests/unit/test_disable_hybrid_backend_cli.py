"""Tests for disable_hybrid_backend CLI argument."""

import argparse

from src.core.cli import build_cli_parser


class TestDisableHybridBackendCLI:
    """Test suite for --disable-hybrid-backend CLI argument."""

    def test_cli_parser_has_disable_hybrid_backend_argument(self) -> None:
        """Test that CLI parser has --disable-hybrid-backend argument."""
        parser = build_cli_parser()

        # Parse with the flag
        args = parser.parse_args(["--disable-hybrid-backend"])
        assert hasattr(args, "disable_hybrid_backend")
        assert args.disable_hybrid_backend is True

    def test_cli_parser_disable_hybrid_backend_defaults_to_false(self) -> None:
        """Test that --disable-hybrid-backend defaults to False when not provided."""
        parser = build_cli_parser()

        # Parse without the flag
        args = parser.parse_args([])
        assert hasattr(args, "disable_hybrid_backend")
        assert args.disable_hybrid_backend is False

    def test_cli_parser_disable_hybrid_backend_is_action_store_true(self) -> None:
        """Test that --disable-hybrid-backend is a boolean flag (action='store_true')."""
        parser = build_cli_parser()

        # Find the action for --disable-hybrid-backend
        action = None
        for act in parser._actions:
            if "--disable-hybrid-backend" in act.option_strings:
                action = act
                break

        assert action is not None, "--disable-hybrid-backend argument not found"
        assert isinstance(action, argparse._StoreTrueAction)

    def test_cli_help_includes_disable_hybrid_backend(self) -> None:
        """Test that CLI help text includes --disable-hybrid-backend."""
        parser = build_cli_parser()
        help_text = parser.format_help()

        assert "--disable-hybrid-backend" in help_text
        assert "Disable the hybrid backend" in help_text
