"""Debug script to verify SSE message splitting."""

# Simulate two SSE messages in a single HTTP chunk
http_chunk = """data: {"choices": [{"delta": {"content": "\\n"}}]}

data: {"choices": [{"delta": {"content": "-"}}]}

"""

print(f"Input HTTP chunk (repr): {http_chunk!r}")
print(f"Input HTTP chunk length: {len(http_chunk)}")

# Simulate iter_sse_messages
buffer = ""
separator = "\n\n"
events = []

buffer += http_chunk

while True:
    if separator in buffer:
        event, buffer = buffer.split(separator, 1)
        print(f"Split: event={event!r}, remaining_buffer={buffer!r}")
        if event:
            events.append(event + separator)
    else:
        break

print(f"\nTotal events: {len(events)}")
for i, event in enumerate(events):
    print(f"Event {i}: {event!r}")
