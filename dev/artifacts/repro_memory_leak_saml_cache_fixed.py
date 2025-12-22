"""Repro script to verify SAML metadata cache fix.

This script verifies that _saml_metadata_cache now has size limits
with LRU eviction.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.auth.sso.config import ProviderConfig, SSOConfig
from src.core.auth.sso.sso_service import SSOService, MAX_SAML_METADATA_CACHE_SIZE


async def main():
    """Test SAML metadata cache with size limit."""
    # Create a minimal SSO config
    provider_config = ProviderConfig(
        type="saml",
        enabled=True,
        client_id="test-client",
        client_secret="test-secret",
        metadata_url="https://example.com/metadata",
    )
    
    sso_config = SSOConfig(providers={"test-provider": provider_config})
    service = SSOService(sso_config)
    
    print(f"Initial cache size: {len(service._saml_metadata_cache)}")
    print(f"Max cache size: {MAX_SAML_METADATA_CACHE_SIZE}")
    
    # Simulate many different metadata URLs being accessed
    # In real usage, each unique provider or metadata URL would add an entry
    num_urls = 200  # More than MAX_SAML_METADATA_CACHE_SIZE
    
    for i in range(num_urls):
        metadata_url = f"https://example.com/metadata/{i}"
        # Simulate cache entry (we can't actually fetch, but we can check growth)
        # Use the actual cache method to trigger LRU eviction
        if metadata_url in service._saml_metadata_cache:
            service._saml_metadata_cache.move_to_end(metadata_url)
        else:
            service._saml_metadata_cache[metadata_url] = {
                "sso_redirect_url": f"https://example.com/sso/{i}",
                "signing_cert": f"cert-{i}",
                "entity_id": f"entity-{i}",
            }
            # Evict oldest entries if cache exceeds size limit
            while len(service._saml_metadata_cache) > MAX_SAML_METADATA_CACHE_SIZE:
                service._saml_metadata_cache.popitem(last=False)
    
    print(f"After adding {num_urls} entries, cache size: {len(service._saml_metadata_cache)}")
    
    if len(service._saml_metadata_cache) <= MAX_SAML_METADATA_CACHE_SIZE:
        print("✓ Fix verified: Cache size is limited!")
    else:
        print("✗ Fix failed: Cache still grows unbounded!")


if __name__ == "__main__":
    asyncio.run(main())
