"""Configuration for non-forwardable message tagging feature."""

from __future__ import annotations

from pydantic import ConfigDict, Field

from src.core.interfaces.model_bases import DomainModel


class NonForwardableTaggingConfig(DomainModel):
    """Configuration for non-forwardable message tagging.

    Controls bounded memory storage for non-forwardable tags per session.
    """

    model_config = ConfigDict(frozen=True)

    max_identities_per_session: int = Field(
        default=10000,
        ge=1,
        description="Maximum number of stored non-forwardable identities per session.",
    )
    """Maximum number of stored non-forwardable identities per session.

    When this limit is exceeded, the proxy will fail the request without calling
    any remote backend and return a NonForwardableTagLimitExceededError.

    Default: 10000
    """
