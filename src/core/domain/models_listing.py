from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ModelInfo(BaseModel):
    id: str
    name: str | None = None
    object: str = "model"
    created: int | None = None
    owned_by: str | None = None
    context_window: int | None = None

    model_config = ConfigDict(extra="allow")


class ModelsListingResponse(BaseModel):
    object: str = "list"
    data: list[ModelInfo]

    model_config = ConfigDict(extra="allow")
