from __future__ import annotations

import json as json_module
from typing import Any

import httpx
from httpx import URL


class MockHTTPClient(httpx.AsyncClient):
    """A mock HTTPX client that can be used in tests."""

    def __init__(self, response: httpx.Response, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.response = response
        self.sent_request: httpx.Request | None = None

    async def post(
        self,
        url: URL | str,
        *,
        content: Any = None,
        json: Any = None,  # Use 'json' parameter to match httpx.AsyncClient.post
        **kwargs: Any,
    ) -> httpx.Response:
        """Mock the POST request."""
        print(f"MockHTTPClient.post called with json: {json}")
        if json is not None:
            content = json_module.dumps(json)

        headers = kwargs.get("headers", {})
        # Create the request with the correct parameters
        # httpx.Request will handle the content parameter correctly
        self.sent_request = httpx.Request("POST", url, content=content, headers=headers)
        # Set the request on the response so raise_for_status works
        self.response._request = self.sent_request
        return self.response

    async def get(self, url: URL | str, **kwargs: Any) -> httpx.Response:
        """Mock the GET request."""
        headers = kwargs.get("headers", {})
        self.sent_request = httpx.Request("GET", url, headers=headers)
        return self.response
