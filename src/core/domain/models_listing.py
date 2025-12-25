from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ModelInfo(BaseModel):
    id: str
    name: str | None = None
    object: str = "model"
    created: int | None = None
    owned_by: str | None = None

    class Config:
        extra = "allow"


class ModelsListingResponse(BaseModel):
    object: str = "list"
    data: list[ModelInfo]

    class Config:
        extra = "allow"
