"""Tests for --disable-gemini-oauth-fallback CLI parameter."""

import os

import pytest
from src.core.cli import apply_cli_args, parse_cli_args


class TestDisableGeminiOAuthFallback:
    """Test the --disable-gemini-oauth-fallback CLI parameter."""

    def test_cli_disable_gemini_oauth_fallback_flag_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that --disable-gemini-oauth-fallback sets the flag to True."""
        # Clean environment
        monkeypatch.delenv("COMMAND_PREFIX", raising=False)
        monkeypatch.delenv("DISABLE_GEMINI_OAUTH_FALLBACK", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        for i in range(1, 21):
            monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)

        # Parse CLI args with the flag
        args = parse_cli_args(["--disable-gemini-oauth-fallback"])
        cfg = apply_cli_args(args)
        if isinstance(cfg, tuple):
            cfg = cfg[0]

        # Verify the flag is set correctly
        assert cfg.backends.disable_gemini_oauth_fallback is True

        # Verify environment variable was set
        assert os.environ["DISABLE_GEMINI_OAUTH_FALLBACK"] == "1"

        # Cleanup
        monkeypatch.delenv("DISABLE_GEMINI_OAUTH_FALLBACK", raising=False)

    def test_cli_disable_gemini_oauth_fallback_flag_not_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that without --disable-gemini-oauth-fallback, the flag defaults to False."""
        # Clean environment
        monkeypatch.delenv("COMMAND_PREFIX", raising=False)
        monkeypatch.delenv("DISABLE_GEMINI_OAUTH_FALLBACK", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        for i in range(1, 21):
            monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)

        # Parse CLI args without the flag
        args = parse_cli_args([])
        cfg = apply_cli_args(args)
        if isinstance(cfg, tuple):
            cfg = cfg[0]

        # Verify the flag defaults to False
        assert cfg.backends.disable_gemini_oauth_fallback is False

        # Cleanup
        monkeypatch.delenv("DISABLE_GEMINI_OAUTH_FALLBACK", raising=False)

    def test_env_var_disable_gemini_oauth_fallback_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that DISABLE_GEMINI_OAUTH_FALLBACK=1 sets the flag to True."""
        # Set environment variable
        monkeypatch.delenv("COMMAND_PREFIX", raising=False)
        monkeypatch.setenv("DISABLE_GEMINI_OAUTH_FALLBACK", "1")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        for i in range(1, 21):
            monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)

        # Parse CLI args without the flag (env var should take effect)
        args = parse_cli_args([])
        cfg = apply_cli_args(args)
        if isinstance(cfg, tuple):
            cfg = cfg[0]

        # Verify the flag is set from environment
        assert cfg.backends.disable_gemini_oauth_fallback is True

        # Cleanup
        monkeypatch.delenv("DISABLE_GEMINI_OAUTH_FALLBACK", raising=False)

    def test_env_var_disable_gemini_oauth_fallback_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that DISABLE_GEMINI_OAUTH_FALLBACK=0 sets the flag to False."""
        # Set environment variable
        monkeypatch.delenv("COMMAND_PREFIX", raising=False)
        monkeypatch.setenv("DISABLE_GEMINI_OAUTH_FALLBACK", "0")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        for i in range(1, 21):
            monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)

        # Parse CLI args without the flag
        args = parse_cli_args([])
        cfg = apply_cli_args(args)
        if isinstance(cfg, tuple):
            cfg = cfg[0]

        # Verify the flag is False from environment
        assert cfg.backends.disable_gemini_oauth_fallback is False

        # Cleanup
        monkeypatch.delenv("DISABLE_GEMINI_OAUTH_FALLBACK", raising=False)

    def test_cli_overrides_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that CLI flag overrides environment variable."""
        # Set environment variable to False
        monkeypatch.delenv("COMMAND_PREFIX", raising=False)
        monkeypatch.setenv("DISABLE_GEMINI_OAUTH_FALLBACK", "0")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        for i in range(1, 21):
            monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)

        # Parse CLI args with the flag (should override env)
        args = parse_cli_args(["--disable-gemini-oauth-fallback"])
        cfg = apply_cli_args(args)
        if isinstance(cfg, tuple):
            cfg = cfg[0]

        # Verify CLI takes precedence
        assert cfg.backends.disable_gemini_oauth_fallback is True

        # Cleanup
        monkeypatch.delenv("DISABLE_GEMINI_OAUTH_FALLBACK", raising=False)
