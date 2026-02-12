"""Provider error normalization for routing/resilience decisions."""

from __future__ import annotations

from src.core.interfaces.provider_error_classifier_interface import (
    IProviderErrorClassifier,
    ProviderErrorClassification,
)


class ProviderErrorClassifier(IProviderErrorClassifier):
    """Classify provider-specific errors into canonical routing categories."""

    _PERMANENT_MODEL_CODES = {
        "model_not_found",
        "model_not_supported",
        "unsupported_model",
        "unsupported_on_instance",
    }
    _TEMPORARY_CODES = {
        "rate_limit",
        "rate_limited",
        "rate_limit_exceeded",
        "quota_exceeded",
        "temporarily_unavailable",
    }

    def classify(self, error: Exception) -> ProviderErrorClassification:
        status_code = self._extract_status_code(error)
        code = self._extract_code(error)
        message = self._extract_message(error)
        normalized_code = code.lower().strip() if isinstance(code, str) else ""
        normalized_message = message.lower()

        # Precedence: permanent model-not-found signals override temporary ones.
        if self._is_permanent_model_not_found(
            status_code=status_code,
            normalized_code=normalized_code,
            normalized_message=normalized_message,
        ):
            return ProviderErrorClassification(
                code="unsupported_on_instance",
                category="availability",
                retryable=False,
                reason=message,
            )

        if status_code == 429 or normalized_code in self._TEMPORARY_CODES:
            return ProviderErrorClassification(
                code="temporarily_unavailable",
                category="availability",
                retryable=True,
                reason=message,
            )

        if status_code in {401, 403}:
            return ProviderErrorClassification(
                code="policy_rejected",
                category="policy",
                retryable=False,
                reason=message,
            )

        return ProviderErrorClassification(
            code="unclassified_error",
            category="execution",
            retryable=False,
            reason=message,
        )

    @staticmethod
    def _extract_status_code(error: Exception) -> int | None:
        status = getattr(error, "status_code", None)
        if isinstance(status, int):
            return status
        details = getattr(error, "details", None)
        if isinstance(details, dict):
            details_status = details.get("status_code")
            if isinstance(details_status, int):
                return details_status
        return None

    @staticmethod
    def _extract_message(error: Exception) -> str:
        detail = getattr(error, "detail", None)
        if isinstance(detail, dict):
            message = detail.get("message")
            if isinstance(message, str) and message.strip():
                return message
            nested_error = detail.get("error")
            if isinstance(nested_error, dict):
                nested_message = nested_error.get("message")
                if isinstance(nested_message, str) and nested_message.strip():
                    return nested_message

        details = getattr(error, "details", None)
        if isinstance(details, dict):
            message = details.get("message")
            if isinstance(message, str) and message.strip():
                return message
            nested_error = details.get("error")
            if isinstance(nested_error, dict):
                nested_message = nested_error.get("message")
                if isinstance(nested_message, str) and nested_message.strip():
                    return nested_message

        message_attr = getattr(error, "message", None)
        if isinstance(message_attr, str) and message_attr.strip():
            return message_attr

        return str(error)

    @staticmethod
    def _extract_code(error: Exception) -> str | None:
        detail = getattr(error, "detail", None)
        if isinstance(detail, dict):
            detail_code = detail.get("code")
            if isinstance(detail_code, str):
                return detail_code
            nested_error = detail.get("error")
            if isinstance(nested_error, dict):
                nested_code = nested_error.get("code")
                if isinstance(nested_code, str):
                    return nested_code

        details = getattr(error, "details", None)
        if isinstance(details, dict):
            details_code = details.get("code")
            if isinstance(details_code, str):
                return details_code
            nested_error = details.get("error")
            if isinstance(nested_error, dict):
                nested_code = nested_error.get("code")
                if isinstance(nested_code, str):
                    return nested_code

        code_attr = getattr(error, "code", None)
        if isinstance(code_attr, str):
            return code_attr
        return None

    def _is_permanent_model_not_found(
        self,
        *,
        status_code: int | None,
        normalized_code: str,
        normalized_message: str,
    ) -> bool:
        if normalized_code in self._PERMANENT_MODEL_CODES:
            return True

        if (
            status_code in {400, 404}
            and "model" in normalized_message
            and (
                "not found" in normalized_message
                or "does not exist" in normalized_message
                or "unknown model" in normalized_message
                or "unsupported" in normalized_message
            )
        ):
            return True

        return "model_not_found" in normalized_message
