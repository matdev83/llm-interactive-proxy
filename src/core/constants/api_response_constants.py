"""Constants for API response values.

This module contains constants for common API response values to make tests
less fragile and more maintainable.
"""

# Content types
CONTENT_TYPE_JSON = "application/json"
CONTENT_TYPE_EVENT_STREAM = "text/event-stream"
CONTENT_TYPE_TEXT_PLAIN = "text/plain; charset=utf-8"

# API response object types
OBJECT_TYPE_LIST = "list"
OBJECT_TYPE_MODEL = "model"
OBJECT_TYPE_CHAT_COMPLETION = "chat.completion"
OBJECT_TYPE_CHAT_COMPLETION_CHUNK = "chat.completion.chunk"
OBJECT_TYPE_MESSAGE = "message"

# Common field names
FIELD_OBJECT = "object"
FIELD_ID = "id"
FIELD_MODEL = "model"
FIELD_CONTENT = "content"
FIELD_ROLE = "role"
FIELD_CHOICES = "choices"
FIELD_MESSAGE = "message"
FIELD_DELTA = "delta"
FIELD_FINISH_REASON = "finish_reason"
FIELD_STOP_REASON = "stop_reason"
FIELD_TYPE = "type"
FIELD_NAME = "name"
FIELD_TEXT = "text"
FIELD_PARTS = "parts"
FIELD_INLINE_DATA = "inline_data"
FIELD_MIME_TYPE = "mime_type"
FIELD_DATA = "data"
FIELD_SOURCE = "source"
FIELD_USAGE = "usage"
FIELD_ERROR = "error"

# Common role values
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"
ROLE_MODEL = "model"

# Common finish reasons
FINISH_REASON_STOP = "stop"
FINISH_REASON_LENGTH = "length"
FINISH_REASON_TOOL_CALLS = "tool_calls"
FINISH_REASON_END_TURN = "end_turn"
FINISH_REASON_MAX_TOKENS = "max_tokens"
FINISH_REASON_STOP_SEQUENCE = "stop_sequence"
FINISH_REASON_ERROR = "error"

# Common tool call types
TOOL_CALL_TYPE_FUNCTION = "function"

# Common model prefixes
MODEL_PREFIX_OPENAI = "openai/"
MODEL_PREFIX_ANTHROPIC = "anthropic/"
MODEL_PREFIX_GEMINI = "gemini/"
MODEL_PREFIX_OPENROUTER = "openrouter:"