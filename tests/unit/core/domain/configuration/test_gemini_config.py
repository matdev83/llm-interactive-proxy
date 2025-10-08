"""Tests for the Gemini generation configuration helpers."""

from src.core.domain.configuration.gemini_config import GeminiGenerationConfig


def test_with_generation_config_supports_camel_case_keys() -> None:
    """Ensure camelCase generation config keys are parsed correctly."""

    config = GeminiGenerationConfig()

    updated = config.with_generation_config(
        {
            "temperature": 0.4,
            "topP": 0.7,
            "topK": 32,
            "maxOutputTokens": 1024,
            "candidateCount": 2,
            "stopSequences": ["STOP"],
        }
    )

    assert updated.temperature == 0.4
    assert updated.top_p == 0.7
    assert updated.top_k == 32
    assert updated.max_output_tokens == 1024
    assert updated.candidate_count == 2
    assert updated.stop_sequences == ["STOP"]


def test_with_generation_config_keeps_snake_case_support() -> None:
    """Verify snake_case keys continue to work for backwards compatibility."""

    config = GeminiGenerationConfig()

    updated = config.with_generation_config(
        {
            "top_p": 0.55,
            "top_k": 16,
        }
    )

    assert updated.top_p == 0.55
    assert updated.top_k == 16
