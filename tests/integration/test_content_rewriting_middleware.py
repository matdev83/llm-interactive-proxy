import json
import os
import shutil
import unittest
from unittest.mock import AsyncMock

from fastapi import Request
from src.core.app.middleware.content_rewriting_middleware import (
    ContentRewritingMiddleware,
)
from src.core.services.content_rewriter_service import ContentRewriterService
from starlette.background import BackgroundTask
from starlette.datastructures import Headers
from starlette.responses import Response, StreamingResponse


class TestContentRewritingMiddleware(unittest.TestCase):
    def setUp(self):
        self.test_config_dir = "test_config_middleware"
        os.makedirs(
            os.path.join(self.test_config_dir, "prompts", "system", "001"),
            exist_ok=True,
        )
        with open(
            os.path.join(
                self.test_config_dir, "prompts", "system", "001", "SEARCH.txt"
            ),
            "w",
        ) as f:
            f.write("original system")
        with open(
            os.path.join(
                self.test_config_dir, "prompts", "system", "001", "REPLACE.txt"
            ),
            "w",
        ) as f:
            f.write("rewritten system")

    def tearDown(self):
        shutil.rmtree(self.test_config_dir)

    def test_inbound_reply_rewriting(self):
        """Verify that inbound replies are rewritten correctly."""
        # Create a reply rule for this test
        os.makedirs(os.path.join(self.test_config_dir, "replies", "001"), exist_ok=True)
        with open(
            os.path.join(self.test_config_dir, "replies", "001", "SEARCH.txt"), "w"
        ) as f:
            f.write("original reply")
        with open(
            os.path.join(self.test_config_dir, "replies", "001", "REPLACE.txt"), "w"
        ) as f:
            f.write("rewritten reply")

        rewriter = ContentRewriterService(config_path=self.test_config_dir)
        middleware = ContentRewritingMiddleware(app=None, rewriter=rewriter)

        response_payload = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "This is an original reply.",
                    }
                }
            ]
        }

        async def call_next(request):
            return Response(
                content=json.dumps(response_payload), media_type="application/json"
            )

        async def receive():
            return {"type": "http.request", "body": b""}

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "headers": Headers({"content-type": "application/json"}).raw,
                "http_version": "1.1",
                "server": ("testserver", 80),
                "client": ("testclient", 123),
                "scheme": "http",
                "root_path": "",
                "path": "/test",
                "raw_path": b"/test",
                "query_string": b"",
            },
            receive=receive,
        )

        async def run_test():
            response = await middleware.dispatch(request, call_next)
            new_body = json.loads(response.body)
            self.assertEqual(
                new_body["choices"][0]["message"]["content"],
                "This is an rewritten reply.",
            )

        import asyncio

        asyncio.run(run_test())

    def test_inbound_reply_rewriting_handles_multimodal_content(self):
        """Ensure text blocks inside multimodal replies are rewritten."""

        os.makedirs(os.path.join(self.test_config_dir, "replies", "001"), exist_ok=True)
        with open(
            os.path.join(self.test_config_dir, "replies", "001", "SEARCH.txt"), "w"
        ) as f:
            f.write("original reply")
        with open(
            os.path.join(self.test_config_dir, "replies", "001", "REPLACE.txt"), "w"
        ) as f:
            f.write("rewritten reply")

        rewriter = ContentRewriterService(config_path=self.test_config_dir)
        middleware = ContentRewritingMiddleware(app=None, rewriter=rewriter)

        response_payload = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "This is an original reply."},
                            {
                                "type": "image_url",
                                "image_url": {"url": "https://example.com"},
                            },
                        ],
                    }
                }
            ]
        }

        async def call_next(request):
            return Response(
                content=json.dumps(response_payload), media_type="application/json"
            )

        async def receive():
            return {"type": "http.request", "body": b""}

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "headers": Headers({"content-type": "application/json"}).raw,
                "http_version": "1.1",
                "server": ("testserver", 80),
                "client": ("testclient", 123),
                "scheme": "http",
                "root_path": "",
                "path": "/test",
                "raw_path": b"/test",
                "query_string": b"",
            },
            receive=receive,
        )

        async def run_test():
            response = await middleware.dispatch(request, call_next)
            new_body = json.loads(response.body)
            rewritten_blocks = new_body["choices"][0]["message"]["content"]
            self.assertEqual(
                rewritten_blocks,
                [
                    {"type": "text", "text": "This is an rewritten reply."},
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.com"},
                    },
                ],
            )

        import asyncio

        asyncio.run(run_test())

    def test_request_rewriting_handles_multimodal_messages(self):
        """Verify chat request rewriting works for list-style content blocks."""

        os.makedirs(
            os.path.join(self.test_config_dir, "prompts", "user", "001"), exist_ok=True
        )
        with open(
            os.path.join(self.test_config_dir, "prompts", "user", "001", "SEARCH.txt"),
            "w",
        ) as f:
            f.write("original user text")
        with open(
            os.path.join(self.test_config_dir, "prompts", "user", "001", "REPLACE.txt"),
            "w",
        ) as f:
            f.write("rewritten user text")

        rewriter = ContentRewriterService(config_path=self.test_config_dir)
        middleware = ContentRewritingMiddleware(app=None, rewriter=rewriter)

        request_payload = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "original user text"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "https://example.com"},
                        },
                    ],
                }
            ]
        }

        async def call_next(request):
            data = await request.json()
            content_blocks = data["messages"][0]["content"]
            self.assertEqual(content_blocks[0]["text"], "rewritten user text")
            return Response(
                content=json.dumps({"ok": True}), media_type="application/json"
            )

        async def receive():
            return {
                "type": "http.request",
                "body": json.dumps(request_payload).encode("utf-8"),
                "more_body": False,
            }

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "headers": Headers({"content-type": "application/json"}).raw,
                "http_version": "1.1",
                "server": ("testserver", 80),
                "client": ("testclient", 123),
                "scheme": "http",
                "root_path": "",
                "path": "/test",
                "raw_path": b"/test",
                "query_string": b"",
            },
            receive=receive,
        )

        async def run_test():
            response = await middleware.dispatch(request, call_next)
            self.assertEqual(response.status_code, 200)

        import asyncio

        asyncio.run(run_test())

    def test_outbound_prompt_rewriting(self):
        """Verify that outbound prompts are rewritten correctly."""

        async def run_test():
            rewriter = ContentRewriterService(config_path=self.test_config_dir)
            middleware = ContentRewritingMiddleware(app=None, rewriter=rewriter)

            payload = {
                "messages": [
                    {"role": "system", "content": "This is an original system prompt."},
                    {"role": "user", "content": "This is a user prompt."},
                ]
            }

            async def get_body():
                return json.dumps(payload).encode("utf-8")

            request = Request(
                {
                    "type": "http",
                    "method": "POST",
                    "headers": Headers({"content-type": "application/json"}).raw,
                    "http_version": "1.1",
                    "server": ("testserver", 80),
                    "client": ("testclient", 123),
                    "scheme": "http",
                    "root_path": "",
                    "path": "/test",
                    "raw_path": b"/test",
                    "query_string": b"",
                }
            )
            request._body = await get_body()

            call_next = AsyncMock()
            call_next.return_value = Response("OK")

            await middleware.dispatch(request, call_next)

            call_next.assert_called_once()
            new_request = call_next.call_args[0][0]

            new_body = await new_request.json()

            self.assertEqual(
                new_body["messages"][0]["content"],
                "This is an rewritten system prompt.",
            )
            self.assertEqual(
                new_body["messages"][1]["content"], "This is a user prompt."
            )

        import asyncio

        asyncio.run(run_test())

    def test_outbound_prompt_rewriting_updates_content_length_header(self):
        """Ensure rewritten requests expose the correct Content-Length."""

        async def run_test():
            rewriter = ContentRewriterService(config_path=self.test_config_dir)
            middleware = ContentRewritingMiddleware(app=None, rewriter=rewriter)

            payload = {
                "messages": [
                    {
                        "role": "system",
                        "content": "This is an original system prompt.",
                    },
                ]
            }

            original_body = json.dumps(payload).encode("utf-8")

            request = Request(
                {
                    "type": "http",
                    "method": "POST",
                    "headers": Headers(
                        {
                            "content-type": "application/json",
                            "content-length": str(len(original_body)),
                        }
                    ).raw,
                    "http_version": "1.1",
                    "server": ("testserver", 80),
                    "client": ("testclient", 123),
                    "scheme": "http",
                    "root_path": "",
                    "path": "/test",
                    "raw_path": b"/test",
                    "query_string": b"",
                }
            )
            request._body = original_body

            call_next = AsyncMock()
            call_next.return_value = Response("OK")

            await middleware.dispatch(request, call_next)

            call_next.assert_called_once()
            forwarded_request = call_next.call_args[0][0]

            forwarded_body = await forwarded_request.body()
            self.assertNotEqual(len(forwarded_body), len(original_body))

            self.assertEqual(
                forwarded_request.headers["content-length"],
                str(len(forwarded_body)),
            )

        import asyncio

        asyncio.run(run_test())

    def test_outbound_responses_input_rewriting(self):
        """Verify that Responses API input payloads are rewritten."""

        async def run_test():
            rewriter = ContentRewriterService(config_path=self.test_config_dir)
            middleware = ContentRewritingMiddleware(app=None, rewriter=rewriter)

            payload = {
                "input": [
                    {
                        "role": "system",
                        "content": [
                            {
                                "type": "text",
                                "text": "This is an original system prompt.",
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "This is a user prompt.",
                            }
                        ],
                    },
                ]
            }

            async def get_body():
                return json.dumps(payload).encode("utf-8")

            request = Request(
                {
                    "type": "http",
                    "method": "POST",
                    "headers": Headers({"content-type": "application/json"}).raw,
                    "http_version": "1.1",
                    "server": ("testserver", 80),
                    "client": ("testclient", 123),
                    "scheme": "http",
                    "root_path": "",
                    "path": "/test",
                    "raw_path": b"/test",
                    "query_string": b"",
                }
            )
            request._body = await get_body()

            call_next = AsyncMock()
            call_next.return_value = Response("OK")

            await middleware.dispatch(request, call_next)

            call_next.assert_called_once()
            new_request = call_next.call_args[0][0]

            new_body = await new_request.json()

            rewritten_content = new_body["input"][0]["content"][0]["text"]
            self.assertEqual(
                rewritten_content,
                "This is an rewritten system prompt.",
            )
            # The user content should remain untouched
            self.assertEqual(
                new_body["input"][1]["content"][0]["text"],
                "This is a user prompt.",
            )

        import asyncio

        asyncio.run(run_test())

    def test_outbound_prompt_rewriting_ignores_non_string_content(self):
        """Ensure non-string prompt content is left untouched."""

        async def run_test():
            rewriter = ContentRewriterService(config_path=self.test_config_dir)
            middleware = ContentRewritingMiddleware(app=None, rewriter=rewriter)

            structured_content = [{"type": "text", "text": "Structured user payload."}]
            payload = {
                "messages": [
                    {
                        "role": "system",
                        "content": "This is an original system prompt.",
                    },
                    {"role": "user", "content": structured_content},
                ]
            }

            async def get_body():
                return json.dumps(payload).encode("utf-8")

            request = Request(
                {
                    "type": "http",
                    "method": "POST",
                    "headers": Headers({"content-type": "application/json"}).raw,
                    "http_version": "1.1",
                    "server": ("testserver", 80),
                    "client": ("testclient", 123),
                    "scheme": "http",
                    "root_path": "",
                    "path": "/test",
                    "raw_path": b"/test",
                    "query_string": b"",
                }
            )
            request._body = await get_body()

            call_next = AsyncMock()
            call_next.return_value = Response("OK")

            await middleware.dispatch(request, call_next)

            call_next.assert_called_once()
            new_request = call_next.call_args[0][0]

            new_body = await new_request.json()

            self.assertEqual(
                new_body["messages"][0]["content"],
                "This is an rewritten system prompt.",
            )
            self.assertEqual(new_body["messages"][1]["content"], structured_content)

        import asyncio

        asyncio.run(run_test())

    def test_end_to_end_rewriting(self):
        """Verify that a lengthy prompt is rewritten and propagated correctly."""

        async def run_test():
            # Create a new rule for a lengthy prompt
            os.makedirs(
                os.path.join(self.test_config_dir, "prompts", "user", "002"),
                exist_ok=True,
            )
            with open(
                os.path.join(
                    self.test_config_dir, "prompts", "user", "002", "SEARCH.txt"
                ),
                "w",
            ) as f:
                f.write("long original prompt")
            with open(
                os.path.join(
                    self.test_config_dir, "prompts", "user", "002", "REPLACE.txt"
                ),
                "w",
            ) as f:
                f.write("rewritten lengthy prompt")

            rewriter = ContentRewriterService(config_path=self.test_config_dir)
            middleware = ContentRewritingMiddleware(app=None, rewriter=rewriter)

            long_prompt = (
                "This is a very long original prompt that should be rewritten."
            )
            payload = {
                "messages": [
                    {"role": "user", "content": long_prompt},
                ]
            }

            async def get_body():
                return json.dumps(payload).encode("utf-8")

            request = Request(
                {
                    "type": "http",
                    "method": "POST",
                    "headers": Headers({"content-type": "application/json"}).raw,
                    "http_version": "1.1",
                    "server": ("testserver", 80),
                    "client": ("testclient", 123),
                    "scheme": "http",
                    "root_path": "",
                    "path": "/test",
                    "raw_path": b"/test",
                    "query_string": b"",
                }
            )
            request._body = await get_body()

            call_next = AsyncMock()
            call_next.return_value = Response("OK")

            await middleware.dispatch(request, call_next)

            call_next.assert_called_once()
            new_request = call_next.call_args[0][0]

            new_body = await new_request.json()

            self.assertEqual(
                new_body["messages"][0]["content"],
                "This is a very rewritten lengthy prompt that should be rewritten.",
            )

        import asyncio

        asyncio.run(run_test())

    def test_end_to_end_reply_rewriting(self):
        """Verify that a lengthy reply is rewritten and propagated correctly."""

        async def run_test():
            # Create a new rule for a lengthy reply
            os.makedirs(
                os.path.join(self.test_config_dir, "replies", "002"),
                exist_ok=True,
            )
            with open(
                os.path.join(self.test_config_dir, "replies", "002", "SEARCH.txt"), "w"
            ) as f:
                f.write("long original reply")
            with open(
                os.path.join(self.test_config_dir, "replies", "002", "REPLACE.txt"), "w"
            ) as f:
                f.write("rewritten lengthy reply")

            rewriter = ContentRewriterService(config_path=self.test_config_dir)
            middleware = ContentRewritingMiddleware(app=None, rewriter=rewriter)

            long_reply = "This is a very long original reply that should be rewritten."
            response_payload = {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": long_reply,
                        }
                    }
                ]
            }

            async def call_next(request):
                return Response(
                    content=json.dumps(response_payload),
                    media_type="application/json",
                )

            async def receive():
                return {"type": "http.request", "body": b""}

            request = Request(
                {
                    "type": "http",
                    "method": "POST",
                    "headers": Headers({"content-type": "application/json"}).raw,
                    "http_version": "1.1",
                    "server": ("testserver", 80),
                    "client": ("testclient", 123),
                    "scheme": "http",
                    "root_path": "",
                    "path": "/test",
                    "raw_path": b"/test",
                    "query_string": b"",
                },
                receive=receive,
            )

            response = await middleware.dispatch(request, call_next)
            new_body = json.loads(response.body)
            self.assertEqual(
                new_body["choices"][0]["message"]["content"],
                "This is a very rewritten lengthy reply that should be rewritten.",
            )

        import asyncio

        asyncio.run(run_test())

    def test_streaming_reply_rewriting(self):
        """Verify that streaming replies are rewritten correctly."""

        async def run_test():
            # Create a new rule for a streaming reply
            os.makedirs(
                os.path.join(self.test_config_dir, "replies", "003"),
                exist_ok=True,
            )
            with open(
                os.path.join(self.test_config_dir, "replies", "003", "SEARCH.txt"), "w"
            ) as f:
                f.write("original streaming reply")
            with open(
                os.path.join(self.test_config_dir, "replies", "003", "REPLACE.txt"), "w"
            ) as f:
                f.write("rewritten streaming reply")

            rewriter = ContentRewriterService(config_path=self.test_config_dir)
            middleware = ContentRewritingMiddleware(app=None, rewriter=rewriter)

            async def stream_generator():
                yield b"This is an original streaming reply."

            async def call_next(request):
                return StreamingResponse(
                    stream_generator(),
                    media_type="text/event-stream",
                )

            async def receive():
                return {"type": "http.request", "body": b""}

            request = Request(
                {
                    "type": "http",
                    "method": "POST",
                    "headers": Headers({"content-type": "application/json"}).raw,
                    "http_version": "1.1",
                    "server": ("testserver", 80),
                    "client": ("testclient", 123),
                    "scheme": "http",
                    "root_path": "",
                    "path": "/test",
                    "raw_path": b"/test",
                    "query_string": b"",
                },
                receive=receive,
            )

            response = await middleware.dispatch(request, call_next)
            self.assertIsInstance(response, StreamingResponse)
            response_body = b""
            async for chunk in response.body_iterator:
                response_body += chunk
            self.assertEqual(
                response_body.decode(), "This is an rewritten streaming reply."
            )

        import asyncio

        asyncio.run(run_test())

    def test_inbound_responses_output_rewriting(self):
        """Verify that Responses API outputs are rewritten."""

        async def run_test():
            os.makedirs(
                os.path.join(self.test_config_dir, "replies", "004"),
                exist_ok=True,
            )
            with open(
                os.path.join(self.test_config_dir, "replies", "004", "SEARCH.txt"),
                "w",
            ) as f:
                f.write("original reply")
            with open(
                os.path.join(self.test_config_dir, "replies", "004", "REPLACE.txt"),
                "w",
            ) as f:
                f.write("rewritten reply")

            rewriter = ContentRewriterService(config_path=self.test_config_dir)
            middleware = ContentRewritingMiddleware(app=None, rewriter=rewriter)

            response_payload = {
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": "This is an original reply.",
                            }
                        ]
                    }
                ],
                "output_text": ["This is an original reply."],
            }

            async def call_next(request):
                return Response(
                    content=json.dumps(response_payload),
                    media_type="application/json",
                )

            async def receive():
                return {"type": "http.request", "body": b""}

            request = Request(
                {
                    "type": "http",
                    "method": "POST",
                    "headers": Headers({"content-type": "application/json"}).raw,
                    "http_version": "1.1",
                    "server": ("testserver", 80),
                    "client": ("testclient", 123),
                    "scheme": "http",
                    "root_path": "",
                    "path": "/test",
                    "raw_path": b"/test",
                    "query_string": b"",
                },
                receive=receive,
            )

            response = await middleware.dispatch(request, call_next)
            body = json.loads(response.body)

            self.assertEqual(
                body["output"][0]["content"][0]["text"],
                "This is an rewritten reply.",
            )
            self.assertEqual(
                body["output_text"][0],
                "This is an rewritten reply.",
            )

        import asyncio

        asyncio.run(run_test())

    def test_inbound_responses_output_prepend_rules_apply_once(self):
        """Ensure PREPEND rules are not applied twice to output text."""

        async def run_test():
            os.makedirs(
                os.path.join(self.test_config_dir, "replies", "005"),
                exist_ok=True,
            )
            with open(
                os.path.join(self.test_config_dir, "replies", "005", "SEARCH.txt"),
                "w",
            ) as f:
                f.write("Original snippet")
            with open(
                os.path.join(self.test_config_dir, "replies", "005", "PREPEND.txt"),
                "w",
            ) as f:
                f.write("Prefix: ")

            rewriter = ContentRewriterService(config_path=self.test_config_dir)
            middleware = ContentRewritingMiddleware(app=None, rewriter=rewriter)

            response_payload = {
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Original snippet",
                            }
                        ]
                    }
                ],
                "output_text": ["Original snippet"],
            }

            async def call_next(request):
                return Response(
                    content=json.dumps(response_payload),
                    media_type="application/json",
                )

            async def receive():
                return {"type": "http.request", "body": b""}

            request = Request(
                {
                    "type": "http",
                    "method": "POST",
                    "headers": Headers({"content-type": "application/json"}).raw,
                    "http_version": "1.1",
                    "server": ("testserver", 80),
                    "client": ("testclient", 123),
                    "scheme": "http",
                    "root_path": "",
                    "path": "/test",
                    "raw_path": b"/test",
                    "query_string": b"",
                },
                receive=receive,
            )

            response = await middleware.dispatch(request, call_next)
            body = json.loads(response.body)

            self.assertEqual(
                body["output"][0]["content"][0]["text"],
                "Prefix: Original snippet",
            )
            self.assertEqual(body["output_text"][0], "Prefix: Original snippet")

        import asyncio

        asyncio.run(run_test())

    def test_streaming_reply_rewriting_preserves_background(self):
        """Ensure background tasks attached to streaming responses are preserved."""

        async def run_test():
            os.makedirs(
                os.path.join(self.test_config_dir, "replies", "004"),
                exist_ok=True,
            )
            with open(
                os.path.join(self.test_config_dir, "replies", "004", "SEARCH.txt"),
                "w",
            ) as f:
                f.write("original streaming background reply")
            with open(
                os.path.join(self.test_config_dir, "replies", "004", "REPLACE.txt"),
                "w",
            ) as f:
                f.write("rewritten streaming background reply")

            rewriter = ContentRewriterService(config_path=self.test_config_dir)
            middleware = ContentRewritingMiddleware(app=None, rewriter=rewriter)

            background_called = False

            def background_func():
                nonlocal background_called
                background_called = True

            background_task = BackgroundTask(background_func)

            async def stream_generator():
                yield b"This is an original streaming background reply."

            async def call_next(request):
                return StreamingResponse(
                    stream_generator(),
                    media_type="text/event-stream",
                    background=background_task,
                )

            async def receive():
                return {"type": "http.request", "body": b""}

            request = Request(
                {
                    "type": "http",
                    "method": "POST",
                    "headers": Headers({"content-type": "application/json"}).raw,
                    "http_version": "1.1",
                    "server": ("testserver", 80),
                    "client": ("testclient", 123),
                    "scheme": "http",
                    "root_path": "",
                    "path": "/test",
                    "raw_path": b"/test",
                    "query_string": b"",
                },
                receive=receive,
            )

            response = await middleware.dispatch(request, call_next)
            self.assertIsInstance(response, StreamingResponse)
            self.assertIs(response.background, background_task)

            response_body = b""
            async for chunk in response.body_iterator:
                response_body += chunk
            self.assertEqual(
                response_body.decode(),
                "This is an rewritten streaming background reply.",
            )

            await response.background()
            self.assertTrue(background_called)

        import asyncio

        asyncio.run(run_test())


import pytest

pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)
