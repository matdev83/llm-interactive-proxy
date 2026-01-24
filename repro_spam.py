
import asyncio
import logging
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock

# Mock dependencies
from src.core.config.models.end_of_session import EndOfSessionConfig
from src.core.domain.events.end_of_session_events import EndOfSessionSignal
from src.core.ports.streaming_contracts import StreamingContent
from src.core.services.streaming.end_of_session_stream_processor import EndOfSessionStreamProcessor

async def repro():
    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)
    
    # Mock EoS service that always returns True for has_ended
    eos_service = MagicMock()
    eos_service.has_ended = AsyncMock(return_value=True)
    
    config = EndOfSessionConfig(enabled=True, detect_stream_signals=True)
    processor = EndOfSessionStreamProcessor(eos_service, config)
    
    session_id = "test-session-id"
    content = StreamingContent(
        content="some content",
        metadata={"session_id": session_id}
    )
    
    print("Starting spam simulation...")
    for i in range(10):
        await processor.process(content)
    print("Spam simulation finished.")

if __name__ == "__main__":
    asyncio.run(repro())
