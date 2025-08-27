from __future__ import annotations

import json
import logging
from typing import Any

from src.core.config.app_config import AppConfig
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    ProcessedResponse,
)
from src.core.services.json_repair_service import JsonRepairService

logger = logging.getLogger(__name__)


class JsonRepairMiddleware(IResponseMiddleware):
    """
    Middleware to detect and repair JSON in LLM responses.
    """

    def __init__(
        self, config: AppConfig, json_repair_service: JsonRepairService
    ) -> None:
        self.config = config
        self.json_repair_service = json_repair_service

    async def process(
        self, response: ProcessedResponse, session_id: str, context: dict[str, Any]
    ) -> ProcessedResponse:
        """
        Processes the response to detect and repair JSON if enabled.
        """
        if not self.config.session.json_repair_enabled:
            return response

        if isinstance(response.content, str):
            repaired_json = self.json_repair_service.repair_and_validate_json(
                response.content,
                strict=self.config.session.json_repair_strict_mode,
            )
            if repaired_json:
                logger.info(f"JSON detected and repaired for session {session_id}")
                response.content = json.dumps(repaired_json)
                response.metadata["repaired"] = True

        return response
