import json

from fastapi import Request
from src.core.services.content_rewriter_service import ContentRewriterService
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response, StreamingResponse


class ContentRewritingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, rewriter: ContentRewriterService):
        super().__init__(app)
        self.rewriter = rewriter

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
                if "messages" in data and isinstance(data["messages"], list):
                    for message in data["messages"]:
                        if "role" in message and "content" in message:
                            role = message["role"]
                            original_content = message["content"]
                            rewritten_content = self.rewriter.rewrite_prompt(
                                original_content, role
                            )
                            if original_content != rewritten_content:
                                message["content"] = rewritten_content
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

            return StreamingResponse(
                new_iterator(),
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
        else:
            response_body = response.body
            try:
                data = json.loads(response_body)
                is_rewritten = False
                if "choices" in data and isinstance(data["choices"], list):
                    for choice in data["choices"]:
                        if "message" in choice and "content" in choice["message"]:
                            original_content = choice["message"]["content"]
                            rewritten_content = self.rewriter.rewrite_reply(
                                original_content
                            )
                            if original_content != rewritten_content:
                                choice["message"]["content"] = rewritten_content
                                is_rewritten = True

                if is_rewritten:
                    new_body = json.dumps(data).encode("utf-8")
                    response.body = new_body
                    response.headers["content-length"] = str(len(new_body))

            except json.JSONDecodeError:
                pass

        return response
