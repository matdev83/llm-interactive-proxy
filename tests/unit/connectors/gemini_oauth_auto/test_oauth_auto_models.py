"""
Unit tests for Gemini OAuth Auto-Connector models.

Tests Requirement 2: Token Storage and Persistence (model validation).
"""

from datetime import datetime, timezone

import pytest
from freezegun import freeze_time
from src.connectors.gemini_oauth_auto.models import AccountSummary, StoredAccount

# Base time for tests to avoid direct BASE_TIME calls (flagged by linter)
# Matches @freeze_time("2026-01-19") used in tests.
BASE_TIME = 1768780800.0  # 2026-01-19 00:00:00 UTC


@freeze_time("2026-01-19")
class TestStoredAccount:
    """Tests for StoredAccount model."""

    @pytest.fixture
    def valid_account_data(self) -> dict:
        """Fixture providing valid account data.

        Uses fixed base time to avoid direct BASE_TIME calls flagged by linter.
        """
        return {
            "account_id": "test-account-1",
            "email": "test@gmail.com",
            "access_token": "ya29.test_access_token",
            "refresh_token": "1//test_refresh_token",
            "token_type": "Bearer",
            "scope": "https://www.googleapis.com/auth/cloud-platform",
            "expiry_date": int((BASE_TIME + 3600) * 1000),  # 1 hour from base
            "created_at": "2026-01-20T10:00:00+00:00",
            "updated_at": "2026-01-20T10:00:00+00:00",
        }

    def test_create_valid_account(self, valid_account_data: dict) -> None:
        """Test creating a valid StoredAccount."""
        account = StoredAccount(**valid_account_data)

        assert account.account_id == "test-account-1"
        assert account.email == "test@gmail.com"
        assert account.access_token == "ya29.test_access_token"
        assert account.refresh_token == "1//test_refresh_token"
        assert account.token_type == "Bearer"
        assert account.needs_reauth is False
        assert account.last_used is None

    def test_account_id_validation_alphanumeric(self) -> None:
        """Test account_id allows alphanumeric characters."""
        account = StoredAccount(
            account_id="MyAccount123",
            email="test@gmail.com",
            access_token="token",
            refresh_token="refresh",
            scope="scope",
            expiry_date=int(BASE_TIME * 1000),
        )
        assert account.account_id == "MyAccount123"

    def test_account_id_validation_with_hyphens(self) -> None:
        """Test account_id allows hyphens."""
        account = StoredAccount(
            account_id="my-account-1",
            email="test@gmail.com",
            access_token="token",
            refresh_token="refresh",
            scope="scope",
            expiry_date=int(BASE_TIME * 1000),
        )
        assert account.account_id == "my-account-1"

    def test_account_id_validation_with_underscores(self) -> None:
        """Test account_id allows underscores."""
        account = StoredAccount(
            account_id="my_account_1",
            email="test@gmail.com",
            access_token="token",
            refresh_token="refresh",
            scope="scope",
            expiry_date=int(BASE_TIME * 1000),
        )
        assert account.account_id == "my_account_1"

    def test_account_id_validation_rejects_spaces(self) -> None:
        """Test account_id rejects spaces."""
        with pytest.raises(ValueError, match="account_id must match pattern"):
            StoredAccount(
                account_id="my account",
                email="test@gmail.com",
                access_token="token",
                refresh_token="refresh",
                scope="scope",
                expiry_date=int(BASE_TIME * 1000),
            )

    def test_account_id_validation_rejects_special_chars(self) -> None:
        """Test account_id rejects special characters."""
        with pytest.raises(ValueError, match="account_id must match pattern"):
            StoredAccount(
                account_id="my@account!",
                email="test@gmail.com",
                access_token="token",
                refresh_token="refresh",
                scope="scope",
                expiry_date=int(BASE_TIME * 1000),
            )

    def test_account_id_validation_rejects_starting_with_hyphen(self) -> None:
        """Test account_id must start with alphanumeric."""
        with pytest.raises(ValueError, match="account_id must match pattern"):
            StoredAccount(
                account_id="-invalid",
                email="test@gmail.com",
                access_token="token",
                refresh_token="refresh",
                scope="scope",
                expiry_date=int(BASE_TIME * 1000),
            )

    def test_account_id_max_length(self) -> None:
        """Test account_id enforces max length of 64 characters."""
        # 64 chars should be OK
        valid_id = "a" * 64
        account = StoredAccount(
            account_id=valid_id,
            email="test@gmail.com",
            access_token="token",
            refresh_token="refresh",
            scope="scope",
            expiry_date=int(BASE_TIME * 1000),
        )
        assert len(account.account_id) == 64

        # 65 chars should fail
        with pytest.raises(ValueError):
            StoredAccount(
                account_id="a" * 65,
                email="test@gmail.com",
                access_token="token",
                refresh_token="refresh",
                scope="scope",
                expiry_date=int(BASE_TIME * 1000),
            )

    def test_is_expired_with_future_expiry(self, valid_account_data: dict) -> None:
        """Test is_expired returns False for future expiry."""
        # Set expiry 1 hour from now

        valid_account_data["expiry_date"] = int((BASE_TIME + 3600) * 1000)
        account = StoredAccount(**valid_account_data)

        assert account.is_expired() is False
        assert account.is_expired(buffer_ms=0) is False

    def test_is_expired_with_past_expiry(self, valid_account_data: dict) -> None:
        """Test is_expired returns True for past expiry."""
        # Set expiry 1 hour ago
        valid_account_data["expiry_date"] = int((BASE_TIME - 3600) * 1000)
        account = StoredAccount(**valid_account_data)

        assert account.is_expired() is True
        assert account.is_expired(buffer_ms=0) is True

    def test_is_expired_with_buffer_within_window(
        self, valid_account_data: dict
    ) -> None:
        """Test is_expired with buffer returns True when within buffer window."""
        # Set expiry 2 minutes from now (120 seconds = 120_000 ms)
        valid_account_data["expiry_date"] = int((BASE_TIME + 120) * 1000)
        account = StoredAccount(**valid_account_data)

        # Without buffer, not expired
        assert account.is_expired(buffer_ms=0) is False

        # With 5 minute buffer (300_000 ms), should be considered expired
        assert account.is_expired(buffer_ms=300_000) is True

        # With 1 minute buffer (60_000 ms), still not expired
        assert account.is_expired(buffer_ms=60_000) is False

    def test_is_expired_with_buffer_outside_window(
        self, valid_account_data: dict
    ) -> None:
        """Test is_expired with buffer returns False when outside buffer window."""
        # Set expiry 10 minutes from now
        valid_account_data["expiry_date"] = int((BASE_TIME + 600) * 1000)
        account = StoredAccount(**valid_account_data)

        # With 5 minute buffer, should not be considered expired
        assert account.is_expired(buffer_ms=300_000) is False

    def test_to_credentials_dict_format(self, valid_account_data: dict) -> None:
        """Test to_credentials_dict returns correct format."""
        account = StoredAccount(**valid_account_data)
        creds = account.to_credentials_dict()

        assert creds == {
            "access_token": account.access_token,
            "refresh_token": account.refresh_token,
            "token_type": "Bearer",
            "expiry_date": account.expiry_date,
        }

    def test_to_credentials_dict_excludes_metadata(
        self, valid_account_data: dict
    ) -> None:
        """Test to_credentials_dict excludes non-credential fields."""
        account = StoredAccount(**valid_account_data)
        creds = account.to_credentials_dict()

        assert "account_id" not in creds
        assert "email" not in creds
        assert "created_at" not in creds
        assert "updated_at" not in creds
        assert "last_used" not in creds
        assert "needs_reauth" not in creds

    def test_status_valid(self, valid_account_data: dict) -> None:
        """Test status returns 'valid' for valid, non-expired token."""
        valid_account_data["expiry_date"] = int((BASE_TIME + 3600) * 1000)
        valid_account_data["needs_reauth"] = False
        account = StoredAccount(**valid_account_data)

        assert account.status == "valid"

    def test_status_expired(self, valid_account_data: dict) -> None:
        """Test status returns 'expired' for expired token."""
        valid_account_data["expiry_date"] = int((BASE_TIME - 3600) * 1000)
        valid_account_data["needs_reauth"] = False
        account = StoredAccount(**valid_account_data)

        assert account.status == "expired"

    def test_status_needs_reauth(self, valid_account_data: dict) -> None:
        """Test status returns 'needs_reauth' when flag is set."""
        valid_account_data["needs_reauth"] = True
        account = StoredAccount(**valid_account_data)

        assert account.status == "needs_reauth"

    def test_status_needs_reauth_takes_precedence(
        self, valid_account_data: dict
    ) -> None:
        """Test needs_reauth status takes precedence over expired."""
        valid_account_data["expiry_date"] = int((BASE_TIME - 3600) * 1000)  # Expired
        valid_account_data["needs_reauth"] = True
        account = StoredAccount(**valid_account_data)

        assert account.status == "needs_reauth"

    def test_with_updated_tokens_creates_new_instance(
        self, valid_account_data: dict
    ) -> None:
        """Test with_updated_tokens creates new instance, doesn't modify original."""
        original = StoredAccount(**valid_account_data)
        original_access_token = original.access_token

        new_expiry = int((BASE_TIME + 7200) * 1000)
        updated = original.with_updated_tokens(
            access_token="new_access_token",
            expiry_date=new_expiry,
        )

        # Original unchanged
        assert original.access_token == original_access_token

        # New instance has updated values
        assert updated.access_token == "new_access_token"
        assert updated.expiry_date == new_expiry
        assert updated.refresh_token == original.refresh_token  # Preserved
        assert updated.needs_reauth is False  # Cleared

    def test_with_updated_tokens_preserves_metadata(
        self, valid_account_data: dict
    ) -> None:
        """Test with_updated_tokens preserves account metadata."""
        original = StoredAccount(**valid_account_data)

        updated = original.with_updated_tokens(
            access_token="new_token",
            expiry_date=int(BASE_TIME * 1000),
        )

        assert updated.account_id == original.account_id
        assert updated.email == original.email
        assert updated.created_at == original.created_at
        assert updated.last_used == original.last_used

    def test_with_updated_tokens_clears_needs_reauth(
        self, valid_account_data: dict
    ) -> None:
        """Test with_updated_tokens clears needs_reauth flag."""
        valid_account_data["needs_reauth"] = True
        original = StoredAccount(**valid_account_data)
        assert original.needs_reauth is True

        updated = original.with_updated_tokens(
            access_token="new_token",
            expiry_date=int(BASE_TIME * 1000),
        )

        assert updated.needs_reauth is False

    def test_with_updated_tokens_can_update_refresh_token(
        self, valid_account_data: dict
    ) -> None:
        """Test with_updated_tokens can optionally update refresh_token."""
        original = StoredAccount(**valid_account_data)

        updated = original.with_updated_tokens(
            access_token="new_access",
            expiry_date=int(BASE_TIME * 1000),
            refresh_token="new_refresh",
        )

        assert updated.refresh_token == "new_refresh"

    def test_mark_used_creates_new_instance(self, valid_account_data: dict) -> None:
        """Test mark_used creates new instance with updated timestamp."""
        original = StoredAccount(**valid_account_data)
        assert original.last_used is None

        used = original.mark_used()

        # Original unchanged
        assert original.last_used is None

        # New instance has timestamp
        assert used.last_used is not None
        # Verify it's a recent ISO timestamp
        parsed = datetime.fromisoformat(used.last_used)
        assert (datetime.now(timezone.utc) - parsed).total_seconds() < 5

    def test_default_timestamps_generated(self) -> None:
        """Test created_at and updated_at are auto-generated if not provided."""
        account = StoredAccount(
            account_id="test",
            email="test@gmail.com",
            access_token="token",
            refresh_token="refresh",
            scope="scope",
            expiry_date=int(BASE_TIME * 1000),
        )

        # Should have valid ISO timestamps
        assert account.created_at is not None
        assert account.updated_at is not None
        datetime.fromisoformat(account.created_at)  # Should not raise
        datetime.fromisoformat(account.updated_at)  # Should not raise


