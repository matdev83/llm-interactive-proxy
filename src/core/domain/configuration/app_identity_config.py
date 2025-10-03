from __future__ import annotations

from typing import Any

from pydantic import Field

from src.core.domain.base import ValueObject
from src.core.domain.configuration.header_config import HeaderConfig
from src.core.interfaces.configuration import IAppIdentityConfig


class AppIdentityConfig(ValueObject, IAppIdentityConfig):
    """Represents the application's identity settings."""

    title: HeaderConfig = Field(
        default=HeaderConfig(
            default_value="llm-interactive-proxy",
            passthrough_name="x-title",
        ),
        description="The title of the application, sent as a header to backends.",
    )
    url: HeaderConfig = Field(
        default=HeaderConfig(
            default_value="https://github.com/matdev83/llm-interactive-proxy",
            passthrough_name="http-referer",
        ),
        description="The URL of the application, sent as a header to backends.",
    )
    user_agent: HeaderConfig = Field(
        default=HeaderConfig(
            default_value="llm-interactive-proxy", passthrough_name="user-agent"
        ),
        description="The User-Agent header, sent to backends.",
    )

    @property
    def title_value(self) -> str:
        """The resolved title of the application."""
        # For backward compatibility, return the default value
        return self.title.default_value

    @property
    def url_value(self) -> str:
        """The resolved URL of the application."""
        # For backward compatibility, return the default value
        return self.url.default_value

    def get_resolved_headers(
        self, incoming_headers: dict[str, Any] | None
    ) -> dict[str, str]:
        """Get the resolved headers for the application identity.

        Args:
            incoming_headers: The headers from the incoming request.

        Returns:
            A dictionary of resolved headers.
        """
        headers = {}
        if (title := self.title.resolve_value(incoming_headers)) is not None:
            headers["X-Title"] = title
        if (url := self.url.resolve_value(incoming_headers)) is not None:
            headers["HTTP-Referer"] = url
        if (user_agent := self.user_agent.resolve_value(incoming_headers)) is not None:
            headers["User-Agent"] = user_agent
        return headers
