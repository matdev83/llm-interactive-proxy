"""Traffic leg enumeration for usage tracking.

This module defines the TrafficLeg enum which represents the four directional
segments of traffic flow through the proxy system.
"""

from enum import Enum


class TrafficLeg(str, Enum):
    """Directional segment of traffic flow through the proxy.

    The proxy tracks traffic at four measurement points to provide full
    observability of both verbatim (original) and mutated (modified) traffic:

    - CLIENT_TO_PROXY (CTP): Request received from client (verbatim ingress)
    - PROXY_TO_BACKEND (PTB): Request sent to backend (mutated egress)
    - BACKEND_TO_PROXY (BTP): Response received from backend (verbatim ingress)
    - PROXY_TO_CLIENT (PTC): Response sent to client (mutated egress)
    """

    CLIENT_TO_PROXY = "CTP"
    PROXY_TO_BACKEND = "PTB"
    BACKEND_TO_PROXY = "BTP"
    PROXY_TO_CLIENT = "PTC"
