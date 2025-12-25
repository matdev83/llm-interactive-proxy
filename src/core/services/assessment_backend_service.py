"""
Backend service for LLM assessment communication.

This service handles communication with the LLM backend for assessment,
abstracting backend-specific details and providing structured output.
"""

import json
import logging
from typing import Any

from src.core.common.logging_utils import get_logger, is_log_level_enabled
from src.core.domain.assessment import AssessmentRequest, LLMAssessmentResponse
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.assessment_config import AssessmentConfig
from src.core.interfaces.assessment_service_interface import IAssessmentBackendService
from src.core.interfaces.backend_service_interface import IBackendService

logger = get_logger(__name__)


class AssessmentBackendError(Exception):
    """Exception raised when assessment backend communication fails."""


class AssessmentBackendService(IAssessmentBackendService):
    """
    Service for communicating with assessment backends.

    This service abstracts the details of different backends and provides
    a unified interface for performing assessments with structured output.
    """

    def __init__(self, backend_service: IBackendService, config: AssessmentConfig):
        """
        Initialize assessment backend service.

        Args:
            backend_service: Main backend service for making requests
            config: Assessment configuration
        """
        self.backend_service = backend_service
        self.config = config

    async def perform_assessment(self, request: AssessmentRequest) -> LLMAssessmentResponse:
        """
        Perform assessment using the configured backend.

        This method creates a chat request with structured output requirements
        and processes it through the specified assessment backend and model.

        Args:
            request: Assessment request with messages and context

        Returns:
            LLMAssessmentResponse with assessment response (reasoning, confidence)

        Raises:
            AssessmentBackendError: If backend communication fails
        """
        try:
            # Create chat request for assessment
            chat_request = self._create_chat_request(request)

            if is_log_level_enabled(logger, logging.DEBUG):
                logger.debug(
                    f"Performing assessment for session {request.session_id} "
                    f"using {self.config.backend}/{self.config.model}"
                )

            # Process request through backend
            response = await self.backend_service.chat_completions(chat_request)

            # Parse JSON response
            if hasattr(response, "content"):
                content = response.content
                if not isinstance(content, str):
                    content = str(content)
            else:
                content = str(response)
            assessment_data = self._parse_json_response(content)

            if is_log_level_enabled(logger, logging.DEBUG):
                logger.debug(
                    f"Assessment completed for session {request.session_id}: "
                    f"confidence={assessment_data.confidence}"
                )

            return assessment_data

        except Exception as e:
            logger.error(
                f"Assessment backend error for session {request.session_id}: {e}"
            )
            raise AssessmentBackendError(f"Backend communication failed: {e}") from e

    def is_backend_available(self) -> bool:
        """
        Check if the assessment backend is available.

        Returns:
            True if backend is available and responsive
        """
        try:
            # Simple check - if we have a backend service and config, assume available
            return bool(
                self.backend_service is not None
                and self.config.backend
                and self.config.model
            )
        except Exception:
            return False

    async def health_check(self) -> bool:
        """
        Perform a health check on the assessment backend.

        This sends a minimal request to verify the backend is responsive.

        Returns:
            True if backend is healthy
        """
        try:
            # Create a minimal test request
            test_messages = [
                {"role": "system", "content": "You are a test assistant."},
                {
                    "role": "user",
                    "content": 'Say \'OK\' in JSON format: {"status": "OK"}',
                },
            ]

            # Combine backend and model in the format expected by the routing system
            full_model = f"{self.config.backend}:{self.config.model}"
            test_request = ChatRequest(
                model=full_model,
                messages=[
                    ChatMessage(role=msg["role"], content=msg["content"])
                    for msg in test_messages
                ],
                max_tokens=50,
            )

            response = await self.backend_service.chat_completions(test_request)

            # Try to parse response as JSON
            if hasattr(response, "content"):
                content = response.content
                if not isinstance(content, str | bytes | bytearray):
                    content = str(content)
            else:
                content = str(response)
            json.loads(content)

            if is_log_level_enabled(logger, logging.DEBUG):
                logger.debug(
                    f"Assessment backend health check passed for {self.config.backend}"
                )
            return True

        except Exception as e:
            logger.warning(f"Assessment backend health check failed: {e}")
            return False

    def _create_chat_request(self, request: AssessmentRequest) -> ChatRequest:
        """
        Create a chat request from an assessment request.

        This configures the request with the assessment model and structured output.

        Args:
            request: Assessment request to convert

        Returns:
            ChatRequest configured for assessment
        """
        # Convert assessment messages to chat format
        chat_messages = []
        for msg in request.messages:
            chat_messages.append({"role": msg.role, "content": msg.content})

        # Create chat request with structured output
        # Combine backend and model in the format expected by the routing system
        full_model = f"{self.config.backend}:{self.config.model}"
        chat_request = ChatRequest(
            model=full_model,
            messages=[
                ChatMessage(role=msg["role"], content=msg["content"])
                for msg in chat_messages
            ],
            max_tokens=500,  # Reasonable limit for assessment responses
            temperature=0.1,  # Low temperature for consistent assessment
        )

        return chat_request

    def _parse_json_response(self, content: str) -> LLMAssessmentResponse:
        """
        Parse JSON response from the backend.

        Args:
            content: Raw response content from backend

        Returns:
            LLMAssessmentResponse with parsed data

        Raises:
            AssessmentBackendError: If JSON parsing fails
        """
        try:
            # Handle different response formats
            content = content.strip()

            # Some backends wrap JSON in markdown code blocks
            if content.startswith("```json"):
                content = content[7:]  # Remove ```json
            if content.endswith("```"):
                content = content[:-3]  # Remove ```

            # Parse JSON
            data = json.loads(content)

            # Validate required fields
            if not isinstance(data, dict):
                raise AssessmentBackendError("Response is not a JSON object")

            try:
                return LLMAssessmentResponse.model_validate(data)
            except Exception as e:
                raise AssessmentBackendError(f"Response validation failed: {e}") from e

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {content[:200]}...")
            raise AssessmentBackendError(f"Invalid JSON response: {e}") from e
        except Exception as e:
            raise AssessmentBackendError(f"Response parsing failed: {e}") from e

    def get_backend_info(self) -> dict[str, str]:
        """
        Get information about the configured assessment backend.

        Returns:
            Dictionary with backend information
        """
        return {
            "backend": self.config.backend,
            "model": self.config.model,
            "available": str(self.is_backend_available()),
        }
