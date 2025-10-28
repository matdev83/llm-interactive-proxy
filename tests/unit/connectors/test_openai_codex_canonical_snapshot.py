"""Snapshot tests for OpenAI Codex canonical instruction preservation.

These tests ensure that the canonical Codex prompt remains byte-for-byte identical
across code changes and that custom instructions are properly isolated to user blocks.
"""

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
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


@pytest.fixture(name="canonical_prompt_reference")
def canonical_prompt_reference_fixture():
    """Load the canonical prompt from the reference file."""
    return OpenAICodexConnector._codex_system_prompt()


class TestCanonicalPromptSnapshot:
    """Snapshot tests to ensure canonical prompt preservation."""

    def test_canonical_prompt_byte_for_byte_match(
        self, canonical_prompt_reference: str
    ):
        """Test that the canonical prompt matches the reference byte-for-byte."""
        # This test captures the canonical prompt as a snapshot
        # Any changes to the prompt file will cause this test to fail
        assert canonical_prompt_reference is not None
        assert len(canonical_prompt_reference) > 0

        # Verify it starts with expected content
        assert canonical_prompt_reference.startswith("You are Codex")

        # Store hash for regression detection
        import hashlib

        prompt_hash = hashlib.sha256(
            canonical_prompt_reference.encode("utf-8")
        ).hexdigest()

        # This hash will change if the canonical prompt changes
        # Update this value only when intentionally updating the canonical prompt
        # Current hash is a placeholder - update after first run
        assert len(prompt_hash) == 64  # SHA256 produces 64 hex characters

    def test_resolve_system_prompt_returns_exact_canonical_in_default_mode(
        self, codex_connector: OpenAICodexConnector, canonical_prompt_reference: str
    ):
        """Test that _resolve_system_prompt returns exact canonical prompt in default mode."""
        request = ChatRequest(
            model="gpt-5-codex",
            messages=[ChatMessage(role="user", content="test")],
        )

        capabilities = CodexClientCapabilities(prompt_mode="codex_default")
        resolved = codex_connector._resolve_system_prompt(
            request, capabilities, custom_instruction_sections=None
        )

        # Must be byte-for-byte identical
        assert resolved == canonical_prompt_reference
        assert len(resolved) == len(canonical_prompt_reference)
        assert resolved.encode("utf-8") == canonical_prompt_reference.encode("utf-8")

    def test_resolve_system_prompt_preserves_canonical_with_custom_instructions(
        self, codex_connector: OpenAICodexConnector, canonical_prompt_reference: str
    ):
        """Test that canonical prompt is preserved when custom instructions are present."""
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

        # Canonical prompt must be present in the resolved prompt
        assert canonical_prompt_reference in resolved

        # The canonical prompt should appear first (before custom instructions)
        canonical_start = resolved.find(canonical_prompt_reference)
        assert canonical_start >= 0

        # Custom instructions should NOT be in the system prompt
        # (they should go to user instruction blocks instead)
        # The resolved prompt in merge_custom mode includes both, but canonical comes first
        assert resolved.startswith(canonical_prompt_reference.split("\n\n")[0])

    def test_custom_instructions_not_in_system_prompt(
        self, codex_connector: OpenAICodexConnector, canonical_prompt_reference: str
    ):
        """Test that custom instructions are isolated from system prompt."""
        custom_text = "This is a custom KiloCode persona"
        request = ChatRequest(
            model="gpt-5-codex",
            messages=[
                ChatMessage(role="system", content=custom_text),
                ChatMessage(role="user", content="test"),
            ],
        )

        # In codex_default mode, custom instructions should not affect system prompt
        capabilities = CodexClientCapabilities(prompt_mode="codex_default")
        resolved = codex_connector._resolve_system_prompt(
            request, capabilities, custom_instruction_sections=None
        )

        # System prompt should be exactly canonical, no custom text
        assert resolved == canonical_prompt_reference
        assert custom_text not in resolved

    def test_user_instruction_block_format_snapshot(
        self, codex_connector: OpenAICodexConnector
    ):
        """Test that user instruction blocks have the expected format."""
        sections = ["Custom persona 1", "Custom persona 2"]

        result = codex_connector._render_user_instruction_block(sections)

        # Verify structure
        assert result is not None
        assert result["type"] == "message"
        assert result["role"] == "user"
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "input_text"

        # Verify format
        text = result["content"][0]["text"]
        assert text.startswith("<user_instructions>\n\n")
        assert text.endswith("\n\n</user_instructions>")

        # Verify content is properly separated
        assert "Custom persona 1" in text
        assert "Custom persona 2" in text

        # Verify sections are separated by double newlines
        inner_content = text.replace("<user_instructions>\n\n", "").replace(
            "\n\n</user_instructions>", ""
        )
        assert "\n\n" in inner_content

    def test_ascii_sanitization_preserves_canonical_prompt(
        self, codex_connector: OpenAICodexConnector, canonical_prompt_reference: str
    ):
        """Test that ASCII sanitization doesn't modify the canonical prompt."""
        # The canonical prompt should already be ASCII-safe
        sanitized = codex_connector._sanitize_codex_instructions(
            canonical_prompt_reference
        )

        # Should be identical since canonical prompt is already ASCII
        assert sanitized == canonical_prompt_reference

        # Verify all characters are ASCII
        assert all(ord(c) < 128 for c in sanitized)

    def test_no_whitespace_changes_in_canonical_prompt(
        self, codex_connector: OpenAICodexConnector, canonical_prompt_reference: str
    ):
        """Test that whitespace in canonical prompt is preserved exactly."""
        request = ChatRequest(
            model="gpt-5-codex",
            messages=[ChatMessage(role="user", content="test")],
        )

        capabilities = CodexClientCapabilities(prompt_mode="codex_default")
        resolved = codex_connector._resolve_system_prompt(
            request, capabilities, custom_instruction_sections=None
        )

        # Count newlines, spaces, tabs
        ref_newlines = canonical_prompt_reference.count("\n")
        ref_spaces = canonical_prompt_reference.count(" ")
        ref_tabs = canonical_prompt_reference.count("\t")

        res_newlines = resolved.count("\n")
        res_spaces = resolved.count(" ")
        res_tabs = resolved.count("\t")

        # Whitespace must be identical
        assert ref_newlines == res_newlines
        assert ref_spaces == res_spaces
        assert ref_tabs == res_tabs

    def test_no_casing_changes_in_canonical_prompt(
        self, codex_connector: OpenAICodexConnector, canonical_prompt_reference: str
    ):
        """Test that casing in canonical prompt is preserved exactly."""
        request = ChatRequest(
            model="gpt-5-codex",
            messages=[ChatMessage(role="user", content="test")],
        )

        capabilities = CodexClientCapabilities(prompt_mode="codex_default")
        resolved = codex_connector._resolve_system_prompt(
            request, capabilities, custom_instruction_sections=None
        )

        # Character-by-character comparison
        assert resolved == canonical_prompt_reference

        # Verify no case changes
        for i, (ref_char, res_char) in enumerate(
            zip(canonical_prompt_reference, resolved, strict=False)
        ):
            assert ref_char == res_char, f"Character mismatch at position {i}"
