from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ACPError(BaseModel):
    code: int
    message: str
    data: Any | None = None


class ToolCall(BaseModel):
    tool_name: str
    arguments: dict[str, Any]


class DataPart(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    tool_call: ToolCall | None = Field(default=None, alias="ToolCall")


class TextPart(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    text: str = Field(alias="TextPart")


class TaskStatusUpdateEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message: str | TextPart | DataPart | dict[str, Any] = Field(alias="Message")


class ACPResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | float | None = None
    method: str | None = None
    params: Any | None = None
    result: Any | None = None
    error: ACPError | None = None

    @property
    def is_result(self) -> bool:
        return self.result is not None

    @property
    def is_error(self) -> bool:
        return self.error is not None
