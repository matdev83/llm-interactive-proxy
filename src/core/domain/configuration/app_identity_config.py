from __future__ import annotations

from pydantic import Field

from src.core.domain.base import ValueObject
from src.core.interfaces.configuration_interface import IAppIdentityConfig


class AppIdentityConfig(ValueObject, IAppIdentityConfig):
    """Represents the application's identity settings."""

    title_value: str = Field(
        default="llm-interactive-proxy",
        alias="title",
        description="The title of the application, sent as a header to backends.",
    )
    url_value: str = Field(
        default="https://github.com/matdev83/llm-interactive-proxy",
        alias="url",
        description="The URL of the application, sent as a header to backends.",
    )

    @property
    def title(self) -> str:
        return self.title_value

    @property
    def url(self) -> str:
        return self.url_value

    def with_title(self, title: str) -> IAppIdentityConfig:
        """Create a new config with an updated title."""
        return self.model_copy(update={"title_value": title})

    def with_url(self, url: str) -> IAppIdentityConfig:
        """Create a new config with an updated URL."""
        return self.model_copy(update={"url_value": url})
