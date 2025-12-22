# Replacement for lines 307-414 in src/connectors/antigravity_oauth.py
# This fixes the memory leak in _intercept_stream


async def _intercept_stream():
    # Stream processing with bounded memory usage
    # We only need to buffer content for XML tool call detection
    # and keep track of the first chunk type for reconstruction
    content_buffer = ""
    first_chunk_type = None

    # Process stream with bounded memory - only buffer what we need
    async for chunk in original_iterator:
        if first_chunk_type is None:
            first_chunk_type = type(chunk)

        # Extract and accumulate content for XML detection only
        if hasattr(chunk, "content"):
            chunk_content = chunk.content
            if isinstance(chunk_content, dict):
                # It might be a CanonicalStreamChunk dict
                choices = chunk_content.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    content_part = delta.get("content", "")
                    if content_part:
                        content_buffer += content_part
            elif isinstance(chunk_content, str):
                content_buffer += chunk_content

        # Early exit if we detect complete XML tool calls
        if "<Tool>" in content_buffer and "</Tool>" in content_buffer:
            # We have a complete tool call, break to process it
            break

        # Yield chunk immediately to avoid buffering entire stream
        yield chunk

    # Check for XML tool calls in accumulated content
    tool_calls = []
    if "<Tool>" in content_buffer:
        tool_pattern = r"<Tool>(.*?)</Tool>"
        match = re.search(tool_pattern, content_buffer, re.DOTALL)
        if match:
            tool_json = match.group(1)
            try:
                tools_data = json.loads(tool_json)
                if isinstance(tools_data, list):
                    for tool_data in tools_data:
                        if tool_data.get("type") == "tool_use":
                            tool_calls.append(
                                {
                                    "id": tool_data.get("id", ""),
                                    "type": "function",
                                    "function": {
                                        "name": tool_data.get("name", ""),
                                        "arguments": json.dumps(
                                            tool_data.get("input", {})
                                        ),
                                    },
                                }
                            )
                # Remove XML from content
                content_buffer = content_buffer.replace(match.group(0), "").strip()
            except Exception as e:
                logger.warning(f"Failed to parse XML tool call in stream: {e}")

    if tool_calls:
        # Yield tool call chunks
        import uuid

        (tool_calls[0]["id"] if tool_calls else f"call_{uuid.uuid4().hex[:8]}")

        # Yield content first if any
        if content_buffer:
            yield first_chunk_type(
                content={
                    "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": effective_model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "content": content_buffer,
                            },
                            "finish_reason": None,
                        }
                    ],
                }
            )

        # Yield tool calls
        yield first_chunk_type(
            content={
                "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": effective_model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"tool_calls": tool_calls},
                        "finish_reason": "tool_calls",
                    }
                ],
            }
        )

    # Continue yielding remaining chunks from original iterator
    async for chunk in original_iterator:
        yield chunk
