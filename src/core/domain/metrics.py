from pydantic import BaseModel


class TimerStats(BaseModel):
    """Statistics for a timer metric."""

    count: int
    total: float
    average: float
    min: float
    max: float
