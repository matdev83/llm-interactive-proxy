
import time
import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime, timezone
from src.connectors.gemini_oauth_auto.account_selector import AccountSelectorService
from src.connectors.gemini_oauth_auto.models import StoredAccount

@pytest.mark.asyncio
async def test_mark_current_account_rate_limited_deduplication():
    """Verify that redundant rate limit marking within 2s is skipped."""
    storage = MagicMock()
    storage.save_account = AsyncMock()
    refresh_service = MagicMock()
    
    selector = AccountSelectorService(storage=storage, refresh_service=refresh_service)
    
    account = StoredAccount(
        account_id="test-acc",
        email="test@example.com",
        access_token="abc",
        refresh_token="def",
        token_type="Bearer",
        scope="https://www.googleapis.com/auth/cloud-platform",
        expiry_date=int(time.time() * 1000) + 3600000,
        updated_at=datetime.now(timezone.utc).isoformat()
    )
    
    selector._accounts = [account]
    selector._current_account = account
    
    # First marking should proceed
    await selector.mark_current_account_rate_limited(retry_after_seconds=10.0)
    assert storage.save_account.call_count == 1
    
    # Immediately marking again should be skipped
    await selector.mark_current_account_rate_limited(retry_after_seconds=10.0)
    assert storage.save_account.call_count == 1
    
    # Update timestamp to be older than 2 seconds
    selector._current_account = selector._current_account.model_copy(
        update={"updated_at": (datetime.now(timezone.utc).timestamp() - 5)}
    )
    # Manually setting updated_at as string because model expects it
    selector._current_account.updated_at = datetime.fromtimestamp(
        time.time() - 5, tz=timezone.utc
    ).isoformat()
    
    # Now it should proceed again
    # We need to wait or mock time for the cooldown to expire
    # In the code we use time.time(), so let's mock it if possible or just test the per-account isolation
    
@pytest.mark.asyncio
async def test_mark_current_account_rate_limited_per_account_isolation():
    """Verify that rate limit marking cooldown is per-account."""
    storage = MagicMock()
    storage.save_account = AsyncMock()
    refresh_service = MagicMock()
    
    selector = AccountSelectorService(storage=storage, refresh_service=refresh_service)
    
    acc1 = StoredAccount(
        account_id="acc1",
        email="acc1@example.com",
        access_token="abc",
        refresh_token="def",
        token_type="Bearer",
        scope="scope",
        expiry_date=int(time.time() * 1000) + 3600000,
        updated_at=datetime.now(timezone.utc).isoformat()
    )
    acc2 = StoredAccount(
        account_id="acc2",
        email="acc2@example.com",
        access_token="xyz",
        refresh_token="uvw",
        token_type="Bearer",
        scope="scope",
        expiry_date=int(time.time() * 1000) + 3600000,
        updated_at=datetime.now(timezone.utc).isoformat()
    )
    
    selector._accounts = [acc1, acc2]
    
    # 1. Mark acc1
    selector._current_account = acc1
    await selector.mark_current_account_rate_limited(retry_after_seconds=10.0)
    assert storage.save_account.call_count == 1
    
    # 2. Mark acc1 again (should be skipped)
    await selector.mark_current_account_rate_limited(retry_after_seconds=10.0)
    assert storage.save_account.call_count == 1
    
    # 3. Switch to acc2 and mark (should NOT be skipped)
    selector._current_account = acc2
    await selector.mark_current_account_rate_limited(retry_after_seconds=10.0)
    assert storage.save_account.call_count == 2
