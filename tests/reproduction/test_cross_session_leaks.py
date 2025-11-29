import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from src.core.services.response_processor_service import ResponseProcessor
from src.core.services.tool_call_reactor_service import ToolCallReactorService, ToolCallContext
from src.core.interfaces.loop_detector_interface import ILoopDetector, LoopDetectionResult
from src.core.interfaces.response_parser_interface import IResponseParser

class MockLoopDetector(ILoopDetector):
    def __init__(self):
        self.reset_count = 0
        self.seen = []

    def is_enabled(self) -> bool:
        return True

    def process_chunk(self, chunk: str):
        return None

    def reset(self) -> None:
        self.reset_count += 1
        self.seen = []

    def get_loop_history(self):
        return []

    def get_current_state(self):
        return {}

    def get_stats(self):
        return {}

    async def check_for_loops(self, content: str) -> LoopDetectionResult:
        self.seen.append(content)
        return LoopDetectionResult(has_loop=False)

@pytest.mark.asyncio
async def test_response_processor_loop_detector_interference():
    """
    Demonstrate that ResponseProcessor resets the shared LoopDetector,
    interfering with concurrent requests.
    """
    loop_detector = MockLoopDetector()
    parser = MagicMock(spec=IResponseParser)
    
    # Initialize ResponseProcessor with a shared loop detector
    processor = ResponseProcessor(
        response_parser=parser,
        loop_detector=loop_detector,
        stream_normalizer=MagicMock() # Mock to avoid complex setup
    )

    # Simulate two concurrent streaming sessions
    async def stream_session(session_id, chunks):
        async def iterator():
            for c in chunks:
                yield c
                await asyncio.sleep(0.01) # Yield control
        
        async for _ in processor.process_streaming_response(iterator(), session_id):
            pass

    # Run two sessions concurrently
    # Session 1 starts, resets loop detector.
    # Session 2 starts, resets loop detector (wiping Session 1's state if it had any).
    # In this mock, we just check reset count.
    
    await asyncio.gather(
        stream_session("session1", ["a", "b"]),
        stream_session("session2", ["c", "d"])
    )

    # If properly isolated, we might expect separate detectors or no interference.
    # But here we expect the single detector to be reset multiple times, potentially mid-stream if logic allowed.
    # Actually, reset() is called at the START of process_streaming_response.
    # So:
    # 1. Session 1 calls reset()
    # 2. Session 1 yields 'a'
    # 3. Session 2 calls reset() -> WIPES Session 1's 'a' from memory!
    # 4. Session 1 yields 'b' -> Loop detector only sees 'b', missing 'a'.
    
    # To prove this, we need the loop detector to actually track state.
    # Our MockLoopDetector tracks 'seen'.
    
    # Let's verify that 'seen' is cleared unexpectedly.
    # We need a more controlled execution than gather() to guarantee order, 
    # but gather with sleep usually interleaves.
    
    # Expected behavior: 2 resets (one for each session start).
    assert loop_detector.reset_count == 2
    
    # The real issue is that Session 1's state is wiped by Session 2.
    # If we had a loop "a -> a" split across chunks, and Session 2 reset in between, we'd miss the loop.

@pytest.mark.asyncio
async def test_tool_call_reactor_session_less_mixing():
    """
    Demonstrate that ToolCallReactorService mixes history for session-less requests.
    """
    tracker = AsyncMock()
    reactor = ToolCallReactorService(history_tracker=tracker)
    
    # Context 1: No session ID
    ctx1 = ToolCallContext(
        tool_name="tool1",
        tool_arguments={},
        backend_name="backend",
        model_name="model",
        calling_agent="agent",
        session_id=None,
        timestamp=None,
        full_response=None
    )
    
    # Context 2: No session ID (different "request" conceptually)
    ctx2 = ToolCallContext(
        tool_name="tool2",
        tool_arguments={},
        backend_name="backend",
        model_name="model",
        calling_agent="agent",
        session_id=None,
        timestamp=None,
        full_response=None
    )
    
    await reactor.process_tool_call(ctx1)
    await reactor.process_tool_call(ctx2)
    
    # Check what session ID was used for recording
    # We expect both to use the SAME resolved session ID (from __empty__ alias)
    
    calls = tracker.record_tool_call.call_args_list
    assert len(calls) == 2
    
    session_id_1 = calls[0].args[0]
    session_id_2 = calls[1].args[0]
    
    # This assertion proves the leak: they share the same ID
    assert session_id_1 == session_id_2
    assert session_id_1 is not None
