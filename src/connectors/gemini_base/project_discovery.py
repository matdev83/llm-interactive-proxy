"""
Project discovery strategies for Gemini OAuth connectors.

This module provides different project ID discovery implementations:
- FreeTierProjectDiscovery: Free tier onboarding flow
- PaidTierProjectDiscovery: Paid tier onboarding flow (Google One/paid plans)
- AntigravityProjectDiscovery: Antigravity-specific discovery
"""

import asyncio
import logging
from typing import Any

from src.connectors.gemini_base.models import TierScore
from src.core.common.exceptions import BackendError


logger = logging.getLogger(__name__)


class FreeTierProjectDiscovery:
    """Project discovery strategy for free-tier backends.

    Used by gemini-oauth-free backend.
    """

    def __init__(self) -> None:
        """Initialize the free-tier project discovery strategy."""
        self._cached_project_id: str | None = None

    async def discover(
        self,
        auth_session: Any,
        credentials: dict[str, Any] | None,
        base_url: str,
        cached_project_id: str | None = None,
    ) -> str:
        """Discover or retrieve the project ID for Code Assist API (Free Tier).

        This method implements the exact project discovery logic from KiloCode,
        which calls loadCodeAssist and potentially onboardUser endpoints.

        Args:
            auth_session: The authorized session for API calls.
            credentials: OAuth credentials dictionary.
            base_url: The API base URL.
            cached_project_id: Previously discovered project ID, if any.

        Returns:
            The discovered project ID string.
        """
        # Use cached if available
        if cached_project_id:
            return cached_project_id
        if self._cached_project_id:
            return self._cached_project_id

        if not auth_session:
            logger.warning(
                "auth_session required for free-tier project discovery but missing"
            )
            return "default"

        initial_project_id = "default"

        # Prepare client metadata (matching KiloCode exactly)
        client_metadata = {
            "ideType": "IDE_UNSPECIFIED",
            "platform": "PLATFORM_UNSPECIFIED",
            "pluginType": "GEMINI",
            "duetProject": initial_project_id,
        }

        try:
            # Call loadCodeAssist to discover the actual project ID
            load_request = {
                "cloudaicompanionProject": initial_project_id,
                "metadata": client_metadata,
            }

            url = f"{base_url}/v1internal:loadCodeAssist"
            load_response = await asyncio.to_thread(
                auth_session.request,
                method="POST",
                url=url,
                json=load_request,
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )

            if load_response.status_code != 200:
                raise BackendError(f"LoadCodeAssist failed: {load_response.text}")

            load_data = load_response.json()

            # Check if we already have a project ID from the response
            if load_data.get("cloudaicompanionProject"):
                self._cached_project_id = load_data["cloudaicompanionProject"]
                return str(self._cached_project_id)

            # For free-tier, we MUST NOT include the "cloudaicompanionProject" field AT ALL.
            onboard_request = {
                "tierId": "free-tier",
                "metadata": {
                    "ideType": "IDE_UNSPECIFIED",
                    "platform": "PLATFORM_UNSPECIFIED",
                    "pluginType": "GEMINI",
                },
            }

            # Call onboardUser
            onboard_url = f"{base_url}/v1internal:onboardUser"
            lro_response = await asyncio.to_thread(
                auth_session.request,
                method="POST",
                url=onboard_url,
                json=onboard_request,
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )

            if lro_response.status_code != 200:
                raise BackendError(f"OnboardUser failed: {lro_response.text}")

            lro_data = lro_response.json()

            # Poll until operation is complete
            max_retries = 30
            retry_count = 0
            while not lro_data.get("done") and retry_count < max_retries:
                await asyncio.sleep(2)
                lro_response = await asyncio.to_thread(
                    auth_session.request,
                    method="POST",
                    url=onboard_url,
                    json=onboard_request,
                    headers={"Content-Type": "application/json"},
                    timeout=30.0,
                )
                if lro_response.status_code == 200:
                    lro_data = lro_response.json()
                retry_count += 1

            if not lro_data.get("done"):
                raise BackendError("Onboarding timeout - operation did not complete")

            # Extract the discovered project ID
            response_data = lro_data.get("response", {})
            cloudai_project = response_data.get("cloudaicompanionProject", {})
            discovered_project_id = cloudai_project.get("id", initial_project_id)

            self._cached_project_id = discovered_project_id
            logger.info(f"Discovered project ID: {self._cached_project_id}")
            return str(self._cached_project_id)

        except Exception as e:
            logger.error(f"Failed to discover project ID: {e}", exc_info=True)
            # Fall back to default
            self._cached_project_id = initial_project_id
            return str(self._cached_project_id)


