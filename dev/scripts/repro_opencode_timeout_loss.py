"""Reproduce OpenCode bash timeout loss in openai-codex stream translation.

The script exits with status 1 when the current bug is present. It uses the same
ResponseExecutor normalization path that production openai-codex streaming uses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.connectors.openai_codex.executor import ResponseExecutor
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.translation_service import TranslationService


def main() -> int:
    base_connector = MagicMock()
    base_connector.translation_service = TranslationService()
    credential_manager = MagicMock()
    executor = ResponseExecutor(base_connector, credential_manager)

    upstream_arguments = {
        "command": "./.venv/Scripts/python.exe -m pytest",
        "timeout": 900000,
        "workdir": "C:\\Users\\Mateusz\\source\\repos\\llm-interactive-proxy",
        "description": "Run full pytest suite with 15 minute timeout",
    }
    chunk = ProcessedResponse(
        content={
            "type": "response.output_item.done",
            "item": {
                "type": "function_call",
                "id": "fc_timeout_repro",
                "call_id": "call_timeout_repro",
                "name": "bash",
                "arguments": json.dumps(upstream_arguments),
                "status": "completed",
            },
        },
        metadata={"event_type": "response.output_item.done"},
    )

    normalized = executor._normalize_processed_stream_chunk(chunk)
    content = cast(dict[str, Any], normalized.content)
    tool_call = content["choices"][0]["delta"]["tool_calls"][0]
    actual_arguments = json.loads(tool_call["function"]["arguments"])

    print(
        json.dumps(
            {
                "upstream_arguments": upstream_arguments,
                "client_visible_arguments": actual_arguments,
                "timeout_preserved": actual_arguments.get("timeout") == 900000,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if actual_arguments.get("timeout") == 900000 else 1


if __name__ == "__main__":
    raise SystemExit(main())
