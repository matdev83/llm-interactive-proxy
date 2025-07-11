"""
Pydantic models for Google Gemini API request/response structures.
These models match the official Gemini API format for compatibility.
"""
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class HarmCategory(str, Enum):
    """Harm categories for safety settings."""
    HARM_CATEGORY_UNSPECIFIED = "HARM_CATEGORY_UNSPECIFIED"
    HARM_CATEGORY_DEROGATORY = "HARM_CATEGORY_DEROGATORY"
    HARM_CATEGORY_TOXICITY = "HARM_CATEGORY_TOXICITY"
    HARM_CATEGORY_VIOLENCE = "HARM_CATEGORY_VIOLENCE"
    HARM_CATEGORY_SEXUAL = "HARM_CATEGORY_SEXUAL"
    HARM_CATEGORY_MEDICAL = "HARM_CATEGORY_MEDICAL"
    HARM_CATEGORY_DANGEROUS = "HARM_CATEGORY_DANGEROUS"
    HARM_CATEGORY_HARASSMENT = "HARM_CATEGORY_HARASSMENT"
    HARM_CATEGORY_HATE_SPEECH = "HARM_CATEGORY_HATE_SPEECH"
    HARM_CATEGORY_SEXUALLY_EXPLICIT = "HARM_CATEGORY_SEXUALLY_EXPLICIT"
    HARM_CATEGORY_DANGEROUS_CONTENT = "HARM_CATEGORY_DANGEROUS_CONTENT"
    HARM_CATEGORY_CIVIC_INTEGRITY = "HARM_CATEGORY_CIVIC_INTEGRITY"


class HarmBlockThreshold(str, Enum):
    """Harm block thresholds for safety settings."""
    HARM_BLOCK_THRESHOLD_UNSPECIFIED = "HARM_BLOCK_THRESHOLD_UNSPECIFIED"
    BLOCK_LOW_AND_ABOVE = "BLOCK_LOW_AND_ABOVE"
    BLOCK_MEDIUM_AND_ABOVE = "BLOCK_MEDIUM_AND_ABOVE"
    BLOCK_ONLY_HIGH = "BLOCK_ONLY_HIGH"
    BLOCK_NONE = "BLOCK_NONE"


class HarmProbability(str, Enum):
    """Harm probability levels."""
    HARM_PROBABILITY_UNSPECIFIED = "HARM_PROBABILITY_UNSPECIFIED"
    NEGLIGIBLE = "NEGLIGIBLE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class FinishReason(str, Enum):
    """Finish reasons for candidate responses."""
    FINISH_REASON_UNSPECIFIED = "FINISH_REASON_UNSPECIFIED"
    STOP = "STOP"
    MAX_TOKENS = "MAX_TOKENS"
    SAFETY = "SAFETY"
    RECITATION = "RECITATION"
    TOOL_CALLS = "TOOL_CALLS"
    FUNCTION_CALL = "FUNCTION_CALL"
    OTHER = "OTHER"


class SafetySetting(BaseModel):
    """Safety setting for a specific harm category."""
    category: HarmCategory
    threshold: HarmBlockThreshold


class SafetyRating(BaseModel):
    """Safety rating for a specific harm category."""
    category: HarmCategory
    probability: HarmProbability
    blocked: Optional[bool] = None


class Blob(BaseModel):
    """Raw bytes data with MIME type."""
    mime_type: str
    data: str  # Base64 encoded data


class FileData(BaseModel):
    """Reference to a file uploaded via the File API."""
    mime_type: str
    file_uri: str


class Part(BaseModel):
    """A part of a content message."""
    text: Optional[str] = None
    inline_data: Optional[Blob] = None
    file_data: Optional[FileData] = None

    def model_post_init(self, __context: Any) -> None:
        """Ensure exactly one field is set."""
        fields_set = sum(
            [
                self.text is not None,
                self.inline_data is not None,
                self.file_data is not None,
            ]
        )
        if fields_set > 1:
            raise ValueError(
                "Exactly one of text, inline_data, or file_data must be set"
            )


