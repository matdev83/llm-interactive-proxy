import unittest

from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalChatResponse,
    ChatMessage,
    ImageURL,
    MessageContentPartImage,
    MessageContentPartText,
)
from src.core.domain.translation import Translation


class TestTranslationResponses(unittest.TestCase):
    def test_anthropic_to_domain_response_success(self):
        anthropic_response = {
            "id": "msg_01A0QnE4S7rD8nSW2C9d9gM1",
            "type": "message",
            "role": "assistant",
            "model": "claude-3-opus-20240229",
            "content": [
                {
                    "type": "text",
                    "text": "Hello! I'm Claude, a large language model from Anthropic.",
                }
            ],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 25},
        }

        result = Translation.anthropic_to_domain_response(anthropic_response)

        self.assertIsInstance(result, CanonicalChatResponse)
        self.assertEqual(result.id, "msg_01A0QnE4S7rD8nSW2C9d9gM1")
        self.assertEqual(result.model, "claude-3-opus-20240229")
        self.assertEqual(len(result.choices), 1)
        self.assertEqual(
            result.choices[0].message.content,
            "Hello! I'm Claude, a large language model from Anthropic.",
        )
        self.assertEqual(result.choices[0].finish_reason, "end_turn")
        self.assertIsNotNone(result.usage)
        if result.usage:
            self.assertEqual(result.usage["prompt_tokens"], 10)
            self.assertEqual(result.usage["completion_tokens"], 25)
            self.assertEqual(result.usage["total_tokens"], 35)

    def test_openai_to_domain_response_success(self):
        openai_response = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1677652288,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello from OpenAI."},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 8, "completion_tokens": 5, "total_tokens": 13},
        }

        result = Translation.openai_to_domain_response(openai_response)

        self.assertIsInstance(result, CanonicalChatResponse)
        self.assertEqual(result.id, "chatcmpl-123")
        self.assertEqual(result.model, "gpt-4")
        self.assertEqual(len(result.choices), 1)
        self.assertEqual(result.choices[0].message.content, "Hello from OpenAI.")
        self.assertEqual(result.choices[0].finish_reason, "stop")
        self.assertIsNotNone(result.usage)
        if result.usage:
            self.assertEqual(result.usage["prompt_tokens"], 8)
            self.assertEqual(result.usage["completion_tokens"], 5)
            self.assertEqual(result.usage["total_tokens"], 13)

    def test_gemini_to_domain_response_success(self):
        gemini_response = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Hello from Gemini."}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 12,
                "candidatesTokenCount": 6,
                "totalTokenCount": 18,
            },
        }

        result = Translation.gemini_to_domain_response(gemini_response)

        self.assertIsInstance(result, CanonicalChatResponse)
        self.assertTrue(result.id.startswith("chatcmpl-"))
        self.assertEqual(result.model, "gemini-pro")
        self.assertEqual(len(result.choices), 1)
        self.assertEqual(result.choices[0].message.content, "Hello from Gemini.")
        self.assertEqual(result.choices[0].finish_reason, "stop")
        self.assertIsNotNone(result.usage)
        if result.usage:
            self.assertEqual(result.usage["prompt_tokens"], 12)
            self.assertEqual(result.usage["completion_tokens"], 6)
            self.assertEqual(result.usage["total_tokens"], 18)

    def test_openai_to_domain_stream_chunk_success(self):
        openai_chunk = {
            "id": "chatcmpl-123",
            "object": "chat.completion.chunk",
            "created": 1677652288,
            "model": "gpt-4",
            "choices": [
                {"index": 0, "delta": {"content": "Hello"}, "finish_reason": None}
            ],
        }

        result = Translation.openai_to_domain_stream_chunk(openai_chunk)

        self.assertIsInstance(result, dict)
        self.assertEqual(result["id"], "chatcmpl-123")
        self.assertEqual(result["choices"][0]["delta"]["content"], "Hello")

    def test_gemini_to_domain_stream_chunk_success(self):
        gemini_chunk = {
            "candidates": [
                {
                    "content": {"parts": [{"text": " from Gemini."}]},
                    "finishReason": "STOP",
                }
            ]
        }

        result = Translation.gemini_to_domain_stream_chunk(gemini_chunk)

        self.assertIsInstance(result, dict)
        self.assertTrue(result["id"].startswith("chatcmpl-"))
        self.assertEqual(result["choices"][0]["delta"]["content"], " from Gemini.")
        self.assertEqual(result["choices"][0]["finish_reason"], "STOP")

    def test_anthropic_to_domain_stream_chunk_success(self):
        anthropic_chunk = {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hello"},
        }

        result = Translation.anthropic_to_domain_stream_chunk(anthropic_chunk)

        self.assertIsInstance(result, dict)
        self.assertTrue(result["id"].startswith("chatcmpl-"))
        self.assertEqual(result["choices"][0]["delta"]["content"], "Hello")

    def test_anthropic_to_domain_stream_chunk_invalid_input(self):
        result = Translation.anthropic_to_domain_stream_chunk("invalid")
        self.assertEqual(
            result, {"error": "Invalid chunk format: expected a dictionary"}
        )

    def test_from_domain_to_anthropic_request_with_system_message(self):
        request = CanonicalChatRequest(
            model="claude-3-opus-20240229",
            messages=[
                ChatMessage(role="system", content="You are a helpful assistant."),
                ChatMessage(role="user", content="Hello, world!"),
            ],
        )
        result = Translation.from_domain_to_anthropic_request(request)
        self.assertEqual(result["system"], "You are a helpful assistant.")
        self.assertEqual(len(result["messages"]), 1)
        self.assertEqual(result["messages"][0]["content"], "Hello, world!")

    def test_from_domain_to_anthropic_request_multimodal(self):
        request = CanonicalChatRequest(
            model="claude-3-opus-20240229",
            messages=[
                ChatMessage(
                    role="user",
                    content=[
                        MessageContentPartText(text="What is in this image?"),
                        MessageContentPartImage(
                            image_url=ImageURL(
                                url="data:image/jpeg;base64,SGVsbG8sIHdvcmxkIQ==",
                                detail=None,
                            )
                        ),
                    ],
                )
            ],
        )
        result = Translation.from_domain_to_anthropic_request(request)
        self.assertIsInstance(result["messages"][0]["content"], list)
        content_list = result["messages"][0]["content"]
        self.assertEqual(content_list[0]["type"], "text")
        self.assertEqual(content_list[1]["type"], "image")
        self.assertEqual(content_list[1]["source"]["data"], "SGVsbG8sIHdvcmxkIQ==")

    def test_from_domain_to_anthropic_request_with_tools(self):
        request = CanonicalChatRequest(
            model="claude-3-opus-20240229",
            messages=[ChatMessage(role="user", content="What is the weather in SF?")],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get the current weather",
                        "parameters": {
                            "type": "object",
                            "properties": {"location": {"type": "string"}},
                        },
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": "get_weather"}},
        )
        result = Translation.from_domain_to_anthropic_request(request)
        self.assertIn("tools", result)
        self.assertEqual(len(result["tools"]), 1)
        self.assertEqual(result["tools"][0]["function"]["name"], "get_weather")
        self.assertIn("tool_choice", result)
        self.assertEqual(result["tool_choice"]["function"]["name"], "get_weather")


if __name__ == "__main__":
    unittest.main()
