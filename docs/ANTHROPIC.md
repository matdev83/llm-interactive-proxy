# Anthropic API Compatibility

This proxy exposes a **compatibility shim** that allows Anthropic-style
`/v1/messages` requests to be served by any OpenAI-compatible backend.

Key points
-----------
1. **`/v1/messages` endpoint** – implemented in `src.main` and guarded by the
   `verify_anthropic_auth` dependency.
2. **Converter helpers** – `src/anthropic_converters.py` provides utilities to
   translate between Anthropic’s *messages* schema and OpenAI chat objects.
   • `anthropic_to_openai_request(...)`
   • `openai_to_anthropic_response(...)`
   • `openai_to_anthropic_stream_chunk(...)`
3. **Streaming support** – each SSE chunk from the OpenAI side is converted to
   the appropriate Anthropic `event: content_block_delta` / `message_delta`
   events so clients receive incremental updates.
4. **Usage accounting** – token counts from the OpenAI response are copied into
   the Anthropic `usage` section (`input_tokens`, `output_tokens`).
5. **Authentication** – provide your client key via the `x-api-key` header (the
   same value as `LLM_INTERACTIVE_PROXY_API_KEY`). Set
   `ANTHROPIC_API_KEY(_N)` env vars if you want to forward calls to Anthropic’s
   *real* API instead of translating them.

Example request
---------------
```bash
curl http://127.0.0.1:8000/v1/messages \
     -H "x-api-key: your-proxy-key" \
     -H "Content-Type: application/json" \
     -d '{
           "model": "claude-3-sonnet-20240229",
           "messages": [
             {"role": "user", "content": "Hello Claude!"}
           ]
         }'
```

The proxy forwards it to the default backend, converts the reply and returns
Anthropic-formatted JSON. 