from __future__ import annotations

from typing import List

from fastapi import FastAPI

from .base import BaseCommand, CommandResult

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..proxy_logic import ProxyState


class FailoverBase(BaseCommand):
    def __init__(self, app: FastAPI | None = None, **kwargs) -> None:
        super().__init__(app=app, **kwargs)

    def _ensure_interactive(self, state: "ProxyState", messages: List[str]) -> None:
        if not state.interactive_mode:
            state.set_interactive_mode(True)
            messages.append(
                "This llm-interactive-proxy session is now set to interactive mode"
            )
