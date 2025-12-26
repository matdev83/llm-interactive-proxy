from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.core.interfaces.response_processor_interface import ProcessedResponse


class ReasoningDetectionMetadata(BaseModel):
    method: str | None = None
    chunks_processed: int = 0
    tokens_estimated: int = 0
    chars_captured: int = 0
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    raw_chunks: list[ProcessedResponse] = Field(default_factory=list)
    error: str | None = None

    class Config:
        arbitrary_types_allowed = True


class ReasoningDetectionResult(BaseModel):
    """Result of reasoning end detection.

    Returned by detection methods to indicate whether reasoning phase ended
    and which tag/reason/marker triggered the detection.
    """

    is_detected: bool
    detected_value: str | None = None


class ReasoningCaptureResult(BaseModel):
    reasoning_text: str
    reasoning_complete: bool
    metadata: ReasoningDetectionMetadata
