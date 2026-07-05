import unittest

from src.core.common.openai_stream_reasoning import openai_dict_has_reasoning_output


class TestOpenaiDictHasReasoningOutput(unittest.TestCase):
    def test_delta_reasoning_content_detected(self) -> None:
        payload = {
            "choices": [{"index": 0, "delta": {"reasoning_content": "step by step"}}]
        }
        self.assertTrue(openai_dict_has_reasoning_output(payload))

    def test_delta_reasoning_summary_detected(self) -> None:
        payload = {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "content": None,
                        "reasoning_content": None,
                        "reasoning_summary": "Planning design updates",
                    },
                }
            ]
        }
        self.assertTrue(openai_dict_has_reasoning_output(payload))

    def test_message_reasoning_summary_detected(self) -> None:
        payload = {
            "choices": [
                {
                    "index": 0,
                    "message": {"reasoning_summary": "summary of reasoning"},
                }
            ]
        }
        self.assertTrue(openai_dict_has_reasoning_output(payload))

    def test_whitespace_reasoning_summary_not_detected(self) -> None:
        payload = {"choices": [{"index": 0, "delta": {"reasoning_summary": "   "}}]}
        self.assertFalse(openai_dict_has_reasoning_output(payload))

    def test_empty_reasoning_summary_not_detected(self) -> None:
        payload = {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "content": None,
                        "reasoning_content": None,
                        "reasoning_summary": "",
                    },
                }
            ]
        }
        self.assertFalse(openai_dict_has_reasoning_output(payload))

    def test_missing_choices_not_detected(self) -> None:
        self.assertFalse(openai_dict_has_reasoning_output({}))

    def test_empty_choices_not_detected(self) -> None:
        self.assertFalse(openai_dict_has_reasoning_output({"choices": []}))


if __name__ == "__main__":
    unittest.main()
