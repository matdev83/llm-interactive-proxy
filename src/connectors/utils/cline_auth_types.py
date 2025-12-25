from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ClineUserInfo(BaseModel):
    id: str | None = None
    email: str | None = None
    name: str | None = None
    # Add other fields if discovered, but for now Any dict was used
    # The code used .get("id") mostly.

    class Config:
        extra = "allow"


class ClineTokenData(BaseModel):
    id_token: str = Field(alias="idToken")
    refresh_token: str | None = Field(default=None, alias="refreshToken")
    expires_at: float | None = Field(default=None, alias="expiresAt")
    user_info: dict[str, Any] = Field(default_factory=dict, alias="userInfo")
    provider: str = "cline"

    class Config:
        populate_by_name = True
