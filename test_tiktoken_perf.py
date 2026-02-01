import tiktoken
import time
import json
import logging
import re

encoding = tiktoken.get_encoding("cl100k_base")
text = "hello " * 170000

start = time.monotonic()
tokens = encoding.encode(text)
end = time.monotonic()

print(f"Tiktoken Time: {end - start:.3f}s")

# Test JSON dumps
data = {"model": "gpt-4", "messages": [{"role": "user", "content": text}]}

start = time.monotonic()
json_str = json.dumps(data, sort_keys=True)
end = time.monotonic()

print(f"JSON dumps (sorted): {end - start:.3f}s")

# Test redaction
from src.core.common.logging_utils import ApiKeyRedactionFilter

# Simulate a lot of API keys to make it slow
api_keys = [f"sk-proj-{i:032x}" for i in range(100)]
redactor = ApiKeyRedactionFilter(api_keys=api_keys)

start = time.monotonic()
sanitized = redactor._sanitize(data)
end = time.monotonic()

print(f"Redaction Time: {end - start:.3f}s")