class PaidTierProjectDiscovery:
    """Project discovery strategy for paid-tier backends.

    Used by gemini-oauth-plan backend.
    """

    def __init__(self) -> None:
        """Initialize the paid-tier project discovery strategy."""
        self._cached_project_id: str | None = None

    async def discover(
        self,
        auth_session: Any,
        credentials: dict[str, Any] | None,
        base_url: str,
        cached_project_id: str | None = None,
    ) -> str:
        """Discover or retrieve the project ID for the paid plan.

        This implementation follows the exact flow used by the official gemini-cli:
        1. Call loadCodeAssist to determine current tier and project
        2. If no current tier, call onboardUser with paid-tier parameters
        3. Poll the long-running operation until completion

        Args:
            auth_session: The authorized session for API calls.
            credentials: OAuth credentials dictionary.
            base_url: The API base URL.
            cached_project_id: Previously discovered project ID, if any.

        Returns:
            The discovered project ID string.
        """
        # Use cached if available
        if cached_project_id:
            return cached_project_id
        if self._cached_project_id:
            return self._cached_project_id

        # Check for existing project ID in the credentials file
        if credentials and "project_id" in credentials:
            project_id = credentials["project_id"]
            if project_id:
                self._cached_project_id = project_id
                return str(project_id)

        if not auth_session:
            raise BackendError("auth_session required for project discovery")

        # Get initial project ID from credentials if available
        initial_project_id = credentials.get("project_id") if credentials else None

        # Prepare client metadata (matching gemini-cli exactly)
        client_metadata = {
            "ideType": "IDE_UNSPECIFIED",
            "platform": "PLATFORM_UNSPECIFIED",
            "pluginType": "GEMINI",
            "duetProject": initial_project_id,
        }

        load_request = {
            "cloudaicompanionProject": initial_project_id,
            "metadata": client_metadata,
        }

        load_url = f"{base_url}/v1internal:loadCodeAssist"
        load_response = await asyncio.to_thread(
            auth_session.post,
            load_url,
            json=load_request,
            headers={"Content-Type": "application/json"},
            timeout=30.0,
        )

        if load_response.status_code != 200:
            raise BackendError(f"LoadCodeAssist failed: {load_response.text}")

        load_data = load_response.json()

        # Check if we already have a project ID from the response
        if load_data.get("cloudaicompanionProject"):
            self._cached_project_id = load_data["cloudaicompanionProject"]
            return str(self._cached_project_id)

        # Determine which tier to use for onboarding
        tier_to_use = self._select_best_tier(load_data)
        selected_tier_id = tier_to_use.get("id") or "paid-tier"
        logger.info(
            "Selected Code Assist tier '%s' (context_limit=%s)",
            selected_tier_id,
            self._context_tokens(tier_to_use),
        )

        # Perform onboarding with the paid tier
        onboard_request = {
            "tierId": selected_tier_id,
            "cloudaicompanionProject": initial_project_id,
            "metadata": {
                **client_metadata,
                "duetProject": initial_project_id,
            },
        }

        onboard_url = f"{base_url}/v1internal:onboardUser"

        # Poll the long-running operation until completion
        max_retries = 30
        retry_count = 0

        while retry_count < max_retries:
            lro_response = await asyncio.to_thread(
                auth_session.post,
                onboard_url,
                json=onboard_request,
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )

            if lro_response.status_code != 200:
                raise BackendError(f"OnboardUser failed: {lro_response.text}")

            lro_data = lro_response.json()

            if lro_data.get("done"):
                # Operation completed successfully
                response_data = lro_data.get("response", {})
                cloudai_project = response_data.get("cloudaicompanionProject", {})
                discovered_project_id = cloudai_project.get(
                    "id", initial_project_id or "default"
                )

                self._cached_project_id = discovered_project_id
                logger.info(f"Discovered project ID: {self._cached_project_id}")
                return str(self._cached_project_id)

            # Operation not done yet, wait and retry
            await asyncio.sleep(2)
            retry_count += 1

        raise BackendError(
            message="Onboarding timeout - operation did not complete after maximum retries",
            code="onboarding_timeout",
        )

    def _select_best_tier(self, load_data: dict[str, Any]) -> dict[str, Any]:
        """Select the best tier from loadCodeAssist response.

        Args:
            load_data: The loadCodeAssist response data.

        Returns:
            The best tier dictionary to use.
        """
        allowed_tiers_raw = load_data.get("allowedTiers", [])
        allowed_tiers: list[dict[str, Any]] = [
            tier for tier in allowed_tiers_raw if isinstance(tier, dict)
        ]
        current_tier = load_data.get("currentTier")
        if isinstance(current_tier, dict):
            allowed_tiers.append(current_tier)

        if allowed_tiers:
            return max(allowed_tiers, key=self._tier_score)

        return {"id": "paid-tier"}

    @staticmethod
    def _tier_id(tier: dict[str, Any]) -> str:
        """Extract tier ID from tier dictionary."""
        raw_id = tier.get("id") or tier.get("tierId")
        return str(raw_id or "").lower()

    @staticmethod
    def _context_tokens(tier: dict[str, Any]) -> int:
        """Extract context token limit from tier dictionary."""
        for key in (
            "maxContextTokens",
            "contextTokenLimit",
            "contextWindowTokens",
            "tokenLimit",
            "maxContextWindow",
        ):
            value = tier.get(key)
            if isinstance(value, int | float):
                return int(value)
        return 0

    def _tier_score(self, tier: dict[str, Any]) -> TierScore:
        """Calculate a score for tier ranking."""
        tier_id = self._tier_id(tier)
        is_paid = int(tier_id in {"paid-tier", "google-one-tier", "googleone-tier"})
        context_tokens = self._context_tokens(tier)
        if is_paid and context_tokens == 0:
            context_tokens = 1_000_000
        is_default = int(bool(tier.get("isDefault")))
        return TierScore(
            is_paid=is_paid, context_tokens=context_tokens, is_default=is_default
        )



