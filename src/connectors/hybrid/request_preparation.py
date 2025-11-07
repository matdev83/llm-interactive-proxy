"""Request preparation helpers for the hybrid connector."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, cast

from src.core.interfaces.model_bases import DomainModel, InternalDTO


class HybridRequestPreparationMixin:
    """Normalize requests before delegating to backend services."""

    translation_service: Any

    def _prepare_backend_request(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        target_model: str,
        stream: bool,
        messages: list | None = None,
    ) -> CanonicalChatRequest:
        """Normalize request for backend service calls."""

        from src.core.domain.chat import CanonicalChatRequest, ChatRequest

        request_obj: Any = request_data

        if hasattr(request_obj, "model_copy"):
            request_obj = request_obj.model_copy(
                update={"model": target_model, "stream": stream}
            )
        elif isinstance(request_obj, dict):
            request_dict = dict(request_obj)
            request_dict["model"] = target_model
            request_dict["stream"] = stream
            request_obj = self.translation_service.to_domain_request(
                request_dict, "openai"
            )
        elif is_dataclass(request_obj) and not isinstance(request_obj, type):
            request_dict = asdict(request_obj)
            request_dict["model"] = target_model
            request_dict["stream"] = stream
            request_obj = self.translation_service.to_domain_request(
                request_dict, "openai"
            )
        elif isinstance(request_obj, ChatRequest):
            request_obj = request_obj.model_copy(
                update={"model": target_model, "stream": stream}
            )
        else:
            raise TypeError(
                "Unable to prepare backend request from type "
                f"{type(request_obj).__name__}"
            )

        if not isinstance(request_obj, CanonicalChatRequest):
            request_obj = self.translation_service.to_domain_request(
                request_obj, "openai"
            )

        if messages is not None:
            request_obj = request_obj.model_copy(update={"messages": messages})

        if request_obj.extra_body and isinstance(request_obj.extra_body, dict):
            keys_to_strip = {"session_id", "backend_type", "model"}
            cleaned_extra_body = {
                key: value
                for key, value in request_obj.extra_body.items()
                if key not in keys_to_strip
            }
            if len(cleaned_extra_body) != len(request_obj.extra_body):
                request_obj = request_obj.model_copy(
                    update={
                        "extra_body": cleaned_extra_body if cleaned_extra_body else None
                    }
                )

        return cast("CanonicalChatRequest", request_obj)
