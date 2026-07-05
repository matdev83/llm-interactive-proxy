import unittest

from src.core.domain.chat import CanonicalStreamChunk
from src.core.domain.translation import Translation


class TestOpenaiToDomainStreamChunkReasoningSummary(unittest.TestCase):
    """Coverage for recognizing ``delta.reasoning_summary`` (Codex Responses stream).

    Codex streams reasoning as ``reasoning_summary`` deltas with ``content`` and
    ``reasoning_content`` set to null. The OpenAI stream translator must surface
    that text through the existing ``reasoning_content`` / ``reasoning`` contract
    while preserving the original ``reasoning_summary`` field, so downstream
    meaningful-output detection and client forwarding treat it as visible reasoning
    instead of an empty stream.
    """

    def test_reasoning_summary_surfaces_as_reasoning_content_and_reasoning(self):
        openai_chunk = {
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

        result = Translation.openai_to_domain_stream_chunk(openai_chunk)

        self.assertIsInstance(result, CanonicalStreamChunk)
        delta = result.choices[0].delta
        self.assertEqual(delta.reasoning_content, "Planning design updates")
        self.assertEqual(delta.reasoning, "Planning design updates")
        self.assertEqual(delta.reasoning_summary, "Planning design updates")

    def test_reasoning_summary_does_not_override_existing_reasoning_content(self):
        # When both ``reasoning_content`` and ``reasoning_summary`` are present,
        # the explicit ``reasoning_content`` value wins and ``reasoning`` mirrors it.
        openai_chunk = {
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

        result = Translation.openai_to_domain_stream_chunk(openai_chunk)
        delta = result.choices[0].delta
        self.assertEqual(delta.reasoning_content, "primary reasoning")
        self.assertEqual(delta.reasoning, "primary reasoning")

    def test_empty_reasoning_summary_is_not_surfaced(self):
        openai_chunk = {
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

        result = Translation.openai_to_domain_stream_chunk(openai_chunk)
        delta = result.choices[0].delta
        self.assertIsNone(delta.reasoning_content)


if __name__ == "__main__":
    unittest.main()
