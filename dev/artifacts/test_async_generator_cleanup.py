"""Test script to demonstrate async generator resource leak scenario."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator


class ResourceHolder:
    """Simulates a resource that needs explicit cleanup."""

    def __init__(self):
        self.active = True

    def close(self):
        """Simulate resource cleanup."""
        if self.active:
            self.active = False
            print("[LEAK CHECK] Resource cleaned up properly")


async def generate_upstream_data(
    resource: ResourceHolder,
) -> AsyncGenerator[bytes, None]:
    """Simulates an upstream data source (e.g., HTTP response)."""
    try:
        for i in range(100):
            if not resource.active:
                break
            yield f"data chunk {i}\n\n".encode()
            await asyncio.sleep(0.01)
    finally:
        print("[UPSTREAM] generate_upstream_data cleanup called")
        resource.close()


async def byte_wrapper(iterator: AsyncIterator[bytes]) -> AsyncGenerator[bytes, None]:
    """Simulates the _byte_wrapper in anthropic_controller.py."""
    try:
        async for chunk in iterator:
            yield chunk
    finally:
        print("[WRAPPER] byte_wrapper cleanup called")


async def stream_converter(
    chunk_generator: AsyncGenerator[bytes, None]
) -> AsyncGenerator[str, None]:
    """Simulates the openai_stream_to_anthropic_stream converter."""
    try:
        async for chunk_bytes in chunk_generator:
            yield chunk_bytes.decode("utf-8")
    finally:
        print("[CONVERTER] stream_converter cleanup called")


async def final_stream(stream_str: AsyncGenerator[str, None]) -> AsyncIterator[bytes]:
    """Simulates the _anthropic_stream in anthropic_controller.py."""
    try:
        async for chunk_str in stream_str:
            yield chunk_str.encode("utf-8")
    finally:
        print("[FINAL] final_stream cleanup called")


async def simulate_client_disconnect_early():
    """Simulates a client disconnecting after receiving a few chunks."""
    print("\n=== TEST 1: Early client disconnect ===")
    resource = ResourceHolder()
    upstream = generate_upstream_data(resource)
    wrapped = byte_wrapper(upstream)
    converted = stream_converter(wrapped)
    final = final_stream(converted)

    # Simulate client consuming only a few chunks then disconnecting
    chunk_count = 0
    try:
        async for chunk in final:
            chunk_count += 1
            if chunk_count >= 3:
                print(f"[CLIENT] Disconnecting after {chunk_count} chunks")
                break
    except Exception as e:
        print(f"[CLIENT] Exception during consumption: {e}")

    # Check if cleanup was called
    await asyncio.sleep(0.1)
    if resource.active:
        print("[LEAK] WARNING: Resource still active - LEAK DETECTED!")
    else:
        print("[OK] Resource was cleaned up")


async def simulate_aclose_call():
    """Test if explicit aclose() cleans up generators."""
    print("\n=== TEST 2: Explicit aclose() call ===")
    resource = ResourceHolder()
    upstream = generate_upstream_data(resource)
    wrapped = byte_wrapper(upstream)
    converted = stream_converter(wrapped)
    final = final_stream(converted)

    # Consume one chunk then explicitly close
    async for _ in final:
        print("[CLIENT] Got first chunk, calling aclose()")
        await final.aclose()
        break

    # Check if cleanup was called
    await asyncio.sleep(0.1)
    if resource.active:
        print("[LEAK] WARNING: Resource still active - LEAK DETECTED!")
    else:
        print("[OK] Resource was cleaned up")


async def simulate_exception_in_middle():
    """Test if exception in middle of chain propagates cleanup."""
    print("\n=== TEST 3: Exception in middle of chain ===")

    class BadConverter:
        """A converter that raises an exception."""

        async def bad_converter(
            self, chunk_generator: AsyncGenerator[bytes, None]
        ) -> AsyncGenerator[str, None]:
            try:
                async for chunk_bytes in chunk_generator:
                    if b"chunk 5" in chunk_bytes:
                        raise RuntimeError("Simulated error in converter")
                    yield chunk_bytes.decode("utf-8")
            finally:
                print("[BAD_CONVERTER] cleanup called")

    resource = ResourceHolder()
    upstream = generate_upstream_data(resource)
    bad_conv = BadConverter()

    try:
        async for chunk in bad_conv.bad_converter(upstream):
            print(f"[CLIENT] Got chunk: {chunk!r}")
    except RuntimeError as e:
        print(f"[CLIENT] Caught expected error: {e}")

    # Check if cleanup was called
    await asyncio.sleep(0.1)
    if resource.active:
        print("[LEAK] WARNING: Resource still active - LEAK DETECTED!")
    else:
        print("[OK] Resource was cleaned up")


async def main():
    """Run all test scenarios."""
    await simulate_client_disconnect_early()
    await simulate_aclose_call()
    await simulate_exception_in_middle()
    print("\n=== SUMMARY ===")
    print("Check the output above - all cleanup sections should be called.")


if __name__ == "__main__":
    asyncio.run(main())
