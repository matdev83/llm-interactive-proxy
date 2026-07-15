from __future__ import annotations

from typing import Any

import pytest
from src.core.common.exceptions import ResponsesProviderLimitationError
from src.core.domain.responses_domain import (
    ResponsesContentPart,
    ResponsesDomainRequest,
    ResponsesInputItem,
    ResponsesOutputItem,
)
from src.core.domain.responses_resolved_session import ResponsesHistoryItem
from src.core.services.acp_responses_projector import project_responses_to_acp_chat


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_output_tokens", 32),
        ("max_tokens", 32),
        ("temperature", 0.2),
        ("top_p", 0.8),
        ("stop", ["END"]),
        ("n", 2),
        ("seed", 42),
        ("top_logprobs", 2),
        ("presence_penalty", 0.2),
        ("frequency_penalty", 0.2),
        ("logit_bias", {"42": -1.0}),
    ],
)
def test_acp_projection_rejects_unsupported_generation_controls(
    field: str, value: Any
) -> None:
    request = ResponsesDomainRequest(
        model="cursor-cli-acp:cursor/glm-5.2-max",
        input=[ResponsesInputItem(type="message", role="user", content="hello")],
        **{field: value},
    )

    with pytest.raises(ResponsesProviderLimitationError) as exc_info:
        project_responses_to_acp_chat(
            request,
            None,
            explicit_model="cursor-cli-acp:cursor/glm-5.2-max",
        )

    assert exc_info.value.feature == field


def test_acp_projection_preserves_string_form_input() -> None:
    request = ResponsesDomainRequest.model_construct(
        model="cursor-cli-acp.default:cursor/glm-5.2-max",
        input="Reply exactly OK",
    )

    canonical = project_responses_to_acp_chat(
        request,
        None,
        explicit_model="cursor-cli-acp.default:cursor/glm-5.2-max",
    )

    assert len(canonical.messages) == 1
    assert canonical.messages[0].role == "user"
    assert canonical.messages[0].to_dict()["content"][0]["text"] == "Reply exactly OK"


def test_acp_projection_includes_current_instructions_in_transcript() -> None:
    request = ResponsesDomainRequest(
        model="cursor-cli-acp:cursor/glm-5.2-max",
        instructions="Use the replacement instructions for this turn.",
        input=[ResponsesInputItem(type="message", role="user", content="hello")],
    )

    canonical = project_responses_to_acp_chat(
        request,
        None,
        explicit_model="cursor-cli-acp:cursor/glm-5.2-max",
    )

    assert canonical.messages[0].role == "system"
    assert canonical.messages[0].to_dict()["content"][0]["text"] == (
        "Use the replacement instructions for this turn."
    )
    assert canonical.messages[-1].role == "user"


def test_acp_projection_preserves_function_call_history_and_matching_output() -> None:
    prior = [
        ResponsesOutputItem(
            id="fc_1",
            type="function_call",
            status="completed",
            call_id="call_1",
            name="lookup",
            arguments='{"query":"status"}',
        )
    ]
    request = ResponsesDomainRequest(
        model="cursor-cli-acp:cursor/glm-5.2-max",
        input=[
            ResponsesInputItem(
                type="function_call_output",
                call_id="call_1",
                output='{"result":"ok"}',
            ),
            ResponsesInputItem(
                type="message",
                role="user",
                content=[ResponsesContentPart(type="input_text", text="continue")],
            ),
        ],
    )

    canonical = project_responses_to_acp_chat(
        request,
        prior,
        explicit_model="cursor-cli-acp:cursor/glm-5.2-max",
    )

    assistant, tool, user = canonical.messages
    assert assistant.role == "assistant"
    assert assistant.tool_calls is not None
    assert assistant.tool_calls[0].id == "call_1"
    assert assistant.tool_calls[0].function.name == "lookup"
    assert assistant.tool_calls[0].function.arguments == '{"query":"status"}'
    assert tool.role == "tool"
    assert tool.tool_call_id == "call_1"
    assert tool.content == '{"result":"ok"}'
    assert user.role == "user"