class Content(BaseModel):
    """Content of a conversation turn."""
    parts: List[Part]
    role: Optional[str] = None  # "user", "model", or "function"


class GenerationConfig(BaseModel):
    """Configuration options for model generation."""
    model_config = {"populate_by_name": True}

    stop_sequences: Optional[List[str]] = Field(None, alias="stopSequences")
    response_mime_type: Optional[str] = Field(None, alias="responseMimeType")
    response_schema: Optional[Dict[str, Any]] = Field(None, alias="responseSchema")
    candidate_count: Optional[int] = Field(None, alias="candidateCount")
    max_output_tokens: Optional[int] = Field(None, alias="maxOutputTokens")
    temperature: Optional[float] = None
    top_p: Optional[float] = Field(None, alias="topP")
    top_k: Optional[int] = Field(None, alias="topK")


class GenerateContentRequest(BaseModel):
    """Request for generating content with Gemini."""
    model_config = {"populate_by_name": True}

    contents: List[Content]
    tools: Optional[List[Dict[str, Any]]] = None
    tool_config: Optional[Dict[str, Any]] = Field(None, alias="toolConfig")
    safety_settings: Optional[List[SafetySetting]] = Field(None, alias="safetySettings")
    system_instruction: Optional[Content] = Field(None, alias="systemInstruction")
    generation_config: Optional[GenerationConfig] = Field(None, alias="generationConfig")
    cached_content: Optional[str] = Field(None, alias="cachedContent")


class PromptFeedback(BaseModel):
    """Feedback about the prompt."""
    block_reason: Optional[str] = None
    safety_ratings: Optional[List[SafetyRating]] = None


class CitationMetadata(BaseModel):
    """Citation metadata for generated content."""
    citation_sources: Optional[List[Dict[str, Any]]] = None


class Candidate(BaseModel):
    """A generated candidate response."""
    model_config = {"populate_by_name": True}

    content: Optional[Content] = None
    finish_reason: Optional[FinishReason] = Field(None, alias="finishReason")
    index: Optional[int] = None
    safety_ratings: Optional[List[SafetyRating]] = None
    citation_metadata: Optional[CitationMetadata] = None
    token_count: Optional[int] = None
    grounding_attributions: Optional[List[Dict[str, Any]]] = None


class UsageMetadata(BaseModel):
    """Usage metadata for the generation request."""
    model_config = {"populate_by_name": True}

    prompt_token_count: Optional[int] = Field(None, alias="promptTokenCount")
    candidates_token_count: Optional[int] = Field(None, alias="candidatesTokenCount")
    total_token_count: Optional[int] = Field(None, alias="totalTokenCount")
    cached_content_token_count: Optional[int] = Field(None, alias="cachedContentTokenCount")


class GenerateContentResponse(BaseModel):
    """Response from generating content with Gemini."""
    model_config = {"populate_by_name": True}

    candidates: Optional[List[Candidate]] = None
    prompt_feedback: Optional[PromptFeedback] = Field(None, alias="promptFeedback")
    usage_metadata: Optional[UsageMetadata] = Field(None, alias="usageMetadata")


class Model(BaseModel):
    """Information about a Gemini model."""
    name: str
    base_model_id: Optional[str] = None
    version: str
    display_name: str
    description: str
    input_token_limit: int
    output_token_limit: int
    supported_generation_methods: List[str]
    temperature: Optional[float] = None
    max_temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None


class ListModelsResponse(BaseModel):
    """Response from listing available models."""
    models: List[Model]
    next_page_token: Optional[str] = None


# Streaming response models
class GenerateContentStreamResponse(BaseModel):
    """Streaming response chunk from generating content."""
    candidates: Optional[List[Candidate]] = None
    prompt_feedback: Optional[PromptFeedback] = None
    usage_metadata: Optional[UsageMetadata] = None
