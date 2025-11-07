"""Utility helpers for the hybrid connector."""

from __future__ import annotations

from typing import Any


class HybridConnectorUtilsMixin:
    """Utility methods shared by the hybrid connector."""

    @staticmethod
    def _extract_message_role(message: Any) -> str | None:
        """Best-effort extraction of a message role."""

        role = getattr(message, "role", None)
        if isinstance(role, str) and role:
            return role

        if isinstance(message, dict):
            role_value = message.get("role")
            return role_value if isinstance(role_value, str) else None

        if hasattr(message, "model_dump") and callable(message.model_dump):
            try:
                dumped = message.model_dump()
                role_value = dumped.get("role")
                if isinstance(role_value, str):
                    return role_value
            except Exception:  # pragma: no cover - defensive
                return None

        if hasattr(message, "get") and callable(message.get):
            try:
                role_value = message.get("role")
                if isinstance(role_value, str):
                    return role_value
            except Exception:  # pragma: no cover - defensive
                return None

        return None

    def _is_first_user_turn(
        self,
        processed_messages: list[Any] | None,
        request_messages: list[Any] | None,
    ) -> bool:
        """Determine whether the current request represents the first user turn."""

        messages_to_check: list[Any] = []
        if processed_messages:
            messages_to_check = list(processed_messages)
        elif request_messages:
            messages_to_check = list(request_messages)

        if not messages_to_check:
            return True

        for message in messages_to_check:
            role = self._extract_message_role(message)
            if not role:
                continue
            normalized_role = role.strip().lower()
            if normalized_role in {"assistant", "tool", "function"}:
                return False

        return True
