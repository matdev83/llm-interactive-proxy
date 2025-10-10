from __future__ import annotations

"""Service for resolving project directories from the first user prompt."""

import contextlib
import logging
import re
import xml.etree.ElementTree as ET
from typing import Any

from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.model_utils import parse_model_backend
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session import Session
from src.core.interfaces.backend_service import IBackendService
from src.core.interfaces.session_service_interface import ISessionService

logger = logging.getLogger(__name__)


class ProjectDirectoryResolutionService:
    """Resolve absolute project directories using a dedicated backend model."""

    _WINDOWS_PATH_PATTERN = re.compile(r"^[A-Za-z]:\\")

    def __init__(
        self,
        app_config: AppConfig,
        backend_service: IBackendService,
        session_service: ISessionService,
    ) -> None:
        self._backend_service = backend_service
        self._session_service = session_service
        self._model_spec = (
            app_config.session.project_dir_resolution_model
            if hasattr(app_config, "session")
            else None
        )
        self._model_spec = self._model_spec.strip() if self._model_spec else ""

        backend_type: str | None = None
        model_name: str | None = None
        if self._model_spec:
            backend_candidate, model_candidate = parse_model_backend(
                self._model_spec, ""
            )
            if backend_candidate and model_candidate:
                backend_type = backend_candidate
                model_name = model_candidate
            else:
                logger.warning(
                    "Invalid project directory resolution model specification: %s",
                    self._model_spec,
                )

        self._backend_type = backend_type
        self._model_name = model_name
        self._model_identifier = (
            f"{self._backend_type}:{self._model_name}"
            if self._backend_type and self._model_name
            else None
        )

        self._system_prompt = (
            "You examine the user's initial instructions to determine the absolute "
            "project directory path they intend to work with. Respond using the "
            "exact XML formats shown below.\n"
            "If the directory can be determined:\n"
            "<directory-resolution-response>\n"
            "<project-absolute-directory>PATH_HERE</project-absolute-directory>\n"
            "</directory-resolution-response>\n"
            "If the directory cannot be determined:\n"
            "<directory-resolution-response>\n"
            "<error>SHORT_REASON</error>\n"
            "</directory-resolution-response>\n"
            "Rules:\n"
            "- Do not execute, simulate, or reason about running any tools or commands.\n"
            "- Operate strictly in a headless, non-interactive environment.\n"
            "- Communicate only via the XML response; no commentary or markdown.\n"
        )

    async def maybe_resolve_project_directory(
        self, session: Session, request: ChatRequest
    ) -> None:
        """Attempt to resolve the project directory for the very first prompt."""

        if not self._model_identifier:
            return

        if getattr(session.state, "project_dir_resolution_attempted", False):
            return

        if session.history:
            return

        existing_dir = getattr(session.state, "project_dir", None)
        if existing_dir:
            await self._persist_state(
                session,
                directory=None,
                message=(
                    "Project directory auto-detection skipped: directory already set to"
                    f" {existing_dir}"
                ),
            )
            return

        prompt_text = self._extract_user_prompt(request)
        if not prompt_text:
            await self._persist_state(
                session,
                directory=None,
                message=(
                    "Project directory auto-detection did not identify a directory"
                    " (empty prompt)"
                ),
            )
            return

        try:
            response = await self._call_resolution_model(prompt_text)
        except Exception as exc:  # pragma: no cover - defensive logging
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Project directory auto-detection call failed: %s", exc, exc_info=True
                )
            await self._persist_state(
                session,
                directory=None,
                message="Project directory auto-detection did not identify a directory (request failure)",
            )
            return

        if isinstance(response, StreamingResponseEnvelope):
            await self._persist_state(
                session,
                directory=None,
                message=(
                    "Project directory auto-detection did not identify a directory"
                    " (streaming response unsupported)"
                ),
            )
            return

        response_text = self._extract_response_text(response)
        if not response_text:
            await self._persist_state(
                session,
                directory=None,
                message=(
                    "Project directory auto-detection did not identify a directory"
                    " (empty model response)"
                ),
            )
            return

        directory, error_reason = self._parse_directory_response(response_text)
        if directory:
            await self._persist_state(
                session,
                directory=directory,
                message=f"Project directory auto-detected: {directory}",
            )
        else:
            reason_suffix = f" ({error_reason})" if error_reason else ""
            await self._persist_state(
                session,
                directory=None,
                message=(
                    "Project directory auto-detection did not identify a directory"
                    f"{reason_suffix}"
                ),
            )

    async def _persist_state(
        self, session: Session, *, directory: str | None, message: str
    ) -> None:
        session_state = session.state
        with contextlib.suppress(AttributeError):
            session_state.project_dir_resolution_attempted = True
        if directory is not None:
            session_state.project_dir = directory
        try:
            await self._session_service.update_session(session)
        except Exception as exc:  # pragma: no cover - defensive logging
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to persist project directory detection state: %s",
                    exc,
                    exc_info=True,
                )
        logger.info(message)

    async def _call_resolution_model(self, prompt_text: str) -> ResponseEnvelope:
        request = ChatRequest(
            model=self._model_identifier,
            messages=[
                ChatMessage(role="system", content=self._system_prompt),
                ChatMessage(role="user", content=prompt_text),
            ],
            extra_body={"backend_type": self._backend_type} if self._backend_type else None,
        )
        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            session_id=None,
            agent="project-dir-resolution",
        )
        response = await self._backend_service.call_completion(
            request,
            stream=False,
            allow_failover=False,
            context=context,
        )
        if isinstance(response, StreamingResponseEnvelope):
            raise TypeError("Streaming response returned for project directory resolution")
        return response

    def _extract_user_prompt(self, request: ChatRequest) -> str | None:
        for message in reversed(request.messages):
            if message.role != "user":
                continue
            content = self._normalize_content(message.content)
            if content.strip():
                return content
        return None

    def _normalize_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                text: Any | None = None
                if hasattr(part, "text"):
                    text = getattr(part, "text")
                elif isinstance(part, dict):
                    text = part.get("text") or part.get("content")
                else:
                    text = str(part)
                if text:
                    parts.append(str(text))
            return "\n".join(parts)
        if content is None:
            return ""
        return str(content)

    def _extract_response_text(self, response: ResponseEnvelope) -> str | None:
        content = response.content
        if isinstance(content, bytes):
            try:
                return content.decode("utf-8")
            except Exception:
                return content.decode("utf-8", "ignore")
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            text = self._extract_from_openai_like_response(content)
            if text:
                return text
            text = self._extract_from_gemini_like_response(content)
            if text:
                return text
            if "output_text" in content:
                value = content.get("output_text")
                if isinstance(value, str):
                    return value
        return None

    def _extract_from_openai_like_response(self, payload: dict[str, Any]) -> str | None:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        first = choices[0]
        if not isinstance(first, dict):
            return None
        message = first.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts: list[str] = []
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text") or part.get("content")
                        if text:
                            parts.append(str(text))
                if parts:
                    return "\n".join(parts)
        text_value = first.get("text")
        if isinstance(text_value, str):
            return text_value
        return None

    def _extract_from_gemini_like_response(self, payload: dict[str, Any]) -> str | None:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return None
        first = candidates[0]
        if not isinstance(first, dict):
            return None
        content = first.get("content")
        parts: list[str] = []
        if isinstance(content, dict):
            raw_parts = content.get("parts")
            if isinstance(raw_parts, list):
                for part in raw_parts:
                    if isinstance(part, dict) and part.get("text"):
                        parts.append(str(part["text"]))
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("text"):
                    parts.append(str(part["text"]))
        if parts:
            return "\n".join(parts)
        text_value = first.get("output_text")
        if isinstance(text_value, str):
            return text_value
        return None

    def _parse_directory_response(
        self, response_text: str
    ) -> tuple[str | None, str | None]:
        try:
            root = ET.fromstring(response_text.strip())
        except ET.ParseError:
            return None, "invalid XML"
        if root.tag != "directory-resolution-response":
            return None, "unexpected root tag"
        directory_elem = root.find("project-absolute-directory")
        if directory_elem is not None and directory_elem.text:
            candidate = directory_elem.text.strip()
            if self._looks_like_absolute_path(candidate):
                return candidate, None
            return None, "not an absolute path"
        error_elem = root.find("error")
        if error_elem is not None and error_elem.text:
            return None, error_elem.text.strip()
        return None, "no directory element"

    def _looks_like_absolute_path(self, value: str) -> bool:
        if not value:
            return False
        if "\n" in value or "\r" in value:
            return False
        if value.startswith("/"):
            return True
        if value.startswith("\\\\"):
            return True
        if self._WINDOWS_PATH_PATTERN.match(value):
            return True
        return False


__all__ = ["ProjectDirectoryResolutionService"]
