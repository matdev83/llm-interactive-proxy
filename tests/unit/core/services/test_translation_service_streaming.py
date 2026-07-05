import unittest

from src.core.services.translation_service_streaming import (
    dict_to_canonical_stream_chunk,
)


class TestDictToCanonicalStreamChunkReasoningSummary(unittest.TestCase):
    """Coverage for ``reasoning_summary`` normalization on the responses stream path.

    The openai-codex backend streams reasoning as ``reasoning_summary`` deltas
    (produced by the Responses translator). ``dict_to_canonical_stream_chunk`` is
    the shared dict -> CanonicalStreamChunk converter on that path; it must surface
    ``reasoning_summary`` through the existing ``reasoning_content`` / ``reasoning``
    contract so downstream meaningful-output detection and client forwarding treat
    it as visible reasoning instead of an empty stream.
    """

    def test_reasoning_summary_surfaces_as_reasoning_content_and_reasoning(self):
        chunk_dict = {
            "id": "resp_summary",
            "object": "response.chunk",
            "created": 1783200524,
            "model": "unknown",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "content": None,
                        "reasoning_content": None,
                        "reasoning_summary": "Planning design updates",
                    },
                    "finish_reason": None,
                }
            ],
        }

        result = dict_to_canonical_stream_chunk(chunk_dict)

        delta = result.choices[0].delta
        self.assertEqual(delta.reasoning_content, "Planning design updates")
        self.assertEqual(delta.reasoning, "Planning design updates")
        self.assertEqual(delta.reasoning_summary, "Planning design updates")

    def test_explicit_reasoning_content_wins_over_reasoning_summary(self):
        chunk_dict = {
            "id": "resp_both",
            "object": "response.chunk",
            "created": 1783200524,
            "model": "unknown",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "reasoning_content": "primary reasoning",
                        "reasoning_summary": "summary text",
                    },
                    "finish_reason": None,
                }
            ],
        }

        result = dict_to_canonical_stream_chunk(chunk_dict)

        delta = result.choices[0].delta
        self.assertEqual(delta.reasoning_content, "primary reasoning")

    def test_empty_reasoning_summary_is_not_surfaced(self):
        chunk_dict = {
            "id": "resp_empty_summary",
            "object": "response.chunk",
            "created": 1783200524,
            "model": "unknown",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "content": None,
                        "reasoning_content": None,
                        "reasoning_summary": "",
                    },
                    "finish_reason": None,
                }
            ],
        }

        result = dict_to_canonical_stream_chunk(chunk_dict)

        delta = result.choices[0].delta
        self.assertIsNone(delta.reasoning_content)

    def test_content_chunk_is_unaffected(self):
        chunk_dict = {
            "id": "resp_content",
            "object": "response.chunk",
            "created": 1783200524,
            "model": "unknown",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "Hello"},
                    "finish_reason": None,
                }
            ],
        }

        result = dict_to_canonical_stream_chunk(chunk_dict)

        delta = result.choices[0].delta
        self.assertEqual(delta.content, "Hello")
        self.assertIsNone(delta.reasoning_content)


if __name__ == "__main__":
    unittest.main()
