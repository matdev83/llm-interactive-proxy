from enum import Enum


class MultimodalInputType(str, Enum):
    IMAGE = "image"
    PDF = "pdf"
    AUDIO = "audio"
    VIDEO = "video"
    TEXT = "text"


# Registry of supported MIME types for each input type
MIME_TYPES = {
    MultimodalInputType.IMAGE: [
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/heic",
        "image/heif",
    ],
    MultimodalInputType.PDF: [
        "application/pdf",
    ],
    MultimodalInputType.AUDIO: [
        "audio/wav",
        "audio/mp3",
        "audio/aiff",
        "audio/aac",
        "audio/ogg",
        "audio/flac",
    ],
    MultimodalInputType.VIDEO: [
        "video/mp4",
        "video/mpeg",
        "video/mov",
        "video/avi",
        "video/x-flv",
        "video/mpg",
        "video/webm",
        "video/wmv",
        "video/3gpp",
    ],
    MultimodalInputType.TEXT: [
        "text/plain",
        "text/csv",
        "text/html",
        "text/markdown",
        "text/xml",
        "application/json",
    ],
}
