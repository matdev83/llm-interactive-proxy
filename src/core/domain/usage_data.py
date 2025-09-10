from datetime import datetime

from pydantic import Field

from src.core.interfaces.model_bases import DomainModel


class UsageData(DomainModel):
    """Represents usage data for LLM API calls.

    This model tracks token usage, costs, and other metrics for API calls.
    """

    id: str = Field(..., description="Unique identifier for the usage entry")
    session_id: str = Field(..., description="Associated session ID")
    project: str | None = Field(None, description="Associated project")
    model: str = Field(..., description="LLM model used")
    prompt_tokens: int = Field(0, description="Number of prompt tokens")
    completion_tokens: int = Field(0, description="Number of completion tokens")
    total_tokens: int = Field(0, description="Total tokens used")
    cost: float | None = Field(None, description="Estimated cost")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="Timestamp of the usage"
    )
