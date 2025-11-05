from __future__ import annotations

from typing import Literal

from src.core.interfaces.model_bases import DomainModel


class AngelDecision(DomainModel):
    decision: Literal["pass", "steer"]
    steering_message: str | None = None


class AngelVerificationRequest(DomainModel):
    context_messages: list[dict]
    model_response: str | dict


class AngelVerificationResult(DomainModel):
    decision: AngelDecision
    raw_response: str
