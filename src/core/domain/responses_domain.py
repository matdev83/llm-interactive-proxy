"""First-class Responses API domain models (typed input/output items, no chat flattening)."""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field, model_validator

from src.core.interfaces.model_bases import DomainModel


class ResponsesContentPart(DomainModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    type: str
    text: str | None = None
    refusal: str | None = None
    image_url: dict[str, Any] | None = None


class ResponsesInputItem(DomainModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    id: str | None = None
    type: str
    role: str | None = None
    content: list[ResponsesContentPart] | str | None = None
    status: str | None = None
    call_id: str | None = None
    name: str | None = None
    arguments: str | None = None
    output: str | None = None
    acknowledged_safety_checks: list[dict[str, Any]] | None = None
    item_id: str | None = None


class ResponsesOutputItem(DomainModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    id: str
    type: str
    role: str | None = None
    status: str
    content: list[ResponsesContentPart] | None = None
    call_id: str | None = None
    name: str | None = None
    arguments: str | None = None


class ResponsesDomainRequest(DomainModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    model: str
    input: list[ResponsesInputItem] = Field(default_factory=list)
    instructions: str | None = None
    previous_response_id: str | None = None
    conversation: str | dict[str, Any] | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    parallel_tool_calls: bool | None = None
    stream: bool = False
    temperature: float | None = None
    max_output_tokens: int | None = None
    max_tool_calls: int | None = None
    response_format: dict[str, Any] | None = None
    reasoning: dict[str, Any] | None = None
    truncation: str | None = None
    include: list[str] | None = None
    store: bool | None = None
    metadata: dict[str, str] | None = None
    service_tier: str | None = None
    text: dict[str, Any] | None = None
    prompt: dict[str, Any] | None = None
    background: bool | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    top_logprobs: int | None = None
    n: int | None = None
    stream_options: dict[str, Any] | None = None
    stop: list[str] | str | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    logit_bias: dict[str, float] | None = None
    user: str | None = None
    safety_identifier: str | None = None
    prompt_cache_key: str | None = None
    prompt_cache_retention: str | None = None
    seed: int | None = None
    session_id: str | None = None
    agent: str | None = None
    extra_body: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_conversation_exclusivity(self) -> ResponsesDomainRequest:
        if self.previous_response_id and self.conversation:
            raise ValueError(
                "previous_response_id and conversation are mutually exclusive"
            )
        return self
