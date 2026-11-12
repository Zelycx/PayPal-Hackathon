from fastapi import APIRouter, Request
from sqlalchemy import text

from app.core.config import get_settings
from app.database.database import engine

router = APIRouter(tags=["health"])


def _health(request: Request) -> dict[str, object]:
    settings = request.app.state.settings if hasattr(request.app.state, "settings") else get_settings()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "unavailable"
    return {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "ai_configured": bool(settings.groq_api_key),
        "chat_model": settings.groq_chat_model,
        "vision_model": settings.groq_vision_model,
        "environment": settings.app_env,
    }


@router.get("/health")
async def health(request: Request):
    return _health(request)


@router.get("/api/v1/health")
async def api_health(request: Request):
    return _health(request)
