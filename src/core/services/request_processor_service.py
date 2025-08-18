from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any, cast

from fastapi import HTTPException, Request
from starlette.responses import Response, StreamingResponse

from src.agents import (
    convert_cline_marker_to_openai_tool_call,
    detect_agent,
    format_command_response_for_agent,
)
from src.core.adapters.api_adapters import legacy_to_domain_chat_request
from src.core.common.exceptions import LoopDetectionError
from src.core.domain.chat import (
    ChatCompletionChoice,
    ChatRequest,
    ChatResponse,
    StreamingChatResponse,
)
from src.core.domain.chat import ChatMessage as DomainChatMessage
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.session import Session, SessionInteraction
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.command_service_interface import ICommandService
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.response_processor_interface import IResponseProcessor
from src.core.interfaces.session_service_interface import ISessionService

logger = logging.getLogger(__name__)


"""Re-export the original RequestProcessor implementation.

Some tests expect helper methods on the class; to preserve that shape we
simply import and expose the original implementation rather than wrapping it.
"""

from src.core.services.request_processor import RequestProcessor as _Orig

# Re-export the original class under the expected name
RequestProcessor = _Orig


