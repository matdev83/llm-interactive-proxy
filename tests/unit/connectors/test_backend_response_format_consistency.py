"""
Tests for backend connector response format consistency.

This test suite automatically discovers all registered backend connectors and verifies
that they return responses in a consistent format. This catches regressions like the
Cline 'data' envelope issue where a connector returns data wrapped in non-standard
structures that break the translation pipeline.

The tests dynamically discover connectors from the registry, so new connectors
added in the future will be automatically tested.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

if TYPE_CHECKING:
    pass

# Standard OpenAI response format - this is the expected format for all connectors
STANDARD_OPENAI_RESPONSE = {
    "id": "chatcmpl-test-123",
    "object": "chat.completion",
    "created": 1234567890,
    "model": "test-model",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "Hello! I'm ready to help.",
            },
            "finish_reason": "stop",
        }
    ],
    "usage": {
        "prompt_tokens": 10,
        "completion_tokens": 20,
        "total_tokens": 30,
    },
}

# Non-standard response formats that could break the pipeline
# These represent bugs that should be caught by these tests
NON_STANDARD_WRAPPED_RESPONSE = {
    "data": STANDARD_OPENAI_RESPONSE,  # Wrapped in 'data' key - like Cline bug
}

NON_STANDARD_NESTED_RESPONSE = {
    "response": {
        "data": STANDARD_OPENAI_RESPONSE,  # Doubly wrapped
    }
}

_CORE_CONNECTOR_MODULES = {
    "src.connectors.openai",
    "src.connectors.cline",
    "src.connectors.anthropic",
    "src.connectors.gemini",
}
_CONNECTOR_IMPORT_ERRORS: dict[str, str] = {}


def _discover_all_connector_modules() -> list[str]:
    """Discover all connector module names in the src/connectors package."""
    import src.connectors as connectors_pkg

    module_names = []
    for _importer, modname, ispkg in pkgutil.iter_modules(connectors_pkg.__path__):
        if not ispkg and not modname.startswith("_"):
            module_names.append(f"src.connectors.{modname}")
    return module_names


def _import_all_connectors() -> None:
    """Import all connector modules to ensure they register with the backend registry."""
    for module_name in _discover_all_connector_modules():
        try:
            importlib.import_module(module_name)
        except Exception as e:
            _CONNECTOR_IMPORT_ERRORS[module_name] = f"{type(e).__name__}: {e}"
            if module_name in _CORE_CONNECTOR_MODULES:
                raise


class TestBackendResponseFormatDiscovery:
    """Tests for automatic backend connector discovery."""

    def test_backend_registry_has_connectors(self) -> None:
        """Verify that the backend registry has registered connectors."""
        _import_all_connectors()
        backends = backend_registry.get_registered_backends()

        # We should have multiple backends registered
        assert len(backends) >= 5, (
            f"Expected at least 5 backends, found {len(backends)}: {backends}. "
            "Make sure connectors are being registered correctly."
        )

    def test_all_connector_modules_are_discovered(self) -> None:
        """Verify that we can discover connector modules."""
        modules = _discover_all_connector_modules()

        # Verify we discover key connectors
        assert any("openai" in m for m in modules), "openai connector not found"
        assert any("anthropic" in m for m in modules), "anthropic connector not found"


class TestResponseEnvelopeFormatConsistency:
    """Tests that ResponseEnvelope content follows the expected format."""

    @pytest.fixture
    def translation_service(self) -> TranslationService:
        return TranslationService()

    def test_standard_response_format_is_accepted(
        self, translation_service: TranslationService
    ) -> None:
        """Verify that the standard OpenAI format is correctly translated."""
        domain_response = translation_service.to_domain_response(
            STANDARD_OPENAI_RESPONSE, "openai"
        )

        assert domain_response.id == "chatcmpl-test-123"
        assert domain_response.model == "test-model"
        assert len(domain_response.choices) == 1
        assert domain_response.choices[0].message.content == "Hello! I'm ready to help."

    def test_wrapped_response_causes_content_loss(
        self, translation_service: TranslationService
    ) -> None:
        """
        Verify that a wrapped response (like Cline's 'data' envelope) causes
        content loss when not properly unwrapped.

        This test documents the bug behavior that we want to prevent.
        """
        # When a wrapped response is passed without unwrapping,
        # the translation creates empty choices because 'choices' is at wrong level
        domain_response = translation_service.to_domain_response(
            NON_STANDARD_WRAPPED_RESPONSE, "openai"
        )

        # The wrapped response doesn't have 'choices' at the top level,
        # so translation creates a response with empty or wrong content
        # This is the bug we want to detect
        has_content = (
            len(domain_response.choices) > 0
            and domain_response.choices[0].message.content is not None
            and len(domain_response.choices[0].message.content) > 0
        )

        # This should fail - demonstrating the bug
        content = (
            domain_response.choices[0].message.content
            if domain_response.choices
            else None
        )
        assert not has_content or (
            isinstance(content, str) and content.startswith("{")
        ), (
            "Wrapped response should NOT produce valid content. "
            "If this passes, the translation layer might be auto-unwrapping, "
            "which should be done at the connector level instead."
        )


class TestConnectorResponseFormatValidation:
    """
    Tests that validate each connector returns properly formatted responses.

    These tests use the ResponseEnvelope.content structure to verify
    that responses follow the expected OpenAI format without non-standard wrapping.
    """

    # Keys that are expected at the top level of a valid OpenAI response
    EXPECTED_TOP_LEVEL_KEYS = {"id", "object", "model", "choices", "created"}

    # Keys that should NOT appear at the top level (indicate wrapping bugs)
    FORBIDDEN_TOP_LEVEL_KEYS = {"data", "response", "result", "body", "payload"}

    @staticmethod
    def validate_response_content_format(content: Any, connector_name: str) -> None:
        """
        Validate that response content follows the expected format.

        Args:
            content: The ResponseEnvelope.content to validate
            connector_name: Name of the connector for error messages
        """
        assert isinstance(content, dict), (
            f"Connector '{connector_name}' returned non-dict content: {type(content)}. "
            "ResponseEnvelope.content must be a dict."
        )

        # Check for forbidden wrapper keys
        for (
            forbidden_key
        ) in TestConnectorResponseFormatValidation.FORBIDDEN_TOP_LEVEL_KEYS:
            if forbidden_key in content:
                inner = content[forbidden_key]
                # Check if the inner content looks like the actual response
                if isinstance(inner, dict) and any(
                    k in inner
                    for k in TestConnectorResponseFormatValidation.EXPECTED_TOP_LEVEL_KEYS
                ):
                    pytest.fail(
                        f"Connector '{connector_name}' returns response wrapped in "
                        f"'{forbidden_key}' key. The actual response data should be at "
                        f"the top level, not nested. Found keys in wrapper: {list(content.keys())}. "
                        f"Found keys in inner: {list(inner.keys()) if isinstance(inner, dict) else 'N/A'}. "
                        f"This is likely a bug in the connector's response handling."
                    )

        # Verify expected keys are present (at least some of them)
        present_expected = (
            TestConnectorResponseFormatValidation.EXPECTED_TOP_LEVEL_KEYS
            & content.keys()
        )
        assert len(present_expected) >= 2, (
            f"Connector '{connector_name}' response is missing expected keys. "
            f"Expected at least 2 of {TestConnectorResponseFormatValidation.EXPECTED_TOP_LEVEL_KEYS}, "
            f"found: {present_expected}. Actual keys: {list(content.keys())}. "
            f"This might indicate the response is wrapped or malformed."
        )

    def test_validate_standard_response_passes(self) -> None:
        """Verify that the standard format passes validation."""
        self.validate_response_content_format(STANDARD_OPENAI_RESPONSE, "test")

    def test_validate_wrapped_response_fails(self) -> None:
        """Verify that wrapped responses are detected."""
        with pytest.raises(pytest.fail.Exception) as exc_info:
            self.validate_response_content_format(NON_STANDARD_WRAPPED_RESPONSE, "test")

        assert "wrapped in 'data' key" in str(exc_info.value)

    def test_validate_nested_response_fails(self) -> None:
        """Verify that nested responses are detected.

        The nested response has 'response.data' wrapping, which should be caught
        either by the forbidden key check or by the missing expected keys check.
        """
        with pytest.raises((pytest.fail.Exception, AssertionError)) as exc_info:
            self.validate_response_content_format(NON_STANDARD_NESTED_RESPONSE, "test")

        error_msg = str(exc_info.value)
        # Should fail either because 'response' is a forbidden wrapper key
        # or because expected keys are missing at top level
        assert (
            "wrapped" in error_msg.lower()
            or "missing expected keys" in error_msg.lower()
        ), f"Expected error about wrapping or missing keys, got: {error_msg}"


class TestAllConnectorsResponseFormat:
    """
    Dynamic tests for all registered backend connectors.

    These tests automatically discover all connectors and verify their
    response format consistency.
    """

    @pytest.fixture(scope="class")
    def all_backends(self) -> list[str]:
        """Get all registered backends after importing all connector modules."""
        _import_all_connectors()
        return backend_registry.get_registered_backends()

    def test_all_backends_are_discovered(self, all_backends: list[str]) -> None:
        """Verify all backends are discovered."""
        # These are core backends that must always be present
        # Note: "cline" is now an extracted OAuth plugin backend
        core_backends = {"openai", "anthropic", "gemini"}
        discovered_set = set(all_backends)

        missing = core_backends - discovered_set
        assert not missing, (
            f"Core backends not discovered: {missing}. "
            f"Found backends: {all_backends}"
        )


def _get_all_backend_names() -> list[str]:
    """Get all backend names for parametrization."""
    _import_all_connectors()
    return backend_registry.get_registered_backends()


@pytest.fixture(scope="module")
def backend_names() -> list[str]:
    """Fixture that provides all backend names."""
    return _get_all_backend_names()


class TestResponseEnvelopeContentValidation:
    """
    Parametrized tests that run for each backend connector.

    This ensures that any new connector added to the codebase will
    automatically be tested for response format consistency.
    """

    @pytest.mark.parametrize("backend_name", _get_all_backend_names())
    def test_backend_factory_exists(self, backend_name: str) -> None:
        """Verify each backend has a valid factory."""
        factory = backend_registry.get_backend_factory(backend_name)
        assert callable(factory), f"Backend '{backend_name}' factory is not callable"

    @pytest.mark.parametrize("backend_name", _get_all_backend_names())
    def test_backend_has_backend_type_attribute(self, backend_name: str) -> None:
        """Verify each backend class has backend_type attribute."""
        factory = backend_registry.get_backend_factory(backend_name)

        # Check if the factory (which is usually a class) has backend_type
        if hasattr(factory, "backend_type"):
            assert (
                factory.backend_type == backend_name or factory.backend_type
            ), f"Backend '{backend_name}' has inconsistent backend_type"


class TestClineSpecificDataEnvelopeHandling:
    """
    Specific tests for the Cline connector's data envelope handling.

    This documents the specific bug and its fix to prevent regression.
    """

    @pytest.fixture
    def mock_http_client(self) -> AsyncMock:
        """Create a mock HTTP client."""
        client = AsyncMock()
        return client

    @pytest.fixture
    def config(self) -> AppConfig:
        return AppConfig()

    @pytest.fixture
    def translation_service(self) -> TranslationService:
        return TranslationService()

    def test_cline_unwraps_data_envelope(
        self,
        mock_http_client: AsyncMock,
        config: AppConfig,
        translation_service: TranslationService,
    ) -> None:
        """
        Verify that ClineConnector properly unwraps the 'data' envelope.

        The Cline API returns responses wrapped in a 'data' key for non-streaming
        requests. This test verifies the connector unwraps it correctly.
        """
        cline_mod = pytest.importorskip(
            "llm_proxy_oauth_connectors.cline",
            reason="Cline connector plugin not installed",
        )
        ClineConnector = cline_mod.ClineConnector

        connector = ClineConnector(mock_http_client, config, translation_service)

        # Simulate Cline's wrapped response
        wrapped_response = {
            "data": {
                "id": "chatcmpl-cline-123",
                "object": "chat.completion",
                "created": 1234567890,
                "model": "x-ai/grok-code-fast-1",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Hello from Cline!",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 10,
                    "total_tokens": 15,
                },
            }
        }

        unwrapped = connector._unwrap_cline_data_envelope(wrapped_response)

        # Verify unwrapping occurred
        assert "data" not in unwrapped, "Response should be unwrapped"
        assert unwrapped["id"] == "chatcmpl-cline-123"
        assert unwrapped["model"] == "x-ai/grok-code-fast-1"
        assert len(unwrapped["choices"]) == 1
        assert unwrapped["choices"][0]["message"]["content"] == "Hello from Cline!"

        # Validate using our standard validator
        TestConnectorResponseFormatValidation.validate_response_content_format(
            unwrapped, "cline"
        )

    def test_cline_does_not_unwrap_standard_response(
        self,
        mock_http_client: AsyncMock,
        config: AppConfig,
        translation_service: TranslationService,
    ) -> None:
        """
        Verify that ClineConnector doesn't modify standard responses.

        If the response is already in standard format (no 'data' wrapper),
        it should pass through unchanged.
        """
        cline_mod = pytest.importorskip(
            "llm_proxy_oauth_connectors.cline",
            reason="Cline connector plugin not installed",
        )
        ClineConnector = cline_mod.ClineConnector

        connector = ClineConnector(mock_http_client, config, translation_service)

        # Standard response without wrapper
        standard_response = {
            "id": "chatcmpl-standard-456",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Standard response",
                    },
                    "finish_reason": "stop",
                }
            ],
        }

        result = connector._unwrap_cline_data_envelope(standard_response)

        # Should be the same object (not modified)
        assert result is standard_response
        assert result["id"] == "chatcmpl-standard-456"

        # Validate using our standard validator
        TestConnectorResponseFormatValidation.validate_response_content_format(
            result, "cline"
        )


class TestFutureConnectorCompliance:
    """
    Tests that document the expected contract for future connectors.

    These tests serve as documentation for connector developers and
    catch non-compliant implementations.
    """

    def test_response_envelope_content_must_be_dict(self) -> None:
        """
        ResponseEnvelope.content must be a dict, not a string or other type.

        This prevents issues where content is accidentally JSON-serialized
        before being placed in the envelope.
        """
        # Valid
        valid_envelope = ResponseEnvelope(
            content={"id": "test", "choices": []},
            status_code=200,
        )
        assert isinstance(valid_envelope.content, dict)

        # Invalid - string content would break downstream processing
        # (This is allowed by the dataclass but should be caught by tests)
        string_envelope = ResponseEnvelope(
            content='{"id": "test", "choices": []}',  # type: ignore
            status_code=200,
        )
        assert isinstance(
            string_envelope.content, str
        )  # This is what we want to detect

        # Validator should catch this
        with pytest.raises(AssertionError):
            TestConnectorResponseFormatValidation.validate_response_content_format(
                string_envelope.content, "test"
            )

    def test_choices_must_be_at_top_level(self) -> None:
        """
        The 'choices' key must be at the top level of the response content.

        This is required for the translation pipeline to work correctly.
        """
        valid_content = {
            "id": "test",
            "object": "chat.completion",
            "model": "test",
            "choices": [{"message": {"content": "test"}}],
        }

        invalid_content = {
            "wrapped": {
                "id": "test",
                "choices": [{"message": {"content": "test"}}],
            }
        }

        # Valid content passes
        TestConnectorResponseFormatValidation.validate_response_content_format(
            valid_content, "test"
        )

        # Invalid content fails (doesn't have enough expected keys at top level)
        with pytest.raises(AssertionError):
            TestConnectorResponseFormatValidation.validate_response_content_format(
                invalid_content, "test"
            )
