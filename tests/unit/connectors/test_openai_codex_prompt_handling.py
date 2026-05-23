"""Tests for OpenAI Codex prompt handling and canonical instruction preservation."""

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest_asyncio
from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex import OpenAICodexConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.translation_service import TranslationService


@pytest_asyncio.fixture(name="auth_dir")
async def auth_dir_tmp(tmp_path: Path):
    """Create a temporary auth directory with valid credentials."""
    data = {"tokens": {"access_token": "test_token"}}
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "auth.json").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


@pytest_asyncio.fixture(name="codex_connector")
async def codex_connector_fixture(auth_dir: Path):
    """Create an OpenAI Codex connector for testing."""
    async with httpx.AsyncClient() as client:
        cfg = AppConfig()
        ts = TranslationService()
        backend = OpenAICodexConnector(client, cfg, translation_service=ts)

        with (
            patch.object(
                backend, "_validate_credentials_file_exists", return_value=(True, [])
            ),
            patch.object(
                backend, "_validate_credentials_structure", return_value=(True, [])
            ),
            patch.object(backend, "_start_file_watching"),
        ):
            await backend.initialize(openai_codex_path=str(auth_dir))
            backend._auth_credentials = {"tokens": {"access_token": "test_token"}}
            yield backend


class TestCanonicalInstructionPreservation:
    """Test that canonical Codex instructions are preserved byte-for-byte."""

    def test_canonical_prompt_loaded(self, codex_connector: OpenAICodexConnector):
        """Test that the canonical prompt is loaded correctly."""
        canonical_prompt = codex_connector._codex_system_prompt()
        assert canonical_prompt is not None
        assert len(canonical_prompt) > 0
        assert "You are Codex" in canonical_prompt

    def test_resolve_system_prompt_preserves_canonical_default_mode(
        self, codex_connector: OpenAICodexConnector
    ):
        """Test that _resolve_system_prompt preserves canonical instructions in codex_default mode."""
        canonical_prompt = codex_connector._codex_system_prompt()

        # Create a request with no custom instructions
        request = ChatRequest(
            model="gpt-5-codex",
            messages=[ChatMessage(role="user", content="test")],
        )

        capabilities = CodexClientCapabilities(prompt_mode="codex_default")
        resolved = codex_connector._resolve_system_prompt(
            request, capabilities, custom_instruction_sections=None
        )

        # Should return canonical prompt exactly
        assert resolved == canonical_prompt

    def test_resolve_system_prompt_preserves_canonical_merge_mode(
        self, codex_connector: OpenAICodexConnector
    ):
        """Test that canonical instructions are preserved when merging with custom instructions."""
        canonical_prompt = codex_connector._codex_system_prompt()

        request = ChatRequest(
            model="gpt-5-codex",
            messages=[
                ChatMessage(role="system", content="Custom instruction"),
                ChatMessage(role="user", content="test"),
            ],
        )

        capabilities = CodexClientCapabilities(prompt_mode="merge_custom")
        resolved = codex_connector._resolve_system_prompt(
            request, capabilities, custom_instruction_sections=None
        )

        # Should contain canonical prompt
        assert canonical_prompt in resolved
        # Custom instructions should NOT be in system prompt (they go to user blocks)
        # The resolved prompt should still be the canonical one
        assert resolved.startswith(canonical_prompt.split("\n\n")[0])

    def test_resolve_system_prompt_custom_only_fallback(
        self, codex_connector: OpenAICodexConnector
    ):
        """Test that custom_only mode falls back to canonical when no custom instructions."""
        canonical_prompt = codex_connector._codex_system_prompt()

        request = ChatRequest(
            model="gpt-5-codex",
            messages=[ChatMessage(role="user", content="test")],
        )

        capabilities = CodexClientCapabilities(prompt_mode="custom_only")
        resolved = codex_connector._resolve_system_prompt(
            request, capabilities, custom_instruction_sections=[]
        )

        # Should fall back to canonical prompt
        assert resolved == canonical_prompt


