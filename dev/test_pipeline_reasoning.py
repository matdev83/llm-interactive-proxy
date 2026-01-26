
import asyncio
import json
from src.core.services.response_processor_service import ResponseProcessor
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.domain.chat import CanonicalStreamChunk, StreamingChatCompletionChoice, StreamingChatCompletionChoiceDelta
from src.core.domain.request_context import RequestContext

class MockResponseParser(IResponseParser):
    def parse_response(self, raw_response, session_id, *, is_streaming=False): return raw_response
    def extract_content(self, parsed_response): return ""
    def extract_usage(self, parsed_response): return None
    def extract_metadata(self, parsed_response): return {}

async def test_full_pipeline_reasoning():
    # Setup ResponseProcessor with minimal dependencies
    # We need a real StreamNormalizer if we want to test the full path
    from src.core.services.streaming.stream_normalizer import StreamNormalizer
    from src.core.services.streaming.content_accumulation_processor import ContentAccumulationProcessor
    from src.core.services.streaming.stream_context_registry import StreamingContextRegistry
    
    processors = [
        ContentAccumulationProcessor(registry=StreamingContextRegistry())
    ]
    normalizer = StreamNormalizer(processors)
    
    processor = ResponseProcessor(
        response_parser=MockResponseParser(),
        stream_normalizer=normalizer
    )
    
    # 1. Simulate a Gemini chunk (translated to domain)
    delta = StreamingChatCompletionChoiceDelta(
        role="assistant",
        reasoning_content="Thinking step 1",
        content="Hello"
    )
    choice = StreamingChatCompletionChoice(index=0, delta=delta)
    chunk = CanonicalStreamChunk(
        id="test-id",
        choices=[choice],
        model="test-model"
    )
    
    async def chunk_gen():
        # Wrap in dict to simulate what StreamingExecutor yields (after model_dump)
        yield chunk.model_dump(exclude_none=True)
        
    # 2. Process through ResponseProcessor
    context = RequestContext(
        session_id="test-session",
        headers={},
        cookies={},
        state={},
        app_state=None
    )
    processed_stream = processor.process_streaming_response(
        chunk_gen(),
        session_id="test-session",
        context=context
    )
    
    print("\n--- Processed Chunks ---")
    async for resp in processed_stream:
        # Convert to SSE bytes to see what the client gets
        from src.core.domain.streaming.streaming_content import StreamingContent
        
        # resp is ProcessedResponse
        # We need to convert it to StreamingContent then to bytes
        content_obj = StreamingContent.from_raw(resp)
        sse_bytes = content_obj.to_bytes()
        sse_str = sse_bytes.decode()
        print(f"SSE Output:\n{sse_str}")
        
        if "reasoning_content" in sse_str:
            print("SUCCESS: reasoning_content found in SSE")
        else:
            print("FAILURE: reasoning_content MISSING in SSE")
            
        if "reasoning" in sse_str:
            print("SUCCESS: reasoning alias found in SSE")
        else:
            print("INFO: reasoning alias missing")

if __name__ == "__main__":
    asyncio.run(test_full_pipeline_reasoning())
