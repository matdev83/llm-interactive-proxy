
import json
from src.core.domain.chat import CanonicalStreamChunk, StreamingChatCompletionChoice, StreamingChatCompletionChoiceDelta
from src.core.domain.translators.openai.streaming import from_domain_to_openai_stream_chunk

def test_reasoning_in_openai_stream():
    delta = StreamingChatCompletionChoiceDelta(
        role="assistant",
        content="Final answer.",
        reasoning_content="I am thinking..."
    )
    choice = StreamingChatCompletionChoice(
        index=0,
        delta=delta,
        finish_reason=None
    )
    chunk = CanonicalStreamChunk(
        id="test-id",
        object="chat.completion.chunk",
        created=123456789,
        model="test-model",
        choices=[choice]
    )
    
    openai_chunk = from_domain_to_openai_stream_chunk(chunk)
    print(f"OpenAI Chunk Delta: {json.dumps(openai_chunk['choices'][0]['delta'], indent=2)}")
    
    delta_out = openai_chunk['choices'][0]['delta']
    if "reasoning_content" in delta_out:
        print("SUCCESS: reasoning_content found")
    else:
        print("FAILURE: reasoning_content MISSING")
        
    if "reasoning" in delta_out:
        print("SUCCESS: reasoning alias found")
    else:
        print("INFO: reasoning alias missing (optional but good for compatibility)")

if __name__ == "__main__":
    test_reasoning_in_openai_stream()