class AntigravityProjectDiscovery:
    """Project discovery strategy for Antigravity sandbox backend.

    Used by antigravity-oauth backend.
    """

    def __init__(self) -> None:
        """Initialize the Antigravity project discovery strategy."""
        self._cached_project_id: str | None = None

    async def discover(
        self,
        auth_session: Any,
        credentials: dict[str, Any] | None,
        base_url: str,
        cached_project_id: str | None = None,
    ) -> str:
        """Discover the project ID using the paid-tier onboarding flow.

        The Antigravity token maps to a real account; prefer the highest tier
        reported by loadCodeAssist instead of the free-tier defaults to avoid
        artificial quota limits.

        Args:
            auth_session: The authorized session for API calls.
            credentials: OAuth credentials dictionary.
            base_url: The API base URL.
            cached_project_id: Previously discovered project ID, if any.

        Returns:
            The discovered project ID string.
        """
        # Use cached if available
        if cached_project_id:
            return cached_project_id
        if self._cached_project_id:
            return self._cached_project_id

        if not auth_session:
            logger.warning(
                "auth_session required for Antigravity project discovery but missing"
            )
            initial = credentials.get("project_id") if credentials else None
            return str(initial or "default")

        initial_project_id = credentials.get("project_id") if credentials else None
        fallback_project_id = initial_project_id or "default"

        client_metadata = {
            "ideType": "IDE_UNSPECIFIED",
            "platform": "PLATFORM_UNSPECIFIED",
            "pluginType": "GEMINI",
            "duetProject": initial_project_id,
        }

        try:
            load_request = {
                "cloudaicompanionProject": initial_project_id,
                "metadata": client_metadata,
            }

            load_url = f"{base_url}/v1internal:loadCodeAssist"
            load_response = await asyncio.to_thread(
                auth_session.request,
                method="POST",
                url=load_url,
                json=load_request,
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )

            if load_response.status_code != 200:
                raise BackendError(f"LoadCodeAssist failed: {load_response.text}")

            load_data = load_response.json()
            project_candidate = load_data.get("cloudaicompanionProject")
            if project_candidate:
                self._cached_project_id = project_candidate
                return str(self._cached_project_id)

            # Select the best tier
            tier_to_use = self._select_best_tier(load_data)
            selected_tier_id = tier_to_use.get("id") or tier_to_use.get("tierId")
            if not selected_tier_id:
                selected_tier_id = "paid-tier"

            logger.info(
                "Selected Code Assist tier '%s' for Antigravity", selected_tier_id
            )

            onboard_request = {
                "tierId": selected_tier_id,
                "cloudaicompanionProject": initial_project_id,
                "metadata": {
                    **client_metadata,
                    "duetProject": initial_project_id,
                },
            }

            onboard_url = f"{base_url}/v1internal:onboardUser"
            max_retries = 30
            retry_count = 0

            while retry_count < max_retries:
                lro_response = await asyncio.to_thread(
                    auth_session.request,
                    method="POST",
                    url=onboard_url,
                    json=onboard_request,
                    headers={"Content-Type": "application/json"},
                    timeout=30.0,
                )

                if lro_response.status_code != 200:
                    raise BackendError(f"OnboardUser failed: {lro_response.text}")

                lro_data = lro_response.json()
                if lro_data.get("done"):
                    response_data = lro_data.get("response", {})
                    cloudai_project = response_data.get("cloudaicompanionProject", {})
                    discovered_project_id = cloudai_project.get(
                        "id", initial_project_id or "default"
                    )
                    self._cached_project_id = discovered_project_id
                    logger.info(
                        "Discovered Antigravity project ID: %s", self._cached_project_id
                    )
                    return str(self._cached_project_id)

                retry_count += 1
                await asyncio.sleep(2)

            logger.warning(
                "Onboarding timed out for Antigravity; falling back to project '%s'",
                fallback_project_id,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning(
                "Antigravity project discovery failed, using fallback project '%s': %s",
                fallback_project_id,
                exc,
                exc_info=True,
            )

        self._cached_project_id = fallback_project_id
        return str(self._cached_project_id)

    def _select_best_tier(self, load_data: dict[str, Any]) -> dict[str, Any]:
        """Select the best tier with Antigravity-specific scoring.

        Args:
            load_data: The loadCodeAssist response data.

        Returns:
            The best tier dictionary to use.
        """
        allowed_tiers_raw = load_data.get("allowedTiers", [])
        allowed_tiers = [tier for tier in allowed_tiers_raw if isinstance(tier, dict)]
        current_tier = load_data.get("currentTier")
        if isinstance(current_tier, dict):
            allowed_tiers.append(current_tier)

        if allowed_tiers:
            return max(allowed_tiers, key=self._tier_score)

        return {"id": "paid-tier"}

    @staticmethod
    def _tier_id(tier: dict[str, Any]) -> str:
        """Extract tier ID from tier dictionary."""
        raw_id = tier.get("id") or tier.get("tierId")
        return str(raw_id or "").lower()

    @staticmethod
    def _context_tokens(tier: dict[str, Any]) -> int:
        """Extract context token limit from tier dictionary."""
        for key in (
            "maxContextTokens",
            "contextTokenLimit",
            "contextWindowTokens",
            "tokenLimit",
            "maxContextWindow",
        ):
            value = tier.get(key)
            if isinstance(value, int | float):
                return int(value)
        return 0

    def _tier_score(self, tier: dict[str, Any]) -> TierScore:
        """Calculate a score for tier ranking (Antigravity-specific).

        Antigravity includes additional tier IDs in its paid tier detection.
        """
        tier_id = self._tier_id(tier)
        is_paid = int(
            tier_id
            in {
                "paid-tier",
                "google-one-tier",
                "googleone-tier",
                "googleone",
                "duet-ai-pro",
            }
        )
        context_tokens = self._context_tokens(tier)
        if is_paid and context_tokens == 0:
            context_tokens = 1_000_000
        is_default = int(bool(tier.get("isDefault")))
        return TierScore(
            is_paid=is_paid, context_tokens=context_tokens, is_default=is_default
        )



# Backward-compatible helper functions
# These are exported for use by other modules that may depend on them


def build_client_metadata(
    project_id: str | None = None,
    ide_type: str = "IDE_UNSPECIFIED",
    platform: str = "PLATFORM_UNSPECIFIED",
    plugin_type: str = "GEMINI",
) -> dict[str, Any]:
    """Build client metadata for Code Assist API calls.

    Args:
        project_id: Optional project ID to include.
        ide_type: IDE type identifier.
        platform: Platform identifier.
        plugin_type: Plugin type identifier.

    Returns:
        Client metadata dictionary.
    """
    return {
        "ideType": ide_type,
        "platform": platform,
        "pluginType": plugin_type,
        "duetProject": project_id,
    }


def calculate_tier_score(tier: dict[str, Any]) -> TierScore:
    """Calculate a score for tier ranking.

    Args:
        tier: Tier dictionary from loadCodeAssist response.

    Returns:
        TierScore object.
    """
    tier_id = (tier.get("id") or tier.get("tierId") or "").lower()
    is_paid = int(
        tier_id
        in {
            "paid-tier",
            "google-one-tier",
            "googleone-tier",
            "googleone",
            "duet-ai-pro",
        }
    )

    context_tokens = 0
    for key in (
        "maxContextTokens",
        "contextTokenLimit",
        "contextWindowTokens",
        "tokenLimit",
        "maxContextWindow",
    ):
        value = tier.get(key)
        if isinstance(value, int | float):
            context_tokens = int(value)
            break

    if is_paid and context_tokens == 0:
        context_tokens = 1_000_000

    is_default = int(bool(tier.get("isDefault")))
    return TierScore(
        is_paid=is_paid, context_tokens=context_tokens, is_default=is_default
    )



def select_best_tier(load_data: dict[str, Any]) -> dict[str, Any]:
    """Select the best tier from loadCodeAssist response.

    Args:
        load_data: The loadCodeAssist response data.

    Returns:
        The best tier dictionary to use.
    """
    allowed_tiers_raw = load_data.get("allowedTiers", [])
    allowed_tiers: list[dict[str, Any]] = [
        tier for tier in allowed_tiers_raw if isinstance(tier, dict)
    ]
    current_tier = load_data.get("currentTier")
    if isinstance(current_tier, dict):
        allowed_tiers.append(current_tier)

    if allowed_tiers:
        return max(allowed_tiers, key=calculate_tier_score)

    return {"id": "paid-tier"}


def extract_project_id_from_response(lro_data: dict[str, Any], fallback: str) -> str:
    """Extract project ID from onboardUser LRO response.

    Args:
        lro_data: Long-running operation response data.
        fallback: Fallback project ID if not found.

    Returns:
        The extracted or fallback project ID.
    """
    response_data = lro_data.get("response", {})
    cloudai_project = response_data.get("cloudaicompanionProject", {})
    return str(cloudai_project.get("id", fallback))


__all__ = [
    # Strategy classes
    "AntigravityProjectDiscovery",
    "FreeTierProjectDiscovery",
    "PaidTierProjectDiscovery",
    # Helper functions (backward compatible)
    "build_client_metadata",
    "calculate_tier_score",
    "extract_project_id_from_response",
    "select_best_tier",
]
