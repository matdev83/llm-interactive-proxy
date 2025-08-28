from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.config.app_config import AppConfig
from src.core.domain.request_context import RequestContext
from src.core.interfaces.wire_capture_interface import IWireCapture


class WireCapture(IWireCapture):
    """File-based wire-level capture implementation.

    Writes human-readable separators and raw payloads to a configured file.
    No-ops when the capture file is not configured.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._lock = asyncio.Lock()
        self._file_path: str | None = getattr(config.logging, "capture_file", None)

        # Ensure directory exists if configured
        if self._file_path:
            try:
                Path(os.path.dirname(self._file_path) or ".").mkdir(
                    parents=True, exist_ok=True
                )
            except Exception:
                # Best-effort; if we cannot create the directory, leave disabled
                self._file_path = None

    def enabled(self) -> bool:
        return bool(self._file_path)

    async def capture_outbound_request(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        request_payload: Any,
    ) -> None:
        if not self.enabled():
            return
        header = self._format_header(
            direction="REQUEST",
            context=context,
            session_id=session_id,
            backend=backend,
            model=model,
            key_name=key_name,
        )
        body = _safe_json_dump(request_payload)
        await self._append(f"{header}\n{body}\n")

    async def capture_inbound_response(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        response_content: Any,
    ) -> None:
        if not self.enabled():
            return
        header = self._format_header(
            direction="REPLY",
            context=context,
            session_id=session_id,
            backend=backend,
            model=model,
            key_name=key_name,
        )
        body = _safe_json_dump(response_content)
        await self._append(f"{header}\n{body}\n")

    def wrap_inbound_stream(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        stream: AsyncIterator[bytes],
    ) -> AsyncIterator[bytes]:
        if not self.enabled():
            return stream

        async def _gen() -> AsyncIterator[bytes]:
            # Write a header once, then tee all bytes
            header = self._format_header(
                direction="REPLY-STREAM",
                context=context,
                session_id=session_id,
                backend=backend,
                model=model,
                key_name=key_name,
            )
            await self._append(f"{header}\n")
            async for chunk in stream:
                # Append chunk as-is (bytes) with a small prefix for readability
                try:
                    text = chunk.decode("utf-8", errors="replace")
                    await self._append(text)
                except Exception:
                    # Fallback to repr if decoding fails
                    await self._append(repr(chunk))
                yield chunk
            await self._append("\n")

        return _gen()

    def _format_header(
        self,
        *,
        direction: str,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
    ) -> str:
        ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        client = getattr(context, "client_host", None) if context else None
        agent = getattr(context, "agent", None) if context else None
        who = f"client={client or 'unknown'}" + (f" agent={agent}" if agent else "")
        sid = f" session={session_id}" if session_id else ""
        key = f" key={key_name}" if key_name else ""
        return (
            f"----- {direction} {ts} -----\n"
            f"{who}{sid} -> backend={backend} model={model}{key}"
        )

    async def _append(self, text: str) -> None:
        # Best-effort append with a lock to serialize writes
        if not self._file_path:
            return
        async with self._lock:
            with open(self._file_path, "a", encoding="utf-8") as f:
                f.write(text)


def _safe_json_dump(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        try:
            if hasattr(obj, "model_dump"):
                return json.dumps(obj.model_dump(), ensure_ascii=False, indent=2)  # type: ignore[attr-defined]
            return json.dumps(obj.__dict__, ensure_ascii=False, indent=2)
        except Exception:
            return str(obj)
