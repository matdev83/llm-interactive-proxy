import json

payload = '{"message": "hello", "choices": [{"delta": {"content": "world"}}]}'

def get_depth(obj, current_depth=0):
    if current_depth > 100:
        return current_depth
    
    if isinstance(obj, dict):
        max_child_depth = current_depth
        for value in obj.values():
            child_depth = get_depth(value, current_depth + 1)
            max_child_depth = max(max_child_depth, child_depth)
        return max_child_depth
    elif isinstance(obj, list):
        max_child_depth = current_depth
        for item in obj:
            child_depth = get_depth(item, current_depth + 1)
            max_child_depth = max(max_child_depth, child_depth)
        return max_child_depth
    else:
        return current_depth

parsed = json.loads(payload)
depth = get_depth(parsed)
print(f"Payload depth: {depth}")
print(f"Payload: {payload}")