class TestClientPersonaInjection:
    """Test that client personas are injected as user-level blocks."""

    def test_render_user_instruction_block_creates_proper_format(
        self, codex_connector: OpenAICodexConnector
    ):
        """Test that user instruction blocks are formatted correctly."""
        sections = ["Custom persona 1", "Custom persona 2"]

        result = codex_connector._render_user_instruction_block(sections)

        assert result is not None
        assert result["type"] == "message"
        assert result["role"] == "user"
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "input_text"

        text = result["content"][0]["text"]
        assert text.startswith("<user_instructions>")
        assert text.endswith("</user_instructions>")
        assert "Custom persona 1" in text
        assert "Custom persona 2" in text

    def test_render_user_instruction_block_empty_sections(
        self, codex_connector: OpenAICodexConnector
    ):
        """Test that empty sections are handled correctly."""
        result = codex_connector._render_user_instruction_block([])
        assert result is None

        result = codex_connector._render_user_instruction_block(["", "  ", None])
        assert result is None

    def test_render_user_instruction_block_sanitizes_content(
        self, codex_connector: OpenAICodexConnector
    ):
        """Test that user instruction blocks sanitize non-ASCII characters."""
        sections = ["Custom with em-dash — and ellipsis…"]

        result = codex_connector._render_user_instruction_block(sections)

        assert result is not None
        text = result["content"][0]["text"]
        # Should have ASCII replacements
        assert "—" not in text  # em-dash should be replaced
        assert "…" not in text  # ellipsis should be replaced
        assert "--" in text or "-" in text  # em-dash replacement
        assert "..." in text  # ellipsis replacement


class TestASCIISanitization:
    """Test ASCII sanitization of instructions."""

    def test_sanitize_codex_instructions_preserves_ascii(
        self, codex_connector: OpenAICodexConnector
    ):
        """Test that ASCII characters are preserved."""
        text = "Hello world! This is a test with numbers 123 and symbols @#$%"
        result = codex_connector._sanitize_codex_instructions(text)
        assert result == text

    def test_sanitize_codex_instructions_replaces_unicode_dashes(
        self, codex_connector: OpenAICodexConnector
    ):
        """Test that Unicode dashes are replaced with ASCII equivalents."""
        test_cases = [
            ("\u2010", "-"),  # hyphen
            ("\u2011", "-"),  # non-breaking hyphen
            ("\u2012", "-"),  # figure dash
            ("\u2013", "-"),  # en dash
            ("\u2014", "--"),  # em dash
            ("\u2015", "--"),  # horizontal bar
        ]

        for unicode_char, expected in test_cases:
            text = f"Test{unicode_char}text"
            result = codex_connector._sanitize_codex_instructions(text)
            assert unicode_char not in result
            assert expected in result

    def test_sanitize_codex_instructions_replaces_ellipsis(
        self, codex_connector: OpenAICodexConnector
    ):
        """Test that Unicode ellipsis is replaced with ASCII equivalent."""
        text = "Wait\u2026"
        result = codex_connector._sanitize_codex_instructions(text)
        assert "\u2026" not in result
        assert "..." in result

    def test_sanitize_codex_instructions_replaces_arrow(
        self, codex_connector: OpenAICodexConnector
    ):
        """Test that Unicode arrow is replaced with ASCII equivalent."""
        text = "A \u2192 B"
        result = codex_connector._sanitize_codex_instructions(text)
        assert "\u2192" not in result
        assert "->" in result

    def test_sanitize_codex_instructions_removes_unmapped_unicode(
        self, codex_connector: OpenAICodexConnector
    ):
        """Test that unmapped Unicode characters are removed."""
        text = "Test with emoji 😊 and other unicode ñ"
        result = codex_connector._sanitize_codex_instructions(text)
        assert "😊" not in result
        assert "ñ" not in result
        assert "Test with emoji" in result
        assert "and other unicode" in result

    def test_sanitize_codex_instructions_complex_text(
        self, codex_connector: OpenAICodexConnector
    ):
        """Test sanitization of complex text with multiple Unicode characters."""
        text = "Here's a test—with em-dash, ellipsis…, arrow → and emoji 😊!"
        result = codex_connector._sanitize_codex_instructions(text)

        # All non-ASCII should be replaced or removed
        assert all(ord(c) < 128 for c in result)
        # Should contain ASCII replacements
        assert "--" in result  # em-dash
        assert "..." in result  # ellipsis
        assert "->" in result  # arrow


