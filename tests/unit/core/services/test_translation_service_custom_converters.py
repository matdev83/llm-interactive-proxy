from __future__ import annotations

from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalChatResponse,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatMessage,
)
from src.core.services.translation_service import TranslationService


def test_register_custom_request_out_converter() -> None:
    service = TranslationService()

    def to_custom(request: CanonicalChatRequest) -> dict[str, str]:
        return {
            "model": request.model,
            "first_message": request.messages[0].content or "",
        }

    service.register_converter("request_out", "custom", to_custom)

    domain_request = CanonicalChatRequest(
        model="my-model",
        messages=[ChatMessage(role="user", content="hello")],
    )

    converted = service.from_domain_request(domain_request, "custom")

    assert converted == {"model": "my-model", "first_message": "hello"}


def test_register_custom_response_out_converter() -> None:
    service = TranslationService()

    def to_custom(response: CanonicalChatResponse) -> dict[str, str]:
        return {
            "identifier": response.id,
            "reply": response.choices[0].message.content or "",
        }

    service.register_converter("response_out", "custom", to_custom)

    domain_response = CanonicalChatResponse(
        id="resp-1",
        created=123,
        model="my-model",
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionChoiceMessage(
                    role="assistant", content="hi there"
                ),
                finish_reason="stop",
            )
        ],
    )

    converted = service.from_domain_response(domain_response, "custom")

    assert converted == {"identifier": "resp-1", "reply": "hi there"}
