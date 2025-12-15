from src.loop_detection.hasher import ContentHasher


def test_content_hasher_hash_consistency() -> None:
    hasher = ContentHasher()
    content1 = "hello world"
    content2 = "hello world"
    content3 = "another string"

    hash1 = hasher.hash(content1)
    hash2 = hasher.hash(content2)
    hash3 = hasher.hash(content3)

    assert hash1 == hash2
    assert hash1 != hash3


def test_content_hasher_empty_string() -> None:
    hasher = ContentHasher()
    content = ""
    expected_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"  # SHA256 hash of empty string
    assert hasher.hash(content) == expected_hash


def test_content_hasher_different_case() -> None:
    hasher = ContentHasher()
    content_lower = "teststring"
    content_upper = "TESTSTRING"

    hash_lower = hasher.hash(content_lower)
    hash_upper = hasher.hash(content_upper)

    assert hash_lower != hash_upper  # Case matters for hash


def test_content_hasher_unicode_characters() -> None:
    hasher = ContentHasher()
    content = "你好世界"  # Hello world in Chinese
    hash_unicode = hasher.hash(content)
    assert len(hash_unicode) == 64  # SHA256 produces 64-char hex string
    # Cannot assert specific hash without pre-calculating, but ensure it runs without error
    assert isinstance(hash_unicode, str)
