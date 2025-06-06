Analysis of Cline agent failure on 2025-06-06

The proxy logs show that requests were successfully forwarded to the Gemini
backend and received `HTTP/1.1 200 OK` responses. The `StreamingResponse`
object was returned without transport errors.

However, Gemini's streaming API does **not** emit data in the same
`text/event-stream` format used by OpenAI. The proxy forwards those chunks
verbatim, so the Cline extension cannot parse them correctly. As a result it
injects error messages such as:

```
[ERROR] You did not use a tool in your previous response! Please retry with a tool use.
Failure: I did not provide a response.
```

These strings are included by Cline in the following request, which causes the
model to focus on them rather than the user's prompt. When Cline communicates
directly with OpenAI or OpenRouter, the responses are in the expected format and
no error injection occurs.

No escaping or modification of tool tags takes place inside the proxy—the raw
Gemini stream is simply relayed. The behaviour difference arises from the
incompatibility between Gemini's response format and the client's expectations.
Either converting Gemini output to the OpenAI schema or using an OpenAI
compatible backend avoids the issue.

To make Gemini usable with existing OpenAI clients the backend connector
now translates the streaming JSON responses into proper `text/event-stream`
chunks matching the OpenAI format. Each Gemini update is parsed and
re-emitted as a standard chat completion chunk, with a final `[DONE]`
event terminating the stream.
