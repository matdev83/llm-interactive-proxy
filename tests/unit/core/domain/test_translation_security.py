from __future__ import annotations

import json

import pytest
from src.core.domain.chat import ImageURL, MessageContentPartImage
from src.core.domain.translation import Translation


@pytest.mark.parametrize(
    "url, expected_scheme",
    [
        (
            "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
            "data",
        ),
        ("http://example.com/image.png", "http"),
        ("https://example.com/image.png", "https"),
        ("file:///etc/passwd", "file"),
        ("ftp://example.com/image.png", "ftp"),
        ("C:\\Users\\user\\image.png", "file"),
    ],
)
def test_process_gemini_image_part_uri_scheme_validation(
    url: str, expected_scheme: str
) -> None:
    """
    Test that _process_gemini_image_part correctly validates URI schemes.
    """
    # Arrange
    part = MessageContentPartImage(
        type="image_url", image_url=ImageURL(url=url, detail="auto")
    )

    # Act
    result = Translation._process_gemini_image_part(part)

    # Assert
    if expected_scheme in ["data", "http", "https"]:
        assert result is not None
        if expected_scheme == "data":
            assert "inline_data" in result
        else:
            assert "file_data" in result
            assert result["file_data"]["file_uri"] == url
    else:
        assert result is None, f"URI with scheme '{expected_scheme}' should be rejected"


def test_extract_and_repair_json_adds_missing_required_fields() -> None:
    schema = {
        "type": "object",
        "required": ["foo", "bar"],
        "properties": {
            "foo": {"type": "string"},
            "bar": {"type": "integer"},
        },
    }
    content = 'prefix {"bar": 3} suffix'

    repaired = Translation._extract_and_repair_json(content, schema)

    assert repaired is not None
    parsed = json.loads(repaired)
    assert parsed["bar"] == 3
    assert parsed["foo"] == ""


def test_extract_and_repair_json_ignores_braces_in_strings() -> None:
    schema: dict[str, object] = {"type": "object"}
    content = 'ignore "{not json}" but keep {"valid": true}'

    repaired = Translation._extract_and_repair_json(content, schema)

    assert repaired is not None
    parsed = json.loads(repaired)
    assert parsed == {"valid": True}


def test_iter_json_candidates_handles_unbalanced_braces() -> None:
    payload = "{" * 128

    candidates = Translation._iter_json_candidates(payload, max_candidates=5)

    assert candidates == []
