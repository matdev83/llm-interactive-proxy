import json
from typing import Any

from fastapi import Request
from src.core.services.content_rewriter_service import ContentRewriterService
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response, StreamingResponse


class ContentRewritingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, rewriter: ContentRewriterService):
        super().__init__(app)
        self.rewriter = rewriter

    def _rewrite_chat_messages(self, payload: dict[str, Any]) -> bool:
        """Rewrite OpenAI chat-style messages in-place."""

        is_rewritten = False
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return False

        for message in messages:
            if not isinstance(message, dict):
                continue

            role = message.get("role")
            content = message.get("content")
            role_value = role if isinstance(role, str) else ""

            if isinstance(content, str):
                rewritten_content = self.rewriter.rewrite_prompt(
                    content, role_value
                )
                if content != rewritten_content:
                    message["content"] = rewritten_content
                    is_rewritten = True
                continue

            if not isinstance(content, list):
                continue

            for block in content:
                if not isinstance(block, dict):
                    continue

                text_value = block.get("text")
                if not isinstance(text_value, str):
                    continue

                rewritten_text = self.rewriter.rewrite_prompt(text_value, role_value)
                if rewritten_text != text_value:
                    block["text"] = rewritten_text
                    is_rewritten = True

        return is_rewritten

    def _rewrite_responses_input(self, payload: dict[str, Any]) -> bool:
        """Rewrite OpenAI Responses API input payloads in-place."""

        inputs = payload.get("input")
        if inputs is None:
            return False

        is_rewritten = False

        if isinstance(inputs, str):
            rewritten = self.rewriter.rewrite_prompt(inputs, "user")
            if rewritten != inputs:
                payload["input"] = rewritten
                return True
            return False

        if not isinstance(inputs, list):
            return False

        for item in inputs:
            if not isinstance(item, dict):
                continue

            role = item.get("role")
            content = item.get("content")

            if isinstance(content, str):
                rewritten = self.rewriter.rewrite_prompt(
                    content, role if isinstance(role, str) else ""
                )
                if rewritten != content:
                    item["content"] = rewritten
                    is_rewritten = True
                continue

            if not isinstance(content, list):
                continue

            for block in content:
                if not isinstance(block, dict):
                    continue

                text_value = block.get("text")
                if not isinstance(text_value, str):
                    continue

                rewritten_text = self.rewriter.rewrite_prompt(
                    text_value, role if isinstance(role, str) else ""
                )
                if rewritten_text != text_value:
                    block["text"] = rewritten_text
                    is_rewritten = True

        return is_rewritten

    def _rewrite_chat_response(self, payload: dict[str, Any]) -> bool:
        """Rewrite OpenAI chat completion responses in-place."""

        choices = payload.get("choices")
        if not isinstance(choices, list):
            return False

        is_rewritten = False

        for choice in choices:
            if not isinstance(choice, dict):
                continue

            message = choice.get("message")
            if not isinstance(message, dict):
                continue

            original_content = message.get("content")
            if not isinstance(original_content, str):
                continue

            rewritten_content = self.rewriter.rewrite_reply(original_content)
            if original_content != rewritten_content:
                message["content"] = rewritten_content
                is_rewritten = True

        return is_rewritten

    def _rewrite_responses_output(self, payload: dict[str, Any]) -> bool:
        """Rewrite OpenAI Responses API outputs in-place."""

        is_rewritten = False

        outputs = payload.get("output")
        if isinstance(outputs, list):
            for item in outputs:
                if not isinstance(item, dict):
                    continue

                content = item.get("content")
                if isinstance(content, str):
                    rewritten = self.rewriter.rewrite_reply(content)
                    if rewritten != content:
                        item["content"] = rewritten
                        is_rewritten = True
                    continue

                if not isinstance(content, list):
                    continue

                for block in content:
                    if not isinstance(block, dict):
                        continue

                    text_value = block.get("text")
                    if not isinstance(text_value, str):
                        continue

                    rewritten_text = self.rewriter.rewrite_reply(text_value)
                    if rewritten_text != text_value:
                        block["text"] = rewritten_text
                        is_rewritten = True

        output_text = payload.get("output_text")
        if isinstance(output_text, list):
            for index, text_value in enumerate(output_text):
                if not isinstance(text_value, str):
                    continue

                rewritten_text = self.rewriter.rewrite_reply(text_value)
                if rewritten_text != text_value:
                    payload["output_text"][index] = rewritten_text
                    is_rewritten = True

        return is_rewritten

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Step 1: Potentially rewrite the request
        request_for_next_call = request
        if request.method == "POST":
            body_bytes = await request.body()

            try:
                data = json.loads(body_bytes)
                is_rewritten = False

                if self._rewrite_chat_messages(data):
                    is_rewritten = True

                if self._rewrite_responses_input(data):
                    is_rewritten = True

                if is_rewritten:
                    body_bytes = json.dumps(data).encode("utf-8")

            except json.JSONDecodeError:
                # Not a JSON request, do nothing to the body
                pass

            # If body was consumed, we must create a new request
            async def receive():
                return {"type": "http.request", "body": body_bytes, "more_body": False}

            request_for_next_call = Request(request.scope, receive)

        # Step 2: Call the next middleware/app
        response = await call_next(request_for_next_call)

        # Step 3: Potentially rewrite the response
        if isinstance(response, StreamingResponse):

            async def new_iterator():
                response_body = b""
                async for chunk in response.body_iterator:
                    response_body += chunk
                rewritten_body = self.rewriter.rewrite_reply(response_body.decode())
                yield rewritten_body.encode("utf-8")

            background = response.background
            response.background = None

            return StreamingResponse(
                new_iterator(),
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
                background=background,
            )
        else:
            response_body = response.body
            try:
                data = json.loads(response_body)
                is_rewritten = False

                if self._rewrite_chat_response(data):
                    is_rewritten = True

                if self._rewrite_responses_output(data):
                    is_rewritten = True

                if is_rewritten:
                    new_body = json.dumps(data).encode("utf-8")
                    response.body = new_body
                    response.headers["content-length"] = str(len(new_body))

            except json.JSONDecodeError:
                pass

        return response
