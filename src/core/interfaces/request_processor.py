from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from fastapi import Request
from starlette.responses import Response


class IRequestProcessor(ABC):
    """Interface for processing chat completion requests.
    
    This interface defines the contract for components that process incoming
    chat completion requests and produce responses, encapsulating the core
    request-response flow logic.
    """
    
    @abstractmethod
    async def process_request(self, request: Request, request_data: Any) -> Response:
        """Process an incoming chat completion request.
        
        Args:
            request: The FastAPI Request object
            request_data: The parsed request data
            
        Returns:
            An appropriate FastAPI Response object
        """
