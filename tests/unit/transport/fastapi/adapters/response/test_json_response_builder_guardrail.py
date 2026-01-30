from __future__ import annotations

from src.core.domain.responses import ResponseEnvelope
from src.core.transport.fastapi.adapters.response.json_response_builder import (
    JSONResponseBuilder,
)


def _get_json(response):
    # FastAPI JSONResponse exposes body as bytes
    return response.body.decode("utf-8")


def test_json_response_builder_injects_assistant_message_when_choices_missing() -> None:
    builder = JSONResponseBuilder()

    envelope = ResponseEnvelope(
        content={"object": "chat.completion", "id": "x", "model": "m"},
        status_code=200,
        headers={},
        usage=None,
    )

    resp = builder.build(envelope)
    body = resp.body
    assert body is not None

    import json

    payload = json.loads(resp.body)

    assert payload["object"] == "chat.completion"
    assert isinstance(payload.get("choices"), list)
    assert payload["choices"][0]["message"]["role"] == "assistant"
    assert isinstance(payload["choices"][0]["message"]["content"], str)


def test_json_response_builder_coerces_none_content_to_empty_string() -> None:
    builder = JSONResponseBuilder()

    envelope = ResponseEnvelope(
        content={
            "object": "chat.completion",
            "id": "x",
            "model": "m",
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": None}}
            ],
        },
        status_code=200,
        headers={},
        usage=None,
    )

    resp = builder.build(envelope)

    import json

    payload = json.loads(resp.body)
    msg = payload["choices"][0]["message"]
    assert msg["role"] == "assistant"
    assert msg["content"] == ""
    assert isinstance(msg["content"], str)
