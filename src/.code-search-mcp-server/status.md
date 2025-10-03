connectors/gemini.py [lines 211–217]
211 |                     async for chunk in processed_stream:
212 |                         # If JSON repair is enabled, the processor yields repaired JSON strings
213 |                         # or raw text. If disabled, it yields raw text.
214 |                         # Convert Gemini format to OpenAI format for consistency
215 |                         if chunk.startswith(("data: ", "id: ", ":")):
216 |                             yield ProcessedResponse(
217 |                                 content=self.translation_service.to_domain_stream_chunk(
agents.py [lines 22–41]
22 | def detect_frontend_api(request_path: str) -> str:
23 |     """
24 |     Detect the frontend API type based on the request path.
25 | 
26 |     Args:
27 |         request_path: The request path (e.g., "/v2/chat/completions", "/anthropic/v1/messages")
28 | 
29 |     Returns:
30 |         Frontend API type: "openai", "anthropic", or "gemini"
31 |     """
32 |     if request_path.startswith("/anthropic/"):
33 |         return "anthropic"
34 |     elif request_path.startswith("/v1beta/"):
35 |         return "gemini"
36 |     elif request_path.startswith("/v2/"):
37 |         # Legacy /v2/ endpoint
38 |         return "openai"
39 |     else:
40 |         # Default to OpenAI /v1/ for all other paths
41 |         return "openai"
agents.py [lines 93–117]
93 | def convert_cline_marker_to_openai_tool_call(content: str) -> dict:
94 |     """
95 |     Convert Cline marker to OpenAI tool call format.
96 |     Frontend-specific implementation for OpenAI API.
97 |     """
98 |     import json
99 |     import secrets
100 | 
101 |     # Extract content from marker
102 |     if content.startswith("__CLINE_TOOL_CALL_MARKER__") and content.endswith(
103 |         "__END_CLINE_TOOL_CALL_MARKER__"
104 |     ):
105 |         actual_content = content[
106 |             len("__CLINE_TOOL_CALL_MARKER__") : -len("__END_CLINE_TOOL_CALL_MARKER__")
107 |         ]
108 |     else:
109 |         actual_content = content
110 | 
111 |     return {
112 |         "id": f"call_{secrets.token_hex(12)}",
113 |         "type": "function",
114 |         "function": {
115 |             "name": "attempt_completion",
116 |             "arguments": json.dumps({"result": actual_content}),
117 |         },
118 |     }
agents.py [lines 181–200]
181 | def create_openai_attempt_completion_tool_call(content_lines: list[str]) -> dict:
182 |     """Return a fully-formed OpenAI tool-call dict for *attempt_completion*.
183 | 
184 |     The integration tests expect a helper that takes a list of **content**
185 |     strings (typically split lines from a command response) and converts them
186 |     into the exact structure produced by
187 |     `convert_cline_marker_to_openai_tool_call`.
188 | 
189 |     Parameters
190 |     ----------
191 |     content_lines : List[str]
192 |         Lines of text that constitute the *result* argument for the
193 |         *attempt_completion* function.
194 |     """
195 |     joined = "\n".join(content_lines)
196 |     # Re-use the existing conversion utility to stay DRY by wrapping the
197 |     # joined content in the special Cline marker pair that the converter
198 |     # recognises.
199 |     marker_wrapped = f"__CLINE_TOOL_CALL_MARKER__{joined}__END_CLINE_TOOL_CALL_MARKER__"
200 |     return convert_cline_marker_to_openai_tool_call(marker_wrapped)
