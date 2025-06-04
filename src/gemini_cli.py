import argparse
import asyncio
import os
from typing import List

import httpx

from src.models import ChatCompletionRequest, ChatMessage
from src.backends.gemini import GeminiBackend


def load_gemini_api_keys() -> List[str]:
    numbered = []
    single = os.getenv("GEMINI_API_KEY")
    for i in range(1, 21):
        val = os.getenv(f"GEMINI_API_KEY_{i}")
        if val:
            numbered.append(val)
    if single and numbered:
        raise ValueError("Set either GEMINI_API_KEY or GEMINI_API_KEY_<n>, not both")
    keys = numbered if numbered else ([single] if single else [])
    if not keys:
        raise ValueError("No Gemini API key provided")
    for key in keys:
        if not key.startswith("AI") or len(key) < 32:
            raise ValueError(f"Invalid Gemini API key: {key}")
    return keys


async def _run(args: argparse.Namespace) -> None:
    keys = load_gemini_api_keys()
    async with httpx.AsyncClient() as client:
        backend = GeminiBackend(client, api_keys=keys)
        req = ChatCompletionRequest(
            model=args.model,
            messages=[ChatMessage(role="user", content=args.prompt)],
            stream=args.stream,
        )
        result = await backend.chat_completion(req, stream=args.stream)
        if args.stream:
            async for chunk in result:
                print(chunk.decode(), end="")
        else:
            print(result["data"])
            print("Response headers:", result["headers"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Interact with Google Gemini AI")
    parser.add_argument("prompt")
    parser.add_argument("--model", default="gemini-pro")
    parser.add_argument("--stream", action="store_true")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
