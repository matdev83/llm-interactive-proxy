"""
Unit tests for Gemini base connector data models.

These tests verify that credential models work correctly with validation,
backward compatibility, and helper methods.
"""

from datetime import datetime, timezone
from typing import Any

import pytest
from freezegun import freeze_time
from src.connectors.gemini_base.models import GeminiOAuthCredentials


def make_creds(**kwargs: Any) -> GeminiOAuthCredentials:
    """Create GeminiOAuthCredentials with mypy-safe typing."""
    return GeminiOAuthCredentials(**kwargs)  # type: ignore[call-arg]


class TestGeminiOAuthCredentials:
    """Test GeminiOAuthCredentials model."""

    def test_required_fields_validation(self) -> None:
        """Verify that access_token is required."""
        with pytest.raises(ValueError, match="access_token"):
            make_creds()

    def test_access_token_validation(self) -> None:
        """Verify that access_token must be non-empty."""
        with pytest.raises(ValueError, match="access_token"):
            make_creds(access_token="")

        with pytest.raises(ValueError, match="access_token"):
            make_creds(access_token=None)  # type: ignore[arg-type]

    def test_optional_fields(self) -> None:
        """Verify that optional fields can be None."""
        creds = make_creds(access_token="test_token")
        assert creds.access_token == "test_token"
        assert creds.refresh_token is None
        assert creds.expiry_date is None
        assert creds.project_id is None

    def test_all_fields(self) -> None:
        """Verify that all fields can be set."""
        creds = make_creds(
            access_token="test_token",
            refresh_token="refresh_token",
            expiry_date=1000000000000,
            project_id="test-project",
        )
        assert creds.access_token == "test_token"
        assert creds.refresh_token == "refresh_token"
        assert creds.expiry_date == 1000000000000
        assert creds.project_id == "test-project"

    def test_refresh_token_validation(self) -> None:
        """Verify that refresh_token must be non-empty if provided."""
        with pytest.raises(ValueError, match="refresh_token"):
            make_creds(access_token="test", refresh_token="")

        # None is allowed
        creds = make_creds(access_token="test", refresh_token=None)
        assert creds.refresh_token is None

    def test_expiry_date_validation(self) -> None:
        """Verify that expiry_date must be non-negative if provided."""
        with pytest.raises(ValueError, match="expiry_date"):
            make_creds(access_token="test", expiry_date=-1)

        # None is allowed
        creds = make_creds(access_token="test", expiry_date=None)
        assert creds.expiry_date is None

    def test_extra_fields_preservation(self) -> None:
        """Verify that extra fields are preserved for backward compatibility."""
        creds = make_creds(
            access_token="test",
            extra_field="extra_value",  # type: ignore[arg-type]
            another_field=123,  # type: ignore[arg-type]
        )
        assert creds.access_token == "test"
        # Extra fields are preserved in model_dump
        dumped = creds.to_dict()
        assert "extra_field" in dumped
        assert dumped["extra_field"] == "extra_value"
        assert "another_field" in dumped
        assert dumped["another_field"] == 123

    def test_from_dict_backward_compatibility(self) -> None:
        """Verify that from_dict works for backward compatibility."""
        data = {
            "access_token": "test_token",
            "refresh_token": "refresh_token",
            "expiry_date": 1000000000000,
            "project_id": "test-project",
        }
        creds = GeminiOAuthCredentials.from_dict(data)
        assert creds.access_token == "test_token"
        assert creds.refresh_token == "refresh_token"
        assert creds.expiry_date == 1000000000000
        assert creds.project_id == "test-project"

    def test_to_dict_conversion(self) -> None:
        """Verify that to_dict converts to dictionary correctly."""
        creds = make_creds(
            access_token="test_token",
            refresh_token="refresh_token",
            expiry_date=1000000000000,
            project_id="test-project",
        )
        data = creds.to_dict()
        assert isinstance(data, dict)
        assert data["access_token"] == "test_token"
        assert data["refresh_token"] == "refresh_token"
        assert data["expiry_date"] == 1000000000000
        assert data["project_id"] == "test-project"

    def test_is_expired_not_expired(self) -> None:
        """Verify that is_expired returns False for non-expired tokens."""
        # Token expires far in the future
        future_timestamp = 2000000000000  # Year 2033
        creds = make_creds(access_token="test", expiry_date=future_timestamp)
        assert not creds.is_expired()

    def test_is_expired_no_expiry_date(self) -> None:
        """Verify that is_expired returns False when expiry_date is None."""
        creds = make_creds(access_token="test", expiry_date=None)
        assert not creds.is_expired()

    def test_is_expired_with_buffer(self) -> None:
        """Verify that is_expired respects buffer_seconds."""
        # Use fixed timestamp for deterministic test
        # Token expires in 30 seconds from base time
        base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        base_time_ms = int(base_time.timestamp() * 1000)
        expiry_ms = base_time_ms + 30000  # 30 seconds later
        creds = make_creds(access_token="test", expiry_date=expiry_ms)

        with freeze_time(base_time):
            # With default 60s buffer, should be expired (current time > expiry - 60s)
            # Since expiry is only 30s in the future, and buffer is 60s, it's expired
            assert creds.is_expired()

            # With 10s buffer, should not be expired
            assert not creds.is_expired(buffer_seconds=10.0)

    def test_has_refresh_token(self) -> None:
        """Verify that has_refresh_token works correctly."""
        creds_no_refresh = make_creds(access_token="test")
        assert not creds_no_refresh.has_refresh_token()

        creds_with_refresh = make_creds(access_token="test", refresh_token="refresh")
        assert creds_with_refresh.has_refresh_token()

        # Empty string is rejected by validator, so we test None case
        creds_none_refresh = make_creds(access_token="test", refresh_token=None)
        assert not creds_none_refresh.has_refresh_token()
