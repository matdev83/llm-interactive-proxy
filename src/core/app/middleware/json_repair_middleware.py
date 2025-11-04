from __future__ import annotations

import json
import logging
from typing import Any

import src.core.services.metrics_service as metrics
from src.core.config.app_config import AppConfig
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
)
from src.core.services.json_repair_service import (
    JsonRepairResult,
    JsonRepairService,
)

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
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        """
        Processes the response to detect and repair JSON if enabled.
        """
        if not self.config.session.json_repair_enabled:
            return response

        # Skip for streaming chunks; handled by JsonRepairProcessor in pipeline
        if context.get("response_type") == "stream":
            return response

        if isinstance(response.content, str):
            # Gate strict mode for non-streaming repairs based on intent
            headers_raw = response.metadata.get("headers")
            headers: dict[str, Any] = (
                headers_raw if isinstance(headers_raw, dict) else {}
            )
            ct_raw = response.metadata.get("content_type")
            content_type = (
                ct_raw
                if isinstance(ct_raw, str)
                else headers.get("Content-Type") or headers.get("content-type")
            )
            is_json_ct = (
                isinstance(content_type, str)
                and "application/json" in content_type.lower()
            )
            expected_json = bool(context.get("expected_json"))
            has_schema = self.config.session.json_repair_schema is not None
            strict_effective = (
                bool(self.config.session.json_repair_strict_mode)
                or is_json_ct
                or expected_json
                or has_schema
            )

            try:
                repair_result: JsonRepairResult = (
                    self.json_repair_service.repair_and_validate_json(
                        response.content,
                        schema=self.config.session.json_repair_schema,
                        strict=strict_effective,
                    )
                )
                metric_suffix = (
                    "strict_success"
                    if strict_effective and repair_result.success
                    else (
                        "best_effort_success"
                        if repair_result.success
                        else ("strict_fail" if strict_effective else "best_effort_fail")
                    )
                )
                metrics.inc(f"json_repair.non_streaming.{metric_suffix}")
            except Exception:
                metrics.inc(
                    "json_repair.non_streaming.strict_fail"
                    if strict_effective
                    else "json_repair.non_streaming.best_effort_fail"
                )
                raise
            if repair_result.success:
                if logger.isEnabledFor(logging.INFO):
                    logger.info(f"JSON detected and repaired for session {session_id}")
                response.content = json.dumps(repair_result.content)
                response.metadata["repaired"] = True

        return response
