import json
from src.core.domain.streaming.parsing.sse_bytes_parser import SSEBytesParser

parser = SSEBytesParser()
test_payload = b'data: {"message": "hello", "choices": [{"delta": {"content": "world"}}]}'

print("Testing payload:", test_payload.decode())

# Add debug to see what's being parsed
def _validate_json_depth_debug(obj, current_depth, max_depth=100):
    print(f"Validating depth: {current_depth}, type: {type(obj)}")
    if current_depth >= max_depth:
        raise ValueError(f"JSON depth {current_depth} exceeds maximum {max_depth}")
    
    if isinstance(obj, dict):
        for key, value in obj.items():
            print(f"  Dict key: {key}, value type: {type(value)}")
            _validate_json_depth_debug(value, current_depth + 1, max_depth)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            print(f"  List index: {i}, item type: {type(item)}")
            _validate_json_depth_debug(item, current_depth + 1, max_depth)

# Test our depth function
parsed = json.loads(test_payload[6:])  # Remove "data: "
print("Parsed object:", parsed)
_validate_json_depth_debug(parsed, 0)

# Test with the parser
try:
    result = parser.parse(test_payload)
    print("Parser result:", result.content)
except Exception as e:
    print("Parser error:", e)