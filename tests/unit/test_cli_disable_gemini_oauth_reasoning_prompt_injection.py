"""Tests for --disable-gemini-oauth-reasoning-prompt-injection CLI parameter."""

import os

import pytest
from src.core.cli import apply_cli_args, parse_cli_args


class TestDisableGeminiOAuthReasoningPromptInjection:
    """Test the --disable-gemini-oauth-reasoning-prompt-injection CLI parameter."""

    def test_cli_flag_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that --disable-gemini-oauth-reasoning-prompt-injection sets the flag to True."""
        monkeypatch.delenv("COMMAND_PREFIX", raising=False)
        monkeypatch.delenv(
            "DISABLE_GEMINI_OAUTH_REASONING_PROMPT_INJECTION", raising=False
        )
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        for i in range(1, 21):
            monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)

        args = parse_cli_args(["--disable-gemini-oauth-reasoning-prompt-injection"])
        cfg = apply_cli_args(args)
        if isinstance(cfg, tuple):
            cfg = cfg[0]

        assert cfg.backends.disable_gemini_oauth_reasoning_prompt_injection is True
        assert os.environ["DISABLE_GEMINI_OAUTH_REASONING_PROMPT_INJECTION"] == "1"

        monkeypatch.delenv(
            "DISABLE_GEMINI_OAUTH_REASONING_PROMPT_INJECTION", raising=False
        )

    def test_cli_flag_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that without the flag, it defaults to False."""
        monkeypatch.delenv("COMMAND_PREFIX", raising=False)
        monkeypatch.delenv(
            "DISABLE_GEMINI_OAUTH_REASONING_PROMPT_INJECTION", raising=False
        )
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        for i in range(1, 21):
            monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)

        args = parse_cli_args([])
        cfg = apply_cli_args(args)
        if isinstance(cfg, tuple):
            cfg = cfg[0]

        assert cfg.backends.disable_gemini_oauth_reasoning_prompt_injection is False

        monkeypatch.delenv(
            "DISABLE_GEMINI_OAUTH_REASONING_PROMPT_INJECTION", raising=False
        )

    def test_env_var_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that DISABLE_GEMINI_OAUTH_REASONING_PROMPT_INJECTION=1 sets the flag."""
        monkeypatch.delenv("COMMAND_PREFIX", raising=False)
        monkeypatch.setenv("DISABLE_GEMINI_OAUTH_REASONING_PROMPT_INJECTION", "1")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        for i in range(1, 21):
            monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)

        args = parse_cli_args([])
        cfg = apply_cli_args(args)
        if isinstance(cfg, tuple):
            cfg = cfg[0]

        assert cfg.backends.disable_gemini_oauth_reasoning_prompt_injection is True

        monkeypatch.delenv(
            "DISABLE_GEMINI_OAUTH_REASONING_PROMPT_INJECTION", raising=False
        )

    def test_env_var_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that DISABLE_GEMINI_OAUTH_REASONING_PROMPT_INJECTION=0 keeps it False."""
        monkeypatch.delenv("COMMAND_PREFIX", raising=False)
        monkeypatch.setenv("DISABLE_GEMINI_OAUTH_REASONING_PROMPT_INJECTION", "0")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        for i in range(1, 21):
            monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)

        args = parse_cli_args([])
        cfg = apply_cli_args(args)
        if isinstance(cfg, tuple):
            cfg = cfg[0]

        assert cfg.backends.disable_gemini_oauth_reasoning_prompt_injection is False

        monkeypatch.delenv(
            "DISABLE_GEMINI_OAUTH_REASONING_PROMPT_INJECTION", raising=False
        )
