"""
Request body builder strategies for Gemini OAuth connectors.

This module provides different request body formats:
- StandardRequestBodyBuilder: Standard user_prompt_id format
- AntigravityRequestBodyBuilder: Antigravity requestId/userAgent/requestType format
"""

import time
import uuid
from collections.abc import Callable
from typing import Any


class StandardRequestBodyBuilder:
    """Request body builder for standard Code Assist API.

    Used by gemini-oauth-plan and gemini-oauth-free backends.
    Produces request bodies with the user_prompt_id field.
    """

    def build(
        self,
        effective_model: str,
        project_id: str,
        request_data: Any,
        inner_request: dict[str, Any],
        user_prompt_id_generator: Callable[[Any], str] | None = None,
    ) -> dict[str, Any]:
        """Build the outer request body wrapper for Code Assist API.

        Args:
            effective_model: The model name to use.
            project_id: The project ID from loadCodeAssist.
            request_data: The original request data (for generating user_prompt_id).
            inner_request: The inner request with contents, generationConfig, etc.
            user_prompt_id_generator: Optional callable to generate user_prompt_id.

        Returns:
            Complete request body dict ready to send to the API.
        """
        if user_prompt_id_generator:
            user_prompt_id = user_prompt_id_generator(request_data)
        else:
            user_prompt_id = self._generate_user_prompt_id(request_data)

        return {
            "model": effective_model,
            "project": project_id,
            "user_prompt_id": user_prompt_id,
            "request": inner_request,
        }

    @staticmethod
    def _generate_user_prompt_id(request_data: Any) -> str:
        """Generate a unique user_prompt_id for the request.

        Args:
            request_data: The original request data.

        Returns:
            A unique ID string.
        """
        # Try to get ID from request data, or generate a new one
        if hasattr(request_data, "id") and request_data.id:
            return str(request_data.id)
        return f"req_{uuid.uuid4().hex[:16]}"


class AntigravityRequestBodyBuilder:
    """Request body builder for Antigravity sandbox API.

    Used by antigravity-oauth backend.
    Produces request bodies with requestId, userAgent, and requestType fields.
    """

    def build(
        self,
        effective_model: str,
        project_id: str,
        request_data: Any,
        inner_request: dict[str, Any],
        user_prompt_id_generator: Callable[[Any], str] | None = None,
    ) -> dict[str, Any]:
        """Build Antigravity-specific request body format.

        The Antigravity sandbox API uses a different wrapper structure than
        the standard Code Assist API:
        - 'requestId' instead of 'user_prompt_id'
        - 'model' at top level (not inside 'request')
        - Additional 'userAgent' and 'requestType' fields required

        Args:
            effective_model: The model name to use.
            project_id: The project ID from loadCodeAssist.
            request_data: The original request data (for generating requestId).
            inner_request: The inner request with contents, generationConfig, etc.
            user_prompt_id_generator: Optional callable to generate requestId.

        Returns:
            Antigravity-formatted request body dict.
        """
        if user_prompt_id_generator:
            request_id = user_prompt_id_generator(request_data)
        else:
            request_id = self._generate_request_id(request_data)

        return {
            "project": project_id,
            "requestId": request_id,
            "request": inner_request,
            "model": effective_model,
            "userAgent": "antigravity",
            "requestType": "agent",
        }

    @staticmethod
    def _generate_request_id(request_data: Any) -> str:
        """Generate a unique requestId for the Antigravity API.

        Args:
            request_data: The original request data.

        Returns:
            A unique request ID string.
        """
        # Try to get ID from request data, or generate a new one
        if hasattr(request_data, "id") and request_data.id:
            return str(request_data.id)
        return f"req_{int(time.time() * 1000)}"


__all__ = [
    "AntigravityRequestBodyBuilder",
    "StandardRequestBodyBuilder",
]
