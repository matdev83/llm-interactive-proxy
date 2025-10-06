from __future__ import annotations

from src.connectors.gemini import GeminiBackend


def test_coerce_stream_chunk_accepts_bytes_payload() -> None:
    chunk = (
        b"data: {\"candidates\":[{\"content\":{\"parts\":[{\"text\":\"hi\"}]}}]}\n\n"
    )

    result = GeminiBackend._coerce_stream_chunk(chunk)

    assert result == {
        "candidates": [
            {"content": {"parts": [{"text": "hi"}]}}
        ]
    }