class TestCustomInstructionExtraction:
    """Test extraction of custom instruction sections from requests."""

    def test_extract_from_system_prompt_field(
        self, codex_connector: OpenAICodexConnector
    ):
        """Test extraction from request.system_prompt field."""
        request = ChatRequest(
            model="gpt-5-codex",
            messages=[ChatMessage(role="user", content="test")],
            system_prompt="Custom system prompt",
        )

        sections = codex_connector._extract_custom_instruction_sections(request)
        assert "Custom system prompt" in sections

    def test_extract_from_system_messages(self, codex_connector: OpenAICodexConnector):
        """Test extraction from system role messages."""
        request = ChatRequest(
            model="gpt-5-codex",
            messages=[
                ChatMessage(role="system", content="System message 1"),
                ChatMessage(role="user", content="test"),
                ChatMessage(role="system", content="System message 2"),
            ],
        )

        sections = codex_connector._extract_custom_instruction_sections(request)
        assert "System message 1" in sections
        assert "System message 2" in sections

    def test_extract_from_extra_body(self, codex_connector: OpenAICodexConnector):
        """Test extraction from extra_body.codex_system_prompt."""
        request = ChatRequest(
            model="gpt-5-codex",
            messages=[ChatMessage(role="user", content="test")],
            extra_body={"codex_system_prompt": "Extra body prompt"},
        )

        sections = codex_connector._extract_custom_instruction_sections(request)
        assert "Extra body prompt" in sections

    def test_extract_from_extra_body_list(self, codex_connector: OpenAICodexConnector):
        """Test extraction from extra_body.codex_system_prompt as list."""
        request = ChatRequest(
            model="gpt-5-codex",
            messages=[ChatMessage(role="user", content="test")],
            extra_body={"codex_system_prompt": ["Prompt 1", "Prompt 2"]},
        )

        sections = codex_connector._extract_custom_instruction_sections(request)
        assert "Prompt 1" in sections
        assert "Prompt 2" in sections

    def test_extract_deduplicates_sections(self, codex_connector: OpenAICodexConnector):
        """Test that duplicate sections are removed."""
        request = ChatRequest(
            model="gpt-5-codex",
            messages=[
                ChatMessage(role="system", content="Duplicate prompt"),
                ChatMessage(role="user", content="test"),
                ChatMessage(role="system", content="Duplicate prompt"),
            ],
            system_prompt="Duplicate prompt",
        )

        sections = codex_connector._extract_custom_instruction_sections(request)
        # Should only appear once
        assert sections.count("Duplicate prompt") == 1

    def test_extract_ignores_empty_sections(
        self, codex_connector: OpenAICodexConnector
    ):
        """Test that empty sections are ignored."""
        request = ChatRequest(
            model="gpt-5-codex",
            messages=[
                ChatMessage(role="system", content=""),
                ChatMessage(role="user", content="test"),
                ChatMessage(role="system", content="  "),
            ],
            system_prompt="  ",
        )

        sections = codex_connector._extract_custom_instruction_sections(request)
        assert len(sections) == 0

    def test_extract_all_sources_combined(self, codex_connector: OpenAICodexConnector):
        """Test extraction from all sources combined."""
        request = ChatRequest(
            model="gpt-5-codex",
            messages=[
                ChatMessage(role="system", content="From message"),
                ChatMessage(role="user", content="test"),
            ],
            system_prompt="From system_prompt",
            extra_body={"codex_system_prompt": "From extra_body"},
        )

        sections = codex_connector._extract_custom_instruction_sections(request)
        assert "From system_prompt" in sections
        assert "From message" in sections
        assert "From extra_body" in sections
        assert len(sections) == 3
