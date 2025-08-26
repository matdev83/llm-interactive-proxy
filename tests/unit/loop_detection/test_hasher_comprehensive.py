"""
Tests for ContentHasher.

This module provides comprehensive test coverage for the ContentHasher class.
"""

import hashlib

from src.loop_detection.hasher import ContentHasher


class TestContentHasher:
    """Tests for ContentHasher class."""

    def test_hasher_initialization(self) -> None:
        """Test ContentHasher initialization."""
        hasher = ContentHasher()
        assert hasher is not None

    def test_hash_basic_string(self) -> None:
        """Test hashing a basic string."""
        hasher = ContentHasher()
        content = "test content"

        result = hasher.hash(content)

        # Should be a valid SHA256 hash (64 characters, hex)
        assert isinstance(result, str)
        assert len(result) == 64
        assert result.isalnum()
        assert result.islower()  # hex should be lowercase

    def test_hash_empty_string(self) -> None:
        """Test hashing an empty string."""
        hasher = ContentHasher()

        result = hasher.hash("")

        # Should still produce a valid hash
        assert isinstance(result, str)
        assert len(result) == 64

        # Empty string should always produce the same hash
        result2 = hasher.hash("")
        assert result == result2

    def test_hash_unicode_content(self) -> None:
        """Test hashing Unicode content."""
        hasher = ContentHasher()
        unicode_content = "Hello, 世界! 🌍 Test content with émojis and ñoñäscii"

        result = hasher.hash(unicode_content)

        assert isinstance(result, str)
        assert len(result) == 64

        # Same content should produce same hash
        result2 = hasher.hash(unicode_content)
        assert result == result2

    def test_hash_consistency(self) -> None:
        """Test that identical content produces identical hashes."""
        hasher = ContentHasher()
        content = "identical content"

        result1 = hasher.hash(content)
        result2 = hasher.hash(content)
        result3 = hasher.hash(content)

        assert result1 == result2 == result3

    def test_hash_deterministic(self) -> None:
        """Test that the hash function is deterministic."""
        hasher = ContentHasher()
        content = "deterministic test"

        # Multiple calls should produce same result
        results = [hasher.hash(content) for _ in range(10)]
        assert all(r == results[0] for r in results)

    def test_hash_different_content_different_results(self) -> None:
        """Test that different content produces different hashes."""
        hasher = ContentHasher()

        content1 = "content one"
        content2 = "content two"
        content3 = "content three"

        result1 = hasher.hash(content1)
        result2 = hasher.hash(content2)
        result3 = hasher.hash(content3)

        # All should be different
        assert result1 != result2
        assert result1 != result3
        assert result2 != result3

    def test_hash_case_sensitivity(self) -> None:
        """Test that hash is case sensitive."""
        hasher = ContentHasher()

        content_lower = "hello world"
        content_upper = "HELLO WORLD"
        content_mixed = "Hello World"

        result_lower = hasher.hash(content_lower)
        result_upper = hasher.hash(content_upper)
        result_mixed = hasher.hash(content_mixed)

        # All should be different due to case differences
        assert result_lower != result_upper
        assert result_lower != result_mixed
        assert result_upper != result_mixed

    def test_hash_whitespace_sensitivity(self) -> None:
        """Test that hash is sensitive to whitespace."""
        hasher = ContentHasher()

        content1 = "hello world"
        content2 = "hello  world"  # extra space
        content3 = "helloworld"  # no space
        content4 = " hello world "  # leading/trailing spaces

        result1 = hasher.hash(content1)
        result2 = hasher.hash(content2)
        result3 = hasher.hash(content3)
        result4 = hasher.hash(content4)

        # All should be different due to whitespace differences
        results = [result1, result2, result3, result4]
        assert len(set(results)) == 4  # All unique

    def test_hash_newline_sensitivity(self) -> None:
        """Test that hash is sensitive to newlines."""
        hasher = ContentHasher()

        content_single = "line1\nline2"
        content_double = "line1\n\nline2"
        content_tabs = "line1\tline2"

        result_single = hasher.hash(content_single)
        result_double = hasher.hash(content_double)
        result_tabs = hasher.hash(content_tabs)

        # All should be different
        assert result_single != result_double
        assert result_single != result_tabs
        assert result_double != result_tabs

    def test_hash_special_characters(self) -> None:
        """Test hashing content with special characters."""
        hasher = ContentHasher()

        special_content = "!@#$%^&*()_+-=[]{}|;:,.<>?"

        result = hasher.hash(special_content)
        assert isinstance(result, str)
        assert len(result) == 64

        # Same content should produce same hash
        result2 = hasher.hash(special_content)
        assert result == result2

    def test_hash_numeric_content(self) -> None:
        """Test hashing numeric content."""
        hasher = ContentHasher()

        # Test various numeric representations
        content_int = "123456"
        content_float = "123.456"
        content_scientific = "1.23e-4"

        result_int = hasher.hash(content_int)
        result_float = hasher.hash(content_float)
        result_scientific = hasher.hash(content_scientific)

        # All should be different
        assert result_int != result_float
        assert result_int != result_scientific
        assert result_float != result_scientific

    def test_hash_json_like_content(self) -> None:
        """Test hashing JSON-like content."""
        hasher = ContentHasher()

        json_content = '{"key": "value", "number": 123, "array": [1, 2, 3]}'
        compact_json = '{"key":"value","number":123,"array":[1,2,3]}'

        result_json = hasher.hash(json_content)
        result_compact = hasher.hash(compact_json)

        # Should be different due to formatting differences
        assert result_json != result_compact

    def test_hash_binary_like_content(self) -> None:
        """Test hashing content that looks like binary data."""
        hasher = ContentHasher()

        binary_like = "\x00\x01\x02\x03\x04\x05"
        text_content = "text content"

        result_binary = hasher.hash(binary_like)
        result_text = hasher.hash(text_content)

        # Should be different
        assert result_binary != result_text

    def test_hash_very_long_content(self) -> None:
        """Test hashing very long content."""
        hasher = ContentHasher()

        # Create a very long string
        long_content = "x" * 10000

        result = hasher.hash(long_content)
        assert isinstance(result, str)
        assert len(result) == 64

        # Same long content should produce same hash
        result2 = hasher.hash(long_content)
        assert result == result2

    def test_hash_very_short_content(self) -> None:
        """Test hashing very short content."""
        hasher = ContentHasher()

        short_contents = ["a", "1", " ", ".", "中"]

        for content in short_contents:
            result = hasher.hash(content)
            assert isinstance(result, str)
            assert len(result) == 64

            # Same content should produce same hash
            result2 = hasher.hash(content)
            assert result == result2

    def test_hash_chunks_of_various_sizes(self) -> None:
        """Test hashing chunks of various sizes."""
        hasher = ContentHasher()

        base_content = "a" * 100
        hashes = []

        # Hash chunks of different sizes from the same base content
        for size in [1, 5, 10, 25, 50, 100]:
            chunk = base_content[:size]
            result = hasher.hash(chunk)
            hashes.append(result)

        # All hashes should be different (different content)
        assert len(set(hashes)) == len(hashes)

    def test_hash_algorithm_correctness(self) -> None:
        """Test that the hash algorithm produces correct SHA256."""
        hasher = ContentHasher()
        content = "test content"

        # Get our hasher result
        our_result = hasher.hash(content)

        # Calculate expected SHA256 directly
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()

        # Should match
        assert our_result == expected

    def test_hash_encoding_consistency(self) -> None:
        """Test that the hasher uses consistent UTF-8 encoding."""
        hasher = ContentHasher()

        # Test various Unicode characters
        unicode_chars = [
            "café",  # Latin with accent
            "naïve",  # Latin with diaeresis
            "北京",  # Chinese
            "العربية",  # Arabic
            "русский",  # Cyrillic
            "🌟⭐",  # Emoji
        ]

        for content in unicode_chars:
            result = hasher.hash(content)
            assert isinstance(result, str)
            assert len(result) == 64

            # Same content should produce same hash
            result2 = hasher.hash(content)
            assert result == result2

    def test_hash_performance_with_large_content(self) -> None:
        """Test that hashing performs reasonably with large content."""
        hasher = ContentHasher()

        # Test with various large sizes
        sizes = [1000, 10000, 100000]

        for size in sizes:
            large_content = "x" * size
            result = hasher.hash(large_content)

            assert isinstance(result, str)
            assert len(result) == 64

            # Same large content should produce same hash
            result2 = hasher.hash(large_content)
            assert result == result2

    def test_hash_empty_vs_whitespace_vs_null(self) -> None:
        """Test hash differences between empty, whitespace, and null-like."""
        hasher = ContentHasher()

        empty = ""
        space = " "
        tab = "\t"
        newline = "\n"
        multiple_spaces = "   "
        zero_width = "\u200b"  # Zero-width space

        contents = [empty, space, tab, newline, multiple_spaces, zero_width]
        results = [hasher.hash(content) for content in contents]

        # All should be different from each other
        assert len(set(results)) == len(results)

        # Empty string should always produce the same hash
        assert hasher.hash("") == hasher.hash("")

    def test_hash_object_instantiation(self) -> None:
        """Test that ContentHasher can be instantiated multiple times."""
        hasher1 = ContentHasher()
        hasher2 = ContentHasher()

        content = "test content"

        result1 = hasher1.hash(content)
        result2 = hasher2.hash(content)

        # Both should produce the same result
        assert result1 == result2

    def test_hash_reproducibility_across_instances(self) -> None:
        """Test that different instances produce the same hash for same content."""
        content = "reproducible content"

        # Create multiple instances
        hashers = [ContentHasher() for _ in range(5)]

        # All should produce the same hash
        results = [hasher.hash(content) for hasher in hashers]
        assert all(r == results[0] for r in results)
