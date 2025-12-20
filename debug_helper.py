
import logging
from typing import Any
from src.core.domain.chat import ChatRequest
from src.core.domain.backend_request_manager.context_models import ToolCallRetryState
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope

logger = logging.getLogger(__name__)

def debug_print(msg):
    print(f"DEBUG: {msg}")

# ... (I'll use search_replace to insert calls to debug_print or just print directly)

