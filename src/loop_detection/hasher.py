import hashlib


class ContentHasher:
    """Provides methods for generating hashes of content."""

    def hash(self, content: str) -> str:
        """Generates a SHA256 hash of the given content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
