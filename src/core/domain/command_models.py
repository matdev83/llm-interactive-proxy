from pydantic import BaseModel


class CommandMatch(BaseModel):
    """Result of a command detection."""

    cmd_name: str
    args_str: str | None
    match_start: int
    match_end: int
