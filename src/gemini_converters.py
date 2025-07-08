"""
Converter functions between Gemini API format and OpenAI format.
These functions enable the proxy to accept Gemini API requests and convert them
to the internal OpenAI format used by existing backends.
"""
from typing import List, Dict, Any, Optional, Iterator
import json
from .models import (
    ChatCompletionRequest, ChatMessage, ChatCompletionResponse, ChatCompletionChoice, 
    ChatCompletionChoiceMessage, CompletionUsage
)
from .gemini_models import (
    GenerateContentRequest, GenerateContentResponse, Content, Part, Candidate,
    GenerationConfig, SafetySetting, UsageMetadata, Model, ListModelsResponse
)


def gemini_to_openai_messages(contents: List[Content]) -> List[ChatMessage]:
    """Convert Gemini contents to OpenAI messages format."""
    messages = []
    
    for content in contents:
        # Determine role mapping
        role = "user"  # Default role
        if content.role == "model":
            role = "assistant"
        elif content.role == "function":
            role = "function"
        elif content.role == "user" or content.role is None:
            role = "user"
        
        # Combine all text parts into a single message
        text_parts = []
        for part in content.parts:
            if part.text:
                text_parts.append(part.text)
            elif part.inline_data:
                # For now, we'll indicate that there's an image/file attachment
                # The actual handling of binary data would need more sophisticated processing
                text_parts.append(f"[Attachment: {part.inline_data.mime_type}]")
            elif part.file_data:
                text_parts.append(f"[File: {part.file_data.file_uri}]")
        
        if text_parts:
            message_content = "\n".join(text_parts)
            messages.append(ChatMessage(role=role, content=message_content))
    
    return messages


def openai_to_gemini_contents(messages: List[ChatMessage]) -> List[Content]:
    """Convert OpenAI messages to Gemini contents format."""
    contents = []
    
    for message in messages:
        # Determine role mapping
        role = "user"  # Default role
        if message.role == "assistant":
            role = "model"
        elif message.role == "function":
            role = "function"
        elif message.role in ["user", "system"]:
            role = "user"
        
        # Create content with text part
        if message.content:
            part = Part(text=message.content)
            content = Content(parts=[part], role=role)
            contents.append(content)
    
    return contents


def gemini_to_openai_request(gemini_request: GenerateContentRequest, model: str) -> ChatCompletionRequest:
    """Convert Gemini GenerateContentRequest to OpenAI ChatCompletionRequest."""
    messages = gemini_to_openai_messages(gemini_request.contents)
    
    # Handle system instruction
    if gemini_request.system_instruction:
        system_messages = gemini_to_openai_messages([gemini_request.system_instruction])
        for msg in system_messages:
            msg.role = "system"
        messages = system_messages + messages
    
    # Convert generation config to OpenAI parameters
    max_tokens = None
    temperature = None
    top_p = None
    stop = None
    
    if gemini_request.generation_config:
        config = gemini_request.generation_config
        max_tokens = config.max_output_tokens
        temperature = config.temperature
        top_p = config.top_p
        stop = config.stop_sequences
    
    return ChatCompletionRequest(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        stop=stop,
        stream=False  # Will be set separately for streaming requests
    )


def openai_to_gemini_response(openai_response: ChatCompletionResponse) -> GenerateContentResponse:
    """Convert OpenAI ChatCompletionResponse to Gemini GenerateContentResponse."""
    candidates = []
    
    for choice in openai_response.choices:
        # Convert choice to candidate
        content = None
        if choice.message and choice.message.content:
            part = Part(text=choice.message.content)
            content = Content(parts=[part], role="model")
        
        # Map finish reason
        finish_reason = None
        if choice.finish_reason == "stop":
            finish_reason = "STOP"
        elif choice.finish_reason == "length":
            finish_reason = "MAX_TOKENS"
        elif choice.finish_reason == "content_filter":
            finish_reason = "SAFETY"
        
        candidate = Candidate(
            content=content,
            finish_reason=finish_reason,
            index=choice.index
        )
        candidates.append(candidate)
    
    # Convert usage information
    usage_metadata = None
    if openai_response.usage:
        usage_metadata = UsageMetadata(
            prompt_token_count=openai_response.usage.prompt_tokens,
            candidates_token_count=openai_response.usage.completion_tokens,
            total_token_count=openai_response.usage.total_tokens
        )
    
    return GenerateContentResponse(
        candidates=candidates,
        usage_metadata=usage_metadata
    )


def openai_to_gemini_stream_chunk(chunk_data: str) -> str:
    """Convert OpenAI streaming chunk to Gemini streaming format."""
    try:
        # Parse the OpenAI chunk
        if chunk_data.startswith("data: "):
            chunk_data = chunk_data[6:]
        
        if chunk_data.strip() == "[DONE]":
            return "data: [DONE]\n\n"
        
        openai_chunk = json.loads(chunk_data)
        
        # Convert to Gemini format
        candidates = []
        if "choices" in openai_chunk:
            for choice in openai_chunk["choices"]:
                content = None
                if "delta" in choice and "content" in choice["delta"] and choice["delta"]["content"]:
                    part = Part(text=choice["delta"]["content"])
                    content = Content(parts=[part], role="model")
                
                finish_reason = None
                if choice.get("finish_reason") == "stop":
                    finish_reason = "STOP"
                elif choice.get("finish_reason") == "length":
                    finish_reason = "MAX_TOKENS"
                
                candidate = Candidate(
                    content=content,
                    finish_reason=finish_reason,
                    index=choice.get("index", 0)
                )
                candidates.append(candidate)
        
        gemini_chunk = {
            "candidates": [candidate.model_dump(exclude_none=True, by_alias=True) for candidate in candidates]
        }
        
        return f"data: {json.dumps(gemini_chunk)}\n\n"
    
    except Exception:
        # If parsing fails, return empty chunk
        return "data: {}\n\n"


def openai_models_to_gemini_models(openai_models: List[Dict[str, Any]]) -> ListModelsResponse:
    """Convert OpenAI models list to Gemini models format."""
    gemini_models = []
    
    for model_data in openai_models:
        model_id = model_data.get("id", "")
        
        # Create Gemini-style model entry
        gemini_model = Model(
            name=f"models/{model_id}",
            base_model_id=model_id,
            version="001",  # Default version
            display_name=model_id.replace("-", " ").title(),
            description=f"Model {model_id} via LLM Interactive Proxy",
            input_token_limit=32768,  # Default reasonable limit
            output_token_limit=4096,  # Default reasonable limit
            supported_generation_methods=["generateContent", "streamGenerateContent"],
            temperature=1.0,
            max_temperature=2.0,
            top_p=1.0,
            top_k=40
        )
        gemini_models.append(gemini_model)
    
    return ListModelsResponse(models=gemini_models)


def extract_model_from_gemini_path(path: str) -> str:
    """Extract model name from Gemini API path like /v1beta/models/gemini-pro:generateContent."""
    # Path format: /v1beta/models/{model}:generateContent or /v1beta/models/{model}:streamGenerateContent
    if "/models/" in path:
        # Extract the part between /models/ and the next :
        parts = path.split("/models/")[1]
        model = parts.split(":")[0]
        return model
    return "gemini-pro"  # Default fallback


def is_streaming_request(path: str) -> bool:
    """Check if the request is for streaming based on the path."""
    return ":streamGenerateContent" in path 