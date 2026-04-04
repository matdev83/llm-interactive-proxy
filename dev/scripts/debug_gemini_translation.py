"""Debug script: inspect translation output for Gemini streaming and tool-call chunks."""
import json
import sys

sys.path.insert(0, ".")

from src.core.services.translation_service import TranslationService

ts = TranslationService()

print("=== Gemini streaming chunk translation ===\n")
streaming_chunks = [
    {"candidates": [{"content": {"parts": [{"text": "Hello"}], "role": "model"}, "finishReason": None, "index": 0}], "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 1}},
    {"candidates": [{"content": {"parts": [{"text": " world"}], "role": "model"}, "finishReason": "STOP", "index": 0}], "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2}},
]
def dump(obj):
    if hasattr(obj, "model_dump"):
        return json.dumps(obj.model_dump(), indent=2)
    try:
        return json.dumps(obj, indent=2)
    except TypeError:
        return repr(obj)

for i, chunk in enumerate(streaming_chunks):
    result = ts.to_domain_stream_chunk(chunk, "gemini")
    print(f"Chunk {i} type={type(result).__name__}: {dump(result)}")
    print("---")

print("\n=== Gemini tool-call chunk translation ===\n")
tool_chunk = {"candidates": [{"content": {"parts": [{"functionCall": {"name": "get_weather", "args": {"location": "Paris"}}}], "role": "model"}, "finishReason": "STOP", "index": 0}]}
result = ts.to_domain_stream_chunk(tool_chunk, "gemini")
print(f"Tool chunk type={type(result).__name__}: {dump(result)}")

print("\n=== Gemini non-streaming response translation ===\n")
non_streaming = {
    "candidates": [{"content": {"parts": [{"text": "Hello there"}], "role": "model"}, "finishReason": "STOP", "index": 0}],
    "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 3, "totalTokenCount": 8}
}
result2 = ts.to_domain_response(non_streaming, source_format="gemini")
print(f"Non-streaming type={type(result2).__name__}: {dump(result2)}")
