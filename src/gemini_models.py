"""
Pydantic models for Google Gemini API request/response structures.
These models match the official Gemini API format for compatibility.
"""

from enum import Enum
from typing import Any

from pydantic import Field

from src.core.interfaces.model_bases import DomainModel


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


class SafetySetting(DomainModel):
    """Safety setting for a specific harm category."""

    category: HarmCategory
    threshold: HarmBlockThreshold


class SafetyRating(DomainModel):
    """Safety rating for a specific harm category."""

    category: HarmCategory
    probability: HarmProbability
    blocked: bool | None = None


class Blob(DomainModel):
    """Raw bytes data with MIME type."""

    mime_type: str
    data: str  # Base64 encoded data


class FileData(DomainModel):
    """Reference to a file uploaded via the File API."""

    mime_type: str
    file_uri: str


class Part(DomainModel):
    """A part of a content message.

    Extended to support Gemini function calling protocol via ``functionCall`` and
    ``functionResponse`` fields in addition to text and data parts.
    """

    model_config = {"populate_by_name": True}
    text: str | None = None
    inline_data: Blob | None = None
    file_data: FileData | None = None
    # Gemini tool-calling fields
    function_call: dict[str, Any] | None = Field(None, alias="functionCall")
    function_response: dict[str, Any] | None = Field(None, alias="functionResponse")

    def model_post_init(self, __context: Any) -> None:
        """Ensure only one kind of payload is present per part."""
        # Explicitly acknowledge unused __context to satisfy vulture
        _ = __context
        fields_set = sum(
            [
                self.text is not None,
                self.inline_data is not None,
                self.file_data is not None,
                self.function_call is not None,
                self.function_response is not None,
            ]
        )
        if fields_set > 1:
            raise ValueError(
                "Exactly one of text, inline_data, file_data, functionCall, or functionResponse must be set"
            )


class Content(DomainModel):
    """Content of a conversation turn."""

    parts: list[Part]
    role: str | None = None  # "user", "model", or "function"


class GenerationConfig(DomainModel):
    """Configuration options for model generation."""

    model_config = {"populate_by_name": True}

    stop_sequences: list[str] | None = Field(None, alias="stopSequences")
    response_mime_type: str | None = Field(None, alias="responseMimeType")
    response_schema: dict[str, Any] | None = Field(None, alias="responseSchema")
    candidate_count: int | None = Field(None, alias="candidateCount")
    max_output_tokens: int | None = Field(None, alias="maxOutputTokens")
    temperature: float | None = None
    top_p: float | None = Field(None, alias="topP")
    top_k: int | None = Field(None, alias="topK")


class GenerateContentRequest(DomainModel):
    """Request for generating content with Gemini."""

    model_config = {"populate_by_name": True}

    contents: list[Content]
    tools: list[dict[str, Any]] | None = None
    tool_config: dict[str, Any] | None = Field(None, alias="toolConfig")
    safety_settings: list[SafetySetting] | None = Field(None, alias="safetySettings")
    system_instruction: Content | None = Field(None, alias="systemInstruction")
    generation_config: GenerationConfig | None = Field(None, alias="generationConfig")
    cached_content: str | None = Field(None, alias="cachedContent")


class PromptFeedback(DomainModel):
    """Feedback about the prompt."""

    block_reason: str | None = None
    safety_ratings: list[SafetyRating] | None = None


class CitationMetadata(DomainModel):
    """Citation metadata for generated content."""

    citation_sources: list[dict[str, Any]] | None = None


class Candidate(DomainModel):
    """A generated candidate response."""

    model_config = {"populate_by_name": True}

    content: Content | None = None
    finish_reason: FinishReason | None = Field(None, alias="finishReason")
    index: int | None = None
    safety_ratings: list[SafetyRating] | None = None
    citation_metadata: CitationMetadata | None = None
    token_count: int | None = None
    grounding_attributions: list[dict[str, Any]] | None = None


class UsageMetadata(DomainModel):
    """Usage metadata for the generation request."""

    model_config = {"populate_by_name": True}

    prompt_token_count: int | None = Field(None, alias="promptTokenCount")
    candidates_token_count: int | None = Field(None, alias="candidatesTokenCount")
    total_token_count: int | None = Field(None, alias="totalTokenCount")
    cached_content_token_count: int | None = Field(
        None, alias="cachedContentTokenCount"
    )


class GenerateContentResponse(DomainModel):
    """Response from generating content with Gemini."""

    model_config = {"populate_by_name": True}

    candidates: list[Candidate] | None = None
    prompt_feedback: PromptFeedback | None = Field(None, alias="promptFeedback")
    usage_metadata: UsageMetadata | None = Field(None, alias="usageMetadata")


class Model(DomainModel):
    """Information about a Gemini model."""

    name: str
    base_model_id: str | None = None
    version: str
    display_name: str
    description: str
    input_token_limit: int
    output_token_limit: int
    supported_generation_methods: list[str]
    temperature: float | None = None
    max_temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None


class ListModelsResponse(DomainModel):
    """Response from listing available models."""

    models: list[Model]
    next_page_token: str | None = None


# Streaming response models
class GenerateContentStreamResponse(DomainModel):
    """Streaming response chunk from generating content."""

    candidates: list[Candidate] | None = None
    prompt_feedback: PromptFeedback | None = None
    usage_metadata: UsageMetadata | None = None
