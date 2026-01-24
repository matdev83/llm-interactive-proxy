
import asyncio
from unittest.mock import AsyncMock, MagicMock
from src.connectors.gemini_oauth_auto.errors import TokenRefreshError

async def test_repro():
    refresh_service = MagicMock()
    # Case 1: side_effect as exception instance
    refresh_service.refresh_if_needed = AsyncMock(side_effect=TokenRefreshError("Transient error"))
    
    try:
        print("Calling refresh_if_needed (single exception side_effect)...")
        await refresh_service.refresh_if_needed()
    except TokenRefreshError:
        print("Caught expected TokenRefreshError (single)")
    except Exception as e:
        print(f"Caught unexpected exception: {type(e)}")

    # Case 2: side_effect as iterable with exception instance
    refresh_service.refresh_if_needed = AsyncMock(side_effect=[
        TokenRefreshError("Invalid grant", needs_reauth=True, account_id="account-1"),
        "success"
    ])

    try:
        print("Calling refresh_if_needed (iterable exception side_effect)...")
        await refresh_service.refresh_if_needed()
    except TokenRefreshError:
        print("Caught expected TokenRefreshError (iterable)")
    except Exception as e:
        print(f"Caught unexpected exception: {type(e)}")

if __name__ == "__main__":
    asyncio.run(test_repro())
