from typing import Any

from pydantic import BaseModel


class ACPError(BaseModel):
    code: int
    message: str
    data: Any | None = None


class ToolCall(BaseModel):
    tool_name: str
    arguments: dict[str, Any]


class DataPart(BaseModel):
    ToolCall: ToolCall | None = None


class TextPart(BaseModel):
    TextPart: str


class TaskStatusUpdateEvent(BaseModel):
    Message: str | TextPart | DataPart | dict[str, Any]


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
