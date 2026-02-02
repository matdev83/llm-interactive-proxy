from __future__ import annotations

from src.connectors.gemini_oauth_auto.verification_url_extractor import (
    extract_first_url,
)


def test_extract_first_url_none() -> None:
    assert extract_first_url(None) is None
    assert extract_first_url("") is None


def test_extract_first_url_simple() -> None:
    text = "To continue, verify your account at https://accounts.google.com/signin/continue?sarp=1"
    assert extract_first_url(text) == "https://accounts.google.com/signin/continue?sarp=1"


def test_extract_first_url_multiline() -> None:
    text = "To continue, verify your account at\n\nhttps://accounts.google.com/signin/continue?sarp=1&flowName=GlifWebSignIn"
    assert extract_first_url(text) == "https://accounts.google.com/signin/continue?sarp=1&flowName=GlifWebSignIn"