def test_acp_projection_rejects_trailing_function_call_output() -> None:
    history: list[ResponsesHistoryItem] = [
        ResponsesInputItem(
            type="message",
            role="user",
            content="Look up the deployment status.",
        ),
        ResponsesOutputItem(
            id="fc_1",
            type="function_call",
            status="completed",
            call_id="call_1",
            name="lookup",
            arguments='{"query":"deployment"}',
        ),
    ]
    request = ResponsesDomainRequest(
        model="cursor-cli-acp:cursor/glm-5.2-max",
        input=[
            ResponsesInputItem(
                type="function_call_output",
                call_id="call_1",
                output='{"status":"ready"}',
            )
        ],
    )

    with pytest.raises(ResponsesProviderLimitationError) as exc_info:
        project_responses_to_acp_chat(
            request,
            prior_items=None,
            prior_history=history,
            explicit_model="cursor-cli-acp:cursor/glm-5.2-max",
        )

    assert exc_info.value.feature == "input.function_call_output"


def test_acp_projection_replays_complete_history_after_runtime_reap() -> None:
    history: list[ResponsesHistoryItem] = [
        ResponsesInputItem(
            type="message",
            role="user",
            content="original prompt",
        ),
        ResponsesOutputItem(
            id="assistant_1",
            type="message",
            role="assistant",
            status="completed",
            content=[ResponsesContentPart(type="output_text", text="first answer")],
        ),
    ]
    request = ResponsesDomainRequest(
        model="cursor-cli-acp:cursor/glm-5.2-max",
        input=[ResponsesInputItem(type="message", role="user", content="follow up")],
    )

    canonical = project_responses_to_acp_chat(
        request,
        prior_items=None,
        prior_history=history,
        explicit_model="cursor-cli-acp:cursor/glm-5.2-max",
    )

    assert [message.role for message in canonical.messages] == [
        "user",
        "assistant",
        "user",
    ]
    assert [
        message.to_dict()["content"][0]["text"] for message in canonical.messages
    ] == ["original prompt", "first answer", "follow up"]


def test_matching_embedded_reasoning_effort_is_validation_only() -> None:
    request = ResponsesDomainRequest(
        model="cursor-cli-acp:cursor/glm-5.2-max",
        input=[ResponsesInputItem(type="message", role="user", content="hello")],
        reasoning={"effort": "max"},
    )

    canonical = project_responses_to_acp_chat(
        request,
        None,
        explicit_model="cursor-cli-acp:cursor/glm-5.2-max",
    )

    assert canonical.model == "cursor-cli-acp:cursor/glm-5.2-max"
    assert canonical.reasoning is None
    assert canonical.reasoning_effort is None


@pytest.mark.parametrize(
    ("input_item", "feature"),
    [
        (
            ResponsesInputItem(type="input_image"),
            "input_image",
        ),
        (
            ResponsesInputItem(
                type="message",
                role="user",
                content=[ResponsesContentPart(type="input_file")],
            ),
            "input_file",
        ),
        (
            ResponsesInputItem(
                type="message",
                role="user",
                content=[
                    ResponsesContentPart(type="input_text", text="keep this"),
                    ResponsesContentPart(
                        type="input_image",
                        image_url={"url": "https://example.test/image.png"},
                    ),
                ],
            ),
            "input_image",
        ),
    ],
)
def test_acp_projection_rejects_non_text_input_parts(
    input_item: ResponsesInputItem,
    feature: str,
) -> None:
    request = ResponsesDomainRequest(
        model="cursor-cli-acp:cursor/glm-5.2-max",
        input=[input_item],
    )

    with pytest.raises(ResponsesProviderLimitationError) as exc_info:
        project_responses_to_acp_chat(
            request,
            None,
            explicit_model="cursor-cli-acp:cursor/glm-5.2-max",
        )

    assert exc_info.value.feature == feature
