# Controllers package

from fastapi import FastAPI

from src.core.app.controllers.chat_controller import register_chat_routes


def register_routes(app: FastAPI) -> None:
    """Register all routes with the FastAPI application.
    
    Args:
        app: The FastAPI application
    """
    register_chat_routes(app)
