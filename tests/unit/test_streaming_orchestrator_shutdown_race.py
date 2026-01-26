import asyncio
import contextlib

import pytest
from src.core.ports.streaming_orchestrator import safe_aclose


async def slow_generator():
    """A generator that is slow to close."""
    try:
        yield "item"
    finally:
        # Simulate some async cleanup
        await asyncio.sleep(0.2)

@pytest.mark.asyncio
async def test_safe_aclose_blocks_on_cancellation() -> None:
    """
    Ensure safe_aclose blocks until aclose() completes even when cancelled.
    This prevents races in sequential cleanup stacks (like AsyncExitStack).
    """
    gen = slow_generator()
    # Advance to the yield
    await gen.__anext__()
    
    close_task_finished = False
    
    async def close_with_cancellation():
        nonlocal close_task_finished
        try:
            await safe_aclose(gen)
            close_task_finished = True
        except asyncio.CancelledError:
            # We expect safe_aclose to re-raise cancellation after waiting
            raise

    # Start the close task
    t = asyncio.create_task(close_with_cancellation())
    
    # Wait until it enters aclose() and suspends at the sleep
    await asyncio.sleep(0.1)
    
    # Now cancel it. If safe_aclose works correctly, it should WAIT
    # for the 0.2s sleep in the generator's finally block to finish
    # before allowing this task to be considered cancelled.
    t.cancel()
    
    start_wait = asyncio.get_event_loop().time()
    with contextlib.suppress(asyncio.CancelledError):
        await t
    end_wait = asyncio.get_event_loop().time()
    
    # It should have waited at least another 0.1s (total 0.2s for the finally block)
    # The sleep in finally is 0.2s, we waited 0.1s before cancelling.
    # So it should wait at least ~0.1s more.
    assert end_wait - start_wait >= 0.05  # Use a conservative threshold
    
    # Verify the generator is indeed closed
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()

@pytest.mark.asyncio
async def test_safe_aclose_prevents_runtime_error_in_stack() -> None:
    """
    Test that safe_aclose prevents the specific RuntimeError seen in logs
    when multiple layers of generators are closed in a stack.
    """
    # This simulates the nested generator structure from the logs
    # OpenAIConnector.stream_completion -> Normalizer -> ... -> Assembler
    
    async def source():
        try:
            yield "data"
        finally:
            await asyncio.sleep(0.1)

    async def wrapper(inner):
        try:
            async for item in inner:
                yield item
        finally:
            pass # Implicitly closes inner
            
    s = source()
    w = wrapper(s)
    
    # Prime the generators
    await w.__anext__()
    
    import contextlib
    
    async def run_stack():
        async with contextlib.AsyncExitStack() as stack:
            # Register them. In AsyncExitStack, they are closed in reverse order.
            # So w is closed first, which will try to close s.
            # Then s is closed by its own callback.
            stack.push_async_callback(safe_aclose, s)
            stack.push_async_callback(safe_aclose, w)
            # Stack exits here and starts cleanup
    
    t = asyncio.create_task(run_stack())
    await asyncio.sleep(0.05) # Wait until w.aclose() has started s.aclose()
    
    t.cancel()
    
    # If safe_aclose is working, this should NOT raise RuntimeError
    # even though t is cancelled during cleanup.
    with contextlib.suppress(asyncio.CancelledError):
        await t
    # If we got here without RuntimeError, the test passed.
