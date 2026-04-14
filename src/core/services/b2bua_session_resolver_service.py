"""B2BUA session resolver implementation."""

from __future__ import annotations

from src.core.domain.b2bua_identity import B2buaIdentity
from src.core.domain.request_context import RequestContext
from src.core.interfaces.auth_scope_resolver_interface import IAuthScopeResolver
from src.core.interfaces.b2bua_mapping_store_interface import IB2buaMappingStore
from src.core.interfaces.client_session_id_extractor_interface import (
    IClientSessionIdExtractor,
)
from src.core.interfaces.session_resolver_interface import ISessionResolver
from src.core.services.b2bua_session_id_factory import B2BUASessionIdFactory

_ANONYMOUS_AUTH_SCOPE_PREFIX = "__b2bua-anon-auth__"
_ANONYMOUS_CLIENT_SESSION_ID = "__b2bua-anon-client__"


class B2BUASessionResolver(ISessionResolver):
    """Resolve canonical internal A-leg session ids for B2BUA mode."""

    def __init__(
        self,
        *,
        client_session_extractor: IClientSessionIdExtractor,
        auth_scope_resolver: IAuthScopeResolver,
        mapping_store: IB2buaMappingStore,
        session_id_factory: B2BUASessionIdFactory,
    ) -> None:
        self._client_session_extractor = client_session_extractor
        self._auth_scope_resolver = auth_scope_resolver
        self._mapping_store = mapping_store
        self._session_id_factory = session_id_factory

    async def resolve_session_id(self, context: RequestContext) -> str:
        """Resolve or create a canonical internal A-leg session id."""
        if context.b2bua_identity is not None:
            context.session_id = context.b2bua_identity.a_session_id
            return context.b2bua_identity.a_session_id

        client_session_id = self._client_session_extractor.extract_client_session_id(
            context
        )
        auth_scope_id = await self._auth_scope_resolver.resolve_auth_scope_id(context)

        if (
            client_session_id is not None
            and self._session_id_factory.is_canonical_a_session_id(client_session_id)
        ):
            echo_continuity = await self._mapping_store.try_resolve_echoed_a_session_id(
                a_session_id=client_session_id.strip(),
                requesting_auth_scope_id=auth_scope_id,
            )
            if echo_continuity is not None:
                a_session_id = echo_continuity.a_session_id
                context.ensure_processing_context().update(
                    {
                        "b2bua_continuity_reused_existing": echo_continuity.reused_existing,
                        "b2bua_continuity_store_error": echo_continuity.had_store_error,
                    }
                )
                context.session_id = a_session_id
                context.b2bua_identity = B2buaIdentity(
                    a_session_id=a_session_id,
                    client_session_id=client_session_id,
                    auth_scope_id=auth_scope_id,
                )
                return a_session_id

        if client_session_id is not None and auth_scope_id is not None:
            continuity = await self._mapping_store.resolve_or_create_a_session_id(
                auth_scope_id=auth_scope_id,
                client_session_id=client_session_id,
                create_a_session_id=self._session_id_factory.generate_a_session_id,
            )
            a_session_id = continuity.a_session_id
            context.ensure_processing_context().update(
                {
                    "b2bua_continuity_reused_existing": continuity.reused_existing,
                    "b2bua_continuity_store_error": continuity.had_store_error,
                }
            )
        else:
            # Strict isolation default: no client session id or no auth scope -> new A-leg.
            generated_a_session_id = self._session_id_factory.generate_a_session_id()
            continuity = await self._mapping_store.resolve_or_create_a_session_id(
                auth_scope_id=f"{_ANONYMOUS_AUTH_SCOPE_PREFIX}:{generated_a_session_id}",
                client_session_id=_ANONYMOUS_CLIENT_SESSION_ID,
                create_a_session_id=lambda: generated_a_session_id,
            )
            a_session_id = continuity.a_session_id
            context.ensure_processing_context().update(
                {
                    "b2bua_continuity_reused_existing": False,
                    "b2bua_continuity_store_error": continuity.had_store_error,
                }
            )

        context.session_id = a_session_id
        context.b2bua_identity = B2buaIdentity(
            a_session_id=a_session_id,
            client_session_id=client_session_id,
            auth_scope_id=auth_scope_id,
        )
        return a_session_id
