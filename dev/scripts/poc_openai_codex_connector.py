from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx

# When running Windows Python from WSL paths, the repo root is not reliably on sys.path.
# Ensure imports like `from src...` work regardless of invocation cwd.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.connectors.openai_codex import OpenAICodexConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.translation_service import TranslationService


def _configure_logging(*, verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _coerce_effective_model(model: str) -> str:
    # Match other backends: allow either "gpt-5.1-codex" or "openai-codex:gpt-5.1-codex".
    if ":" in model:
        return model
    return f"openai-codex:{model}"


def _print_response_text(envelope: ResponseEnvelope) -> int:
    content = envelope.content
    if not isinstance(content, dict):
        print(str(content))
        return 0

    if "error" in content:
        print(json.dumps(content, indent=2))
        return 1

    choices = content.get("choices")
    if isinstance(choices, list) and choices:
        choice0 = choices[0]
        if isinstance(choice0, dict):
            msg = choice0.get("message")
            if isinstance(msg, dict):
                message_content = msg.get("content")
                if isinstance(message_content, str) and message_content:
                    print(message_content)
                    return 0
                tool_calls = msg.get("tool_calls")
                if tool_calls is not None:
                    print(json.dumps({"tool_calls": tool_calls}, indent=2))
                    return 0

    print(json.dumps(content, indent=2))
    return 0


def _extract_stream_delta(chunk: Any) -> tuple[str, list[Any] | None]:
    payload = _chunk_to_payload(chunk)

    if not isinstance(payload, dict):
        return "", None

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return "", None

    choice0 = choices[0]
    if not isinstance(choice0, dict):
        return "", None

    delta = choice0.get("delta")
    if not isinstance(delta, dict):
        return "", None

    text = delta.get("content")
    tool_calls = delta.get("tool_calls")
    delta_text = text if isinstance(text, str) else ""
    delta_tool_calls = tool_calls if isinstance(tool_calls, list) else None
    return delta_text, delta_tool_calls


def _chunk_to_payload(chunk: Any) -> Any:
    if isinstance(chunk, ProcessedResponse):
        chunk = chunk.content
    if hasattr(chunk, "model_dump"):
        try:
            return chunk.model_dump(exclude_none=True)
        except TypeError:
            return chunk.model_dump()
    return chunk


async def _run() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "POC: call the ChatGPT Codex backend via the in-process "
            "`openai-codex` connector (no proxy server needed)."
        ),
    )
    parser.add_argument(
        "--model",
        default="gpt-5.1-codex",
        help="Model name (e.g. gpt-5.1-codex, gpt-5.2-codex, codex-mini-latest).",
    )
    parser.add_argument(
        "--message",
        default="Hello from llm-interactive-proxy POC. Reply with a single sentence.",
        help="User message to send.",
    )
    parser.add_argument(
        "--system",
        default=None,
        help="Optional system message (sent as role=system in /v1/chat/completions style).",
    )
    parser.add_argument(
        "--prompt-mode",
        default=None,
        choices=["codex_default", "merge_custom", "custom_only"],
        help=(
            "Optional override for Codex prompt handling. "
            "Implemented via request.extra_body.codex_capabilities.prompt_mode."
        ),
    )
    parser.add_argument(
        "--codex-home",
        default=None,
        help=(
            "Optional directory containing auth.json (defaults to ~/.codex). "
            "Example: C:\\Users\\<you>\\.codex"
        ),
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream the response as it arrives (prints delta.content).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logs.",
    )
    parser.add_argument(
        "--dump-chunks",
        action="store_true",
        help="Print raw streaming chunks to stderr (for debugging).",
    )
    args = parser.parse_args()
    _configure_logging(verbose=bool(args.verbose))

    config = AppConfig()
    translation_service = TranslationService()

    timeout = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        connector = OpenAICodexConnector(
            client=client,
            config=config,
            translation_service=translation_service,
        )

        init_kwargs: dict[str, Any] = {
            "enable_openai_codex_backend_debugging_override": True,
        }
        if isinstance(args.codex_home, str) and args.codex_home.strip():
            init_kwargs["openai_codex_path"] = args.codex_home.strip()

        await connector.initialize(**init_kwargs)

        if not connector.is_backend_functional():
            errors = connector.get_validation_errors()
            print(
                "openai-codex backend not functional. Ensure you have valid Codex CLI credentials.\n"
                f"- Expected default: {Path.home() / '.codex' / 'auth.json'}\n"
                f"- Errors: {errors}"
            )
            await connector.shutdown()
            return 2

        effective_model = _coerce_effective_model(str(args.model))
        messages: list[ChatMessage] = []
        if isinstance(args.system, str) and args.system.strip():
            messages.append(ChatMessage(role="system", content=args.system.strip()))
        messages.append(ChatMessage(role="user", content=str(args.message)))

        request = ChatRequest(
            model=effective_model,
            messages=messages,
            stream=bool(args.stream),
            session_id=f"poc-{uuid.uuid4().hex[:12]}",
        )
        if isinstance(args.prompt_mode, str) and args.prompt_mode.strip():
            request.extra_body = {
                **(request.extra_body or {}),
                "codex_capabilities": {
                    **(request.extra_body or {}).get("codex_capabilities", {}),
                    "prompt_mode": args.prompt_mode.strip(),
                },
            }

        result = await connector.chat_completions(
            request_data=request,
            processed_messages=request.messages,
            effective_model=effective_model,
        )

        exit_code = 0
        if bool(args.stream):
            if not isinstance(result, StreamingResponseEnvelope):
                print(json.dumps(getattr(result, "content", result), indent=2))
                await connector.shutdown()
                return 0

            if result.content is None:
                print("Streaming response had no content iterator.")
                await connector.shutdown()
                return 1

            async for chunk in result.content:
                delta_text, tool_calls = _extract_stream_delta(chunk)
                if delta_text:
                    print(delta_text, end="", flush=True)
                elif bool(args.dump_chunks):
                    payload = _chunk_to_payload(chunk)
                    try:
                        sys.stderr.write(json.dumps(payload) + "\n")
                    except TypeError:
                        sys.stderr.write(str(payload) + "\n")
                if tool_calls is not None and args.verbose:
                    print("\n" + json.dumps({"tool_calls": tool_calls}, indent=2))
            print()
        else:
            if isinstance(result, ResponseEnvelope):
                exit_code = _print_response_text(result)
            else:
                print(json.dumps(getattr(result, "content", result), indent=2))
                exit_code = 0

        await connector.shutdown()
        return exit_code


def main() -> None:
    try:
        raise SystemExit(asyncio.run(_run()))
    except KeyboardInterrupt:
        raise SystemExit(130)


if __name__ == "__main__":
    main()
