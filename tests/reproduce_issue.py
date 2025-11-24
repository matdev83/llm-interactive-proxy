import asyncio
import json
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.ports.streaming_contracts import StreamingContent


# Mock JsonRepairProcessor (simplified)
class JsonRepairProcessor:
    def __init__(self):
        self._states = {}

    async def process(self, content: StreamingContent):
        raw_content = content.content
        if isinstance(raw_content, bytes):
            text = raw_content.decode("utf-8", errors="ignore")
        elif isinstance(raw_content, dict):
            text = json.dumps(raw_content)
        else:
            text = str(raw_content or "")

        i = 0
        # This is the line causing error
        try:
            brace_pos_obj = text.find("{", i)
            print(f"Success: {brace_pos_obj}, text type: {type(text)}")
            return True
        except Exception as e:
            print(f"Error with type {type(text)}: {e}")
            return False


async def main():
    processor = JsonRepairProcessor()

    # Test with ProcessedResponse containing bytes (this was the actual bug)
    print("Testing with ProcessedResponse containing bytes:")
    pr_bytes = ProcessedResponse(content=b"some bytes", metadata={}, usage=None)
    sc_from_pr = StreamingContent.from_raw(pr_bytes)
    print(
        f"  StreamingContent.content type: {type(sc_from_pr.content)}, value: {sc_from_pr.content!r}"
    )
    await processor.process(sc_from_pr)

    # Test with ProcessedResponse containing string
    print("\nTesting with ProcessedResponse containing string:")
    pr_str = ProcessedResponse(content="some string", metadata={}, usage=None)
    sc_from_pr_str = StreamingContent.from_raw(pr_str)
    print(
        f"  StreamingContent.content type: {type(sc_from_pr_str.content)}, value: {sc_from_pr_str.content!r}"
    )
    await processor.process(sc_from_pr_str)

    # Test with StreamingContent directly (for comparison)
    print("\nTesting with direct StreamingContent (string):")
    await processor.process(StreamingContent(content="some string"))


if __name__ == "__main__":
    asyncio.run(main())
