"""API routes — health, chat, schemes (Phase 5)."""

from src.api.routes.chat import router as chat_router
from src.api.routes.health import router as health_router

__all__ = ["chat_router", "health_router"]
