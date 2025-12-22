"""Regression test for SAML metadata cache memory leak fix.

This test verifies that the SAML metadata cache uses LRU eviction
and doesn't grow unbounded when many different metadata URLs are accessed.
"""

import pytest
import respx
import httpx

from src.core.auth.sso.config import ProviderConfig, SSOConfig
from src.core.auth.sso.sso_service import SSOService, MAX_SAML_METADATA_CACHE_SIZE


def _create_saml_metadata_xml(entity_id: str, sso_url: str, cert: str = "ABC123") -> str:
    """Create a SAML metadata XML for testing."""
    return f"""
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="{entity_id}">
  <md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" Location="{sso_url}"/>
    <md:KeyDescriptor use="signing">
      <ds:KeyInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
        <ds:X509Data>
          <ds:X509Certificate>{cert}</ds:X509Certificate>
        </ds:X509Data>
      </ds:KeyInfo>
    </md:KeyDescriptor>
  </md:IDPSSODescriptor>
</md:EntityDescriptor>
""".strip()


class TestSAMLMetadataCacheMemoryLeakRegression:
    """Regression tests for SAML metadata cache memory leak fix."""

    @pytest.mark.asyncio
    async def test_cache_bounded_growth(self) -> None:
        """Test that cache doesn't grow unbounded with many unique metadata URLs."""
        provider_config = ProviderConfig(
            type="saml",
            enabled=True,
            client_id="test-client",
            client_secret="test-secret",
            metadata_url="https://example.com/metadata",
        )
        sso_config = SSOConfig(providers={"test-provider": provider_config})
        service = SSOService(sso_config)

        # Verify initial cache is empty
        assert len(service._saml_metadata_cache) == 0

        # Create many different metadata URLs (more than MAX_SAML_METADATA_CACHE_SIZE)
        num_urls = MAX_SAML_METADATA_CACHE_SIZE + 50  # 150 URLs > 100 limit

        with respx.mock:
            # Mock HTTP responses for all metadata URLs
            for i in range(num_urls):
                metadata_url = f"https://example.com/metadata/{i}"
                entity_id = f"https://idp{i}.example.com/metadata"
                sso_url = f"https://idp{i}.example.com/sso"
                metadata_xml = _create_saml_metadata_xml(entity_id, sso_url, f"cert-{i}")

                respx.get(metadata_url).mock(return_value=httpx.Response(200, text=metadata_xml))

            # Load metadata for all URLs
            for i in range(num_urls):
                metadata_url = f"https://example.com/metadata/{i}"
                await service._load_saml_metadata(metadata_url)

            # Cache should not exceed MAX_SAML_METADATA_CACHE_SIZE
            cache_size = len(service._saml_metadata_cache)
            assert cache_size <= MAX_SAML_METADATA_CACHE_SIZE, (
                f"Cache size ({cache_size}) exceeded max size ({MAX_SAML_METADATA_CACHE_SIZE}). "
                "LRU eviction is not working properly."
            )

    @pytest.mark.asyncio
    async def test_cache_lru_eviction(self) -> None:
        """Test that LRU eviction works correctly."""
        provider_config = ProviderConfig(
            type="saml",
            enabled=True,
            client_id="test-client",
            client_secret="test-secret",
            metadata_url="https://example.com/metadata",
        )
        sso_config = SSOConfig(providers={"test-provider": provider_config})
        service = SSOService(sso_config)

        # Fill cache to capacity
        num_urls = MAX_SAML_METADATA_CACHE_SIZE

        with respx.mock:
            # Mock HTTP responses
            for i in range(num_urls + 20):  # More than cache size
                metadata_url = f"https://example.com/metadata/{i}"
                entity_id = f"https://idp{i}.example.com/metadata"
                sso_url = f"https://idp{i}.example.com/sso"
                metadata_xml = _create_saml_metadata_xml(entity_id, sso_url, f"cert-{i}")

                respx.get(metadata_url).mock(return_value=httpx.Response(200, text=metadata_xml))

            # Load metadata to fill cache
            for i in range(num_urls):
                metadata_url = f"https://example.com/metadata/{i}"
                await service._load_saml_metadata(metadata_url)

            # Cache should be at max size
            assert len(service._saml_metadata_cache) == MAX_SAML_METADATA_CACHE_SIZE

            # Access first entry to move it to end (LRU)
            first_url = f"https://example.com/metadata/0"
            await service._load_saml_metadata(first_url)

            # Add more entries - should evict oldest ones (not the recently accessed first_url)
            for i in range(num_urls, num_urls + 10):
                metadata_url = f"https://example.com/metadata/{i}"
                await service._load_saml_metadata(metadata_url)

            # Cache should still be bounded
            assert len(service._saml_metadata_cache) <= MAX_SAML_METADATA_CACHE_SIZE, (
                "Cache exceeded max size after LRU operations."
            )

            # First URL should still be in cache (was accessed recently)
            assert first_url in service._saml_metadata_cache, (
                "Recently accessed URL was evicted incorrectly."
            )

    @pytest.mark.asyncio
    async def test_cache_reuses_existing_entries(self) -> None:
        """Test that accessing same URL multiple times doesn't grow cache."""
        provider_config = ProviderConfig(
            type="saml",
            enabled=True,
            client_id="test-client",
            client_secret="test-secret",
            metadata_url="https://example.com/metadata",
        )
        sso_config = SSOConfig(providers={"test-provider": provider_config})
        service = SSOService(sso_config)

        metadata_url = "https://example.com/metadata/test"
        metadata_xml = _create_saml_metadata_xml(
            "https://idp.example.com/metadata",
            "https://idp.example.com/sso",
            "test-cert",
        )

        with respx.mock:
            respx.get(metadata_url).mock(return_value=httpx.Response(200, text=metadata_xml))

            # Access same URL multiple times
            for _ in range(100):
                await service._load_saml_metadata(metadata_url)

            # Cache should only have one entry
            assert len(service._saml_metadata_cache) == 1, (
                "Cache grew when accessing same URL multiple times."
            )
            assert metadata_url in service._saml_metadata_cache, (
                "Cached URL should still be in cache."
            )

    def test_max_cache_size_constant_defined(self) -> None:
        """Test that MAX_SAML_METADATA_CACHE_SIZE constant is defined correctly."""
        # Verify constant exists and has reasonable value
        assert MAX_SAML_METADATA_CACHE_SIZE == 100, (
            f"MAX_SAML_METADATA_CACHE_SIZE ({MAX_SAML_METADATA_CACHE_SIZE}) should be 100"
        )
        assert MAX_SAML_METADATA_CACHE_SIZE > 0, "MAX_SAML_METADATA_CACHE_SIZE should be positive"