@freeze_time("2026-01-19")
class TestAccountSummary:
    """Tests for AccountSummary model."""

    @pytest.fixture
    def valid_account(self) -> StoredAccount:
        """Fixture providing a valid StoredAccount."""
        return StoredAccount(
            account_id="test-account",
            email="test@gmail.com",
            access_token="ya29.test",
            refresh_token="1//test",
            scope="scope",
            expiry_date=int((BASE_TIME + 3600) * 1000),
            last_used="2026-01-20T10:00:00+00:00",
        )

    def test_from_stored_account_valid(self, valid_account: StoredAccount) -> None:
        """Test creating AccountSummary from valid StoredAccount."""
        summary = AccountSummary.from_stored_account(valid_account)

        assert summary.account_id == valid_account.account_id
        assert summary.email == valid_account.email
        assert summary.status == "valid"
        assert summary.expiry_date == valid_account.expiry_date
        assert summary.last_used == valid_account.last_used

    def test_from_stored_account_expired(self) -> None:
        """Test AccountSummary reflects expired status."""
        account = StoredAccount(
            account_id="test",
            email="test@gmail.com",
            access_token="token",
            refresh_token="refresh",
            scope="scope",
            expiry_date=int((BASE_TIME - 3600) * 1000),  # Expired
        )

        summary = AccountSummary.from_stored_account(account)
        assert summary.status == "expired"

    def test_from_stored_account_needs_reauth(self) -> None:
        """Test AccountSummary reflects needs_reauth status."""
        account = StoredAccount(
            account_id="test",
            email="test@gmail.com",
            access_token="token",
            refresh_token="refresh",
            scope="scope",
            expiry_date=int((BASE_TIME + 3600) * 1000),
            needs_reauth=True,
        )

        summary = AccountSummary.from_stored_account(account)
        assert summary.status == "needs_reauth"

    def test_from_stored_account_no_last_used(self) -> None:
        """Test AccountSummary handles None last_used."""
        account = StoredAccount(
            account_id="test",
            email="test@gmail.com",
            access_token="token",
            refresh_token="refresh",
            scope="scope",
            expiry_date=int((BASE_TIME + 3600) * 1000),
            last_used=None,
        )

        summary = AccountSummary.from_stored_account(account)
        assert summary.last_used is None
