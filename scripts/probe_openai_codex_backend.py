#!/usr/bin/env python
"""
Diagnostic probe for the OpenAI Codex backend.

This script exercises the ``OpenAICodexConnector`` directly so that we can
experiment with different instruction-delivery strategies and observe how the
remote Codex service responds. It is intended for manual debugging while we
work through 400 "Instructions are not valid" errors reported by real clients.

Usage examples:

    # Run the full built-in scenario sweep
    ./.venv/Scripts/python.exe scripts/probe_openai_codex_backend.py

    # Limit to a specific scenario
    ./.venv/Scripts/python.exe scripts/probe_openai_codex_backend.py --scenarios inline_kilo

    # Dry-run to inspect the payloads without contacting the remote service
    ./.venv/Scripts/python.exe scripts/probe_openai_codex_backend.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import shorten
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx
from src.connectors.openai_codex import OpenAICodexConnector
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.interfaces.translation_service_interface import ITranslationService
from src.core.services.translation_service import TranslationService

LOGGER = logging.getLogger("probe_codex_backend")

DEFAULT_MODEL_ALIAS = "openai-codex:gpt-5-codex"
DEFAULT_EFFECTIVE_MODEL = "gpt-5-codex"
CODEX_ENDPOINT = "https://chatgpt.com/backend-api/codex/responses"

# Representative instructions observed in wire logs when Kilo triggers the proxy.
DEFAULT_KILO_SYSTEM_PROMPT = """You are Kilo Code, a knowledgeable technical assistant focused on answering questions and providing information about software development, technology, and related topics.

====

MARKDOWN RULES

- Rely on Markdown best practices. Use headings to delineate major sections using #,##,###.
- Avoid excessive formatting or stylized capitalization beyond standard Markdown.
- Avoid HTML tags when possible. Use Markdown-compliant structures instead and escape raw HTML if unavoidable.
- When showing code, use fenced code block with language annotations for syntax highlighting.

GENERAL GUIDANCE

- Keep answers concise, professional, and accurate.
- Provide references, links, or short citations when referencing external resources or summarizing from documentation.
- Split responses into sections with headings when diving into multi-part answers or walkthroughs.
- Avoid speculation. If unsure, clarify the gap or suggest ways to verify.
- When describing processes or steps, use ordered lists. For bullet points or highlights, use unordered lists.
"""

# Representative user payload captured from the failing request.
DEFAULT_KILO_USER_PROMPT = """<task>
What this project is all about?
</task>
<environment_details>
# VSCode Visible Files
tests\\conftest.py

