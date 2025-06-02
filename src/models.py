from pydantic import BaseModel, Field
from typing import List, Optional, Union, Dict, Any

# For multimodal content parts
class MessageContentPartText(BaseModel):
    type: str = "text"
    text: str

class ImageURL(BaseModel):
    url: str # Should be a data URI (e.g., "data:image/jpeg;base64,...") or public URL
    detail: Optional[str] = Field(None, examples=["auto", "low", "high"])

class MessageContentPartImage(BaseModel):
    type: str = "image_url"
    image_url: ImageURL

# Extend with other multimodal types as needed (e.g., audio, video file, documents)
# For now, text and image are common starting points.
MessageContentPart = Union[MessageContentPartText, MessageContentPartImage]

class ChatMessage(BaseModel):
    role: str
    content: Union[str, List[MessageContentPart]]
    name: Optional[str] = None
    # tool_calls: Optional[List[Any]] = None # Future extension for tool/function calling
    # tool_call_id: Optional[str] = None   # Future extension for tool/function calling

class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    n: Optional[int] = None # Number of chat completion choices to generate
    stream: Optional[bool] = False
    stop: Optional[Union[str, List[str]]] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    logit_bias: Optional[Dict[str, float]] = None
    user: Optional[str] = None
    # Add other OpenAI parameters as needed, e.g., functions, tool_choice, tools

# We don't strictly need to model the OpenAI response if we're just proxying JSON/SSE.
# FastAPI handles serialization of dicts to JSON, and StreamingResponse handles SSE.