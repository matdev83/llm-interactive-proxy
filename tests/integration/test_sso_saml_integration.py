"""
Integration test for SAML flow through the FastAPI SSO router.
"""

from __future__ import annotations

import base64
import socket
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastapi import FastAPI
from src.core.auth.sso.authorization_service import (
    AuthorizationConfig,
    AuthorizationService,
)
from src.core.auth.sso.captcha_service import CaptchaService
from src.core.auth.sso.config import ProviderConfig, SSOConfig
from src.core.auth.sso.database import DatabaseManager, TokenRepository
from src.core.auth.sso.rate_limit_service import RateLimitService
from src.core.auth.sso.sso_service import SSOService
from src.core.auth.sso.token_service import TokenService
from src.core.auth.sso.web_interface import create_sso_router


def _saml_response_xml(
    audience: str, name_id: str, email: str, signing_cert: str
) -> str:
    return f"""
<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="_resp1" Version="2.0" IssueInstant="2020-01-01T00:00:00Z">
    <saml:Issuer>https://idp.example.com/metadata</saml:Issuer>
    <samlp:Status>
        <samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success" />
    </samlp:Status>
    <ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
      <ds:KeyInfo>
        <ds:X509Data>
          <ds:X509Certificate>{signing_cert}</ds:X509Certificate>
        </ds:X509Data>
      </ds:KeyInfo>
    </ds:Signature>
    <saml:Assertion ID="_assert1" Version="2.0" IssueInstant="2020-01-01T00:00:00Z">
        <saml:Issuer>https://idp.example.com/metadata</saml:Issuer>
        <saml:Subject>
            <saml:NameID>{name_id}</saml:NameID>
        </saml:Subject>
        <saml:Conditions NotOnOrAfter="2099-01-01T00:00:00Z">
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
async def test_saml_flow_redirects_to_confirm(tmp_path):
    signing_cert = "ABC123"
    metadata_xml = f"""
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="https://idp.example.com/metadata">
  <md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" Location="https://idp.example.com/sso"/>
    <md:KeyDescriptor use="signing">
      <ds:KeyInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
        <ds:X509Data>
          <ds:X509Certificate>{signing_cert}</ds:X509Certificate>
        </ds:X509Data>
      </ds:KeyInfo>
    </md:KeyDescriptor>
  </md:IDPSSODescriptor>
</md:EntityDescriptor>
""".strip()

    db_path = tmp_path / "sso.db"
    sso_config = SSOConfig(
        enabled=True,
        session_lifetime_hours=24,
        database_path=str(db_path),
        authorization=AuthorizationConfig(mode="single_user"),
        providers={
            "saml-idp": ProviderConfig(
                type="saml",
                client_id="my-client-id",
                client_secret="secret",
                metadata_url="https://idp.example.com/metadata",
            )
        },
    )

    database_manager = DatabaseManager(str(db_path))
    await database_manager.initialize_schema()

    token_service = TokenService(memory_cost=8192, time_cost=1, parallelism=1)
    sso_service = SSOService(sso_config)
    rate_limit_service = RateLimitService(database_manager)
    authorization_service = AuthorizationService(
        mode="single_user",
        config=sso_config.authorization,
        database_manager=database_manager,
        rate_limit_service=rate_limit_service,
    )
    captcha_service = CaptchaService(sso_config.captcha)
    router = create_sso_router(
        sso_config=sso_config,
        sso_service=sso_service,
        token_service=token_service,
        authorization_service=authorization_service,
        database_manager=database_manager,
        rate_limit_service=rate_limit_service,
        base_url="http://testserver",
        captcha_service=captcha_service,
    )

    app = FastAPI()
    app.include_router(router)

    token_repo = TokenRepository(str(db_path))
    login_token = await token_repo.create_login_token()

    fake_addr = (
        socket.AF_INET,
        socket.SOCK_STREAM,
        0,
        "",
        ("203.0.113.1", 443),
    )
    with patch("socket.getaddrinfo", return_value=[fake_addr]):
        async with respx.mock:
            respx.get("https://idp.example.com/metadata").mock(
                return_value=httpx.Response(200, text=metadata_xml)
            )
            async with httpx.AsyncClient(app=app, base_url="http://testserver") as client:
                login_resp = await client.get(
                    f"/auth/login?token={login_token}", follow_redirects=False
                )
                assert login_resp.status_code == 302
                auth_url = login_resp.headers["Location"]
                parsed = urlparse(auth_url)
                query = parse_qs(parsed.query)
                relay_state = query["RelayState"][0]

                saml_xml = _saml_response_xml(
                    audience="my-client-id",
                    name_id="user-123",
                    email="user@example.com",
                    signing_cert=signing_cert,
                )
                saml_response = base64.b64encode(saml_xml.encode("utf-8")).decode(
                    "ascii"
                )

                callback_resp = await client.post(
                    "/auth/callback",
                    data={"SAMLResponse": saml_response, "RelayState": relay_state},
                    follow_redirects=False,
                )

                assert callback_resp.status_code == 302
                assert "/auth/confirm" in callback_resp.headers["Location"]