# VSCode Open Tabs
tests/conftest.py
</environment_details>
"""


@dataclass(slots=True)
class Scenario:
    """Configuration for a single probe run."""

    key: str
    description: str
    system_strategy: str = "none"
    user_message: str = DEFAULT_KILO_USER_PROMPT
    extra_body: dict[str, Any] = field(default_factory=dict)
    include_tools: bool = False
    reasoning_effort: str | None = None

    def build_messages(
        self, system_prompt: str | None, *, include_system: bool = True
    ) -> list[ChatMessage]:
        messages: list[ChatMessage] = []
        if include_system and self.system_strategy == "inline" and system_prompt:
            messages.append(ChatMessage(role="system", content=system_prompt))
        messages.append(ChatMessage(role="user", content=self.user_message))
        return messages


def _load_optional_text(path: str | None) -> str | None:
    if not path:
        return None
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Text override file not found: {file_path}")
    return file_path.read_text(encoding="utf-8")


def _build_user_instructions_block(text: str) -> str:
    payload = text.strip()
    return f"<user_instructions>\n\n{payload}\n\n</user_instructions>"


def build_default_scenarios() -> dict[str, Scenario]:
    """Return the baked-in scenario catalogue."""
    return {
        "baseline_cli": Scenario(
            key="baseline_cli",
            description="Baseline CLI-style request: Codex default instructions only.",
            system_strategy="none",
            extra_body={
                "sandbox_mode": "danger-full-access",
                "approval_policy": "never",
                "network_access": "enabled",
                "shell": "bash",
            },
        ),
        "inline_kilo": Scenario(
            key="inline_kilo",
            description="Inject the Kilo system prompt as a traditional system message (expected current failure).",
            system_strategy="inline",
        ),
        "user_instructions_kilo": Scenario(
            key="user_instructions_kilo",
            description="Deliver the Kilo instructions via <user_instructions> input block while keeping Codex defaults.",
            system_strategy="user_instructions",
        ),
        "instructions_only_kilo": Scenario(
            key="instructions_only_kilo",
            description="Replace Codex base instructions with the Kilo system prompt to test strict validation.",
            system_strategy="instructions_only",
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe the OpenAI Codex backend with controlled instruction strategies."
    )
    parser.add_argument(
        "--auth-path",
        help="Optional path to the directory containing auth.json (defaults to connector discovery).",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL_ALIAS,
        help=f"Model alias to place in the ChatRequest (default: {DEFAULT_MODEL_ALIAS}).",
    )
    parser.add_argument(
        "--effective-model",
        default=DEFAULT_EFFECTIVE_MODEL,
        help=f"Underlying Codex model slug to target (default: {DEFAULT_EFFECTIVE_MODEL}).",
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        help="Scenario keys to execute (default: all built-ins).",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List available scenarios and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build payloads but do not contact the remote service.",
    )
    parser.add_argument(
        "--system-file",
        help="Path to a file containing an alternate system prompt to use for Kilo scenarios.",
    )
    parser.add_argument(
        "--user-file",
        help="Path to a file containing an alternate user message payload.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=45.0,
        help="HTTP timeout in seconds (applies to each request).",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=20,
        help="Maximum number of SSE lines to sample before closing a successful stream.",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=2048,
        help="Maximum number of bytes to capture from error bodies.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level for the probe script (default: INFO).",
    )
    return parser.parse_args()


def _summarize_instructions(text: str | None) -> str:
    if not text:
        return "<empty>"
    normalized = " ".join(text.split())
    return shorten(normalized, width=160, placeholder="…")


def _inject_user_instructions_payload(
    payload: dict[str, Any], user_instruction_text: str
) -> None:
    user_block = {
        "type": "message",
        "role": "user",
        "content": [
            {
                "type": "input_text",
                "text": _build_user_instructions_block(user_instruction_text),
            }
        ],
    }
    payload.setdefault("input", [])
    payload["input"].insert(0, user_block)


async def _send_payload(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
    headers: dict[str, str],
    *,
    timeout: float,
    max_events: int,
    max_bytes: int,
) -> dict[str, Any]:
    response_summary: dict[str, Any] = {}
    LOGGER.debug("POST %s", CODEX_ENDPOINT)
    async with client.stream(
        "POST",
        CODEX_ENDPOINT,
        json=payload,
        headers=headers,
        timeout=timeout,
    ) as response:
        response_summary["status_code"] = response.status_code
        response_summary["reason_phrase"] = response.reason_phrase
        response_summary["headers"] = dict(response.headers.items())

        if response.status_code >= 400:
            body = await response.aread()
            response_summary["body_preview"] = body.decode("utf-8", errors="replace")[
                :max_bytes
            ]
            return response_summary

        events: list[str] = []
        async for line in response.aiter_lines():
            if not line:
                continue
            events.append(line)
            if len(events) >= max_events:
                break
        response_summary["sampled_events"] = events
    return response_summary


async def run_scenario(
    connector: OpenAICodexConnector,
    scenario: Scenario,
    *,
    model_alias: str,
    effective_model: str,
    system_prompt: str | None,
    dry_run: bool,
    timeout: float,
    max_events: int,
    max_bytes: int,
) -> dict[str, Any]:
    LOGGER.info("Running scenario: %s - %s", scenario.key, scenario.description)
    scenario_messages = scenario.build_messages(system_prompt)
    request = ChatRequest(
        model=model_alias,
        messages=scenario_messages,
        stream=True,
        tools=None,
        extra_body=scenario.extra_body or {},
        reasoning_effort=scenario.reasoning_effort,
    )

    processed_messages = list(request.messages)
    payload, conversation_id = connector._build_codex_payload(
        request_data=request,
        processed_messages=processed_messages,
        effective_model=effective_model,
    )

    summary: dict[str, Any] = {
        "scenario": scenario.key,
        "system_strategy": scenario.system_strategy,
        "instructions_preview": _summarize_instructions(payload.get("instructions")),
        "instructions_length": len(payload.get("instructions") or ""),
        "input_length": len(payload.get("input", [])),
    }

    if scenario.system_strategy == "user_instructions":
        base_prompt = connector._codex_system_prompt()
        payload["instructions"] = connector._sanitize_codex_instructions(base_prompt)
        if system_prompt:
            _inject_user_instructions_payload(payload, system_prompt)
            summary["user_instructions_inserted"] = True

    elif scenario.system_strategy == "instructions_only":
        sanitized = connector._sanitize_codex_instructions(system_prompt or "")
        payload["instructions"] = sanitized

    headers = connector._build_codex_headers(conversation_id)

    summary["headers_preview"] = {
        key: value for key, value in headers.items() if key.lower() != "authorization"
    }

    if dry_run:
        LOGGER.info("Dry-run enabled; skipping HTTP call for %s", scenario.key)
        summary["status"] = "skipped"
        summary["payload"] = {
            "model": payload.get("model"),
            "stream": payload.get("stream"),
            "tool_choice": payload.get("tool_choice"),
            "include": payload.get("include"),
        }
        return summary

    try:
        result = await _send_payload(
            connector.client,
            payload,
            headers,
            timeout=timeout,
            max_events=max_events,
            max_bytes=max_bytes,
        )
        summary.update(result)
    except httpx.HTTPError as exc:
        summary["error"] = f"HTTPError: {exc!s}"

    return summary


async def async_main(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    scenarios_catalogue = build_default_scenarios()
    if args.list_scenarios:
        for item in scenarios_catalogue.values():
            print(f"{item.key}: {item.description}")
        return 0

    selected_keys = (
        list(scenarios_catalogue.keys()) if not args.scenarios else args.scenarios
    )

    missing = [key for key in selected_keys if key not in scenarios_catalogue]
    if missing:
        raise ValueError(f"Unknown scenario keys: {', '.join(missing)}")

    system_prompt_override = _load_optional_text(args.system_file)
    user_payload_override = _load_optional_text(args.user_file)

    if system_prompt_override:
        LOGGER.info("Loaded custom system prompt from %s", args.system_file)
    if user_payload_override:
        LOGGER.info("Loaded custom user payload from %s", args.user_file)

    async with httpx.AsyncClient(timeout=args.timeout) as client:
        config = AppConfig()

        # Set up DI container properly
        services = ServiceCollection()
        services.add_singleton(TranslationService)
        services.add_singleton(ITranslationService, TranslationService)  # type: ignore[type-abstract]
        provider = services.build_provider()

        # Get translation service via DI
        di_translation_service = provider.get_required_service(ITranslationService)

        connector = OpenAICodexConnector(
            client=client,
            config=config,
            translation_service=di_translation_service,
        )
        await connector.initialize(openai_codex_path=args.auth_path)

        try:
            reports: list[dict[str, Any]] = []
            for key in selected_keys:
                scenario = scenarios_catalogue[key]
                if user_payload_override:
                    scenario = Scenario(
                        key=scenario.key,
                        description=scenario.description,
                        system_strategy=scenario.system_strategy,
                        user_message=user_payload_override,
                        extra_body=scenario.extra_body,
                        include_tools=scenario.include_tools,
                        reasoning_effort=scenario.reasoning_effort,
                    )
                system_prompt = system_prompt_override or (
                    DEFAULT_KILO_SYSTEM_PROMPT
                    if scenario.system_strategy != "none"
                    else None
                )
                result = await run_scenario(
                    connector,
                    scenario,
                    model_alias=args.model,
                    effective_model=args.effective_model,
                    system_prompt=system_prompt,
                    dry_run=args.dry_run,
                    timeout=args.timeout,
                    max_events=args.max_events,
                    max_bytes=args.max_bytes,
                )
                reports.append(result)
                LOGGER.info(
                    "Scenario %s result: %s", scenario.key, json.dumps(result, indent=2)
                )
        finally:
            connector._stop_file_watching()

    return 0


def main() -> None:
    args = parse_args()
    try:
        exit_code = asyncio.run(async_main(args))
    except KeyboardInterrupt:
        exit_code = 130
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
