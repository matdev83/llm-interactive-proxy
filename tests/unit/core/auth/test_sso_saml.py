"""
Unit tests for SAML support in SSOService.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx
from src.core.auth.sso.config import ProviderConfig, SSOConfig
from src.core.auth.sso.exceptions import AuthenticationError
from src.core.auth.sso.models import SAMLMetadata
from src.core.auth.sso.sso_service import SSOService



def _build_saml_response_xml(
    audience: str, name_id: str, email: str, signing_cert: str | None = None
) -> str:
    issue_instant = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    signature_block = ""
    if signing_cert:
        signature_block = f"""
    <ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
      <ds:KeyInfo>
        <ds:X509Data>
          <ds:X509Certificate>{signing_cert}</ds:X509Certificate>
        </ds:X509Data>
      </ds:KeyInfo>
    </ds:Signature>
"""
    return f"""
<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="_resp1" Version="2.0" IssueInstant="{issue_instant}">
    <saml:Issuer>https://idp.example.com/metadata</saml:Issuer>
    <samlp:Status>
        <samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success" />
    </samlp:Status>
    {signature_block}
    <saml:Assertion ID="_assert1" Version="2.0" IssueInstant="{issue_instant}">
        <saml:Issuer>https://idp.example.com/metadata</saml:Issuer>
        <saml:Subject>
            <saml:NameID>{name_id}</saml:NameID>
        </saml:Subject>
        <saml:Conditions NotOnOrAfter="{expiry}">
            <saml:AudienceRestriction>
                <saml:Audience>{audience}</saml:Audience>
            </saml:AudienceRestriction>
        </saml:Conditions>
        <saml:AttributeStatement>
            <saml:Attribute Name="email">
                <saml:AttributeValue>{email}</saml:AttributeValue>
            </saml:Attribute>
        </saml:AttributeStatement>
    </saml:Assertion>
</samlp:Response>
""".strip()


@pytest.mark.asyncio
async def test_create_saml_authorization_url_uses_metadata():
    metadata_xml = """
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="https://idp.example.com/metadata">
  <md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" Location="https://idp.example.com/sso"/>
    <md:KeyDescriptor use="signing">
      <ds:KeyInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
        <ds:X509Data>
          <ds:X509Certificate>ABC123</ds:X509Certificate>
        </ds:X509Data>
      </ds:KeyInfo>
    </md:KeyDescriptor>
  </md:IDPSSODescriptor>
</md:EntityDescriptor>
""".strip()

    config = SSOConfig(
        enabled=True,
        providers={
            "saml-idp": ProviderConfig(
                type="saml",
                client_id="my-client-id",
                client_secret="secret",
                metadata_url="https://idp.example.com/metadata",
            )
        },
    )
    service = SSOService(config)

    with respx.mock:
        respx.get("https://idp.example.com/metadata").mock(
            return_value=httpx.Response(200, text=metadata_xml)
        )
        url = await service.create_authorization_url(
            "saml-idp", state="relay123", redirect_uri="http://localhost/auth/callback"
        )

    assert "SAMLRequest=" in url
    assert "RelayState=relay123" in url
    assert url.startswith("https://idp.example.com/sso?")


@pytest.mark.asyncio
async def test_handle_saml_callback_parses_assertion_success():
    config = SSOConfig(
        enabled=True,
        providers={
            "saml-idp": ProviderConfig(
                type="saml",
                client_id="my-client-id",
                client_secret="secret",
                metadata_url="https://idp.example.com/metadata",
            )
        },
    )
    service = SSOService(config)

    signing_cert = "ABC123"
    service._saml_metadata_cache["https://idp.example.com/metadata"] = SAMLMetadata(
        sso_redirect_url="https://idp.example.com/sso",
        signing_cert=signing_cert,
        entity_id="https://idp.example.com/metadata",
    )


    response_xml = _build_saml_response_xml(
        audience="my-client-id",
        name_id="user-123",
        email="user@example.com",
        signing_cert=signing_cert,
    )
    saml_response = base64.b64encode(response_xml.encode("utf-8")).decode("ascii")

    result = await service.handle_callback(
        provider="saml-idp",
        code=None,
        state="relay123",
        redirect_uri="http://localhost/auth/callback",
        saml_response=saml_response,
    )

    assert result.success is True
    assert result.user_id == "user-123"
    assert result.user_email == "user@example.com"
    assert result.provider == "saml-idp"


@pytest.mark.asyncio
async def test_handle_saml_callback_rejects_audience_mismatch():
    config = SSOConfig(
        enabled=True,
        providers={
            "saml-idp": ProviderConfig(
                type="saml",
                client_id="expected-audience",
                client_secret="secret",
                metadata_url="https://idp.example.com/metadata",
            )
        },
    )
    service = SSOService(config)

    service._saml_metadata_cache["https://idp.example.com/metadata"] = SAMLMetadata(
        sso_redirect_url="https://idp.example.com/sso",
        signing_cert="ABC123",
        entity_id="https://idp.example.com/metadata",
    )


    bad_response = _build_saml_response_xml(
        audience="other-audience",
        name_id="user-123",
        email="user@example.com",
        signing_cert="ABC123",
    )
    saml_response = base64.b64encode(bad_response.encode("utf-8")).decode("ascii")

    with pytest.raises(AuthenticationError):
        await service.handle_callback(
            provider="saml-idp",
            code=None,
            state="relay123",
            redirect_uri="http://localhost/auth/callback",
            saml_response=saml_response,
        )


@pytest.mark.asyncio
async def test_handle_saml_callback_rejects_cert_mismatch():
    config = SSOConfig(
        enabled=True,
        providers={
            "saml-idp": ProviderConfig(
                type="saml",
                client_id="my-client-id",
                client_secret="secret",
                metadata_url="https://idp.example.com/metadata",
            )
        },
    )
    service = SSOService(config)

    # Preload metadata with expected cert
    service._saml_metadata_cache["https://idp.example.com/metadata"] = SAMLMetadata(
        sso_redirect_url="https://idp.example.com/sso",
        signing_cert="ABC123",
        entity_id="https://idp.example.com/metadata",
    )


    response_xml = _build_saml_response_xml(
        audience="my-client-id",
        name_id="user-123",
        email="user@example.com",
        signing_cert="DIFFERENT",
    )
    saml_response = base64.b64encode(response_xml.encode("utf-8")).decode("ascii")

    with pytest.raises(AuthenticationError):
        await service.handle_callback(
            provider="saml-idp",
            code=None,
            state="relay123",
            redirect_uri="http://localhost/auth/callback",
            saml_response=saml_response,
        )
