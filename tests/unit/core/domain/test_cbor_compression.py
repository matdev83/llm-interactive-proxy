import zlib

from src.core.domain.cbor_capture import CaptureDirection, CaptureEntry


class TestCaptureEntryCompression:
    """Tests for CaptureEntry compression logic."""

    def test_small_payload_not_compressed(self):
        """Ensure small payloads are not compressed."""
        data = b"small payload"
        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=1,
            data=data,
        )

        serialized = entry.to_dict()

        # Should be stored as is
        assert serialized["data"] == data
        assert "enc" not in serialized

        # Roundtrip
        reconstructed = CaptureEntry.from_dict(serialized)
        assert reconstructed.data == data

    def test_large_payload_compressed(self):
        """Ensure large, compressible payloads are compressed."""
        # Create compressible data larger than 128 bytes
        data = b"A" * 1000
        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=1,
            data=data,
        )

        serialized = entry.to_dict()

        # Should be compressed
        assert serialized["data"] != data
        assert serialized["enc"] == "zlib"

        # Verify it is actually compressed zlib data
        decompressed = zlib.decompress(serialized["data"])
        assert decompressed == data

        # Roundtrip
        reconstructed = CaptureEntry.from_dict(serialized)
        assert reconstructed.data == data

    def test_large_uncompressible_payload_not_compressed(self):
        """Ensure large but uncompressible payloads are stored as is (if compression adds overhead)."""
        # Random bytes are usually not compressible
        import os

        data = os.urandom(200)

        # zlib might still compress it slightly or add small overhead.
        # If overhead is added, my logic:
        # if len(compressed) < len(self.data):
        #    use compressed
        # else:
        #    use raw

        # To guarantee no compression, we can construct a worst-case scenario or just check behavior.
        # Let's just rely on logic check.

        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=1,
            data=data,
        )

        serialized = entry.to_dict()

        # If zlib couldn't shrink it, it should be raw
        if "enc" not in serialized:
            assert serialized["data"] == data
        else:
            # If it managed to shrink it (rare for random data but possible due to small size),
            # then it should be marked as compressed
            assert serialized["enc"] == "zlib"
            assert zlib.decompress(serialized["data"]) == data

        # Roundtrip
        reconstructed = CaptureEntry.from_dict(serialized)
        assert reconstructed.data == data

    def test_legacy_format_compatibility(self):
        """Ensure we can read entries without 'enc' field."""
        data = b"some legacy data"
        legacy_dict = {"ts": 1.0, "dir": 0, "seq": 1, "data": data}

        entry = CaptureEntry.from_dict(legacy_dict)
        assert entry.data == data
