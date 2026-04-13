from __future__ import annotations

from typing import Literal

from src.core.interfaces.model_bases import DomainModel


class QualityVerifierDecision(DomainModel):
    decision: Literal["pass", "steer"]
    steering_message: str | None = None
