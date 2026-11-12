import hmac
import re
from typing import Annotated

from fastapi import Header, HTTPException, Request, status

from app.core.config import get_settings


def safe_user_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.@-]{1,80}", value):
        raise HTTPException(status_code=400, detail={"code": "invalid_user_id", "message": "Invalid user identifier."})
    return value


async def authenticated_user(
    request: Request,
    x_api_key: Annotated[str | None, Header()] = None,
    x_dev_user_id: Annotated[str | None, Header()] = None,
) -> str:
    settings = request.app.state.settings if hasattr(request.app.state, "settings") else get_settings()
    if settings.app_env.lower() == "production":
        if not settings.app_api_key or not x_api_key or not hmac.compare_digest(settings.app_api_key, x_api_key):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "unauthorized", "message": "Valid API credentials are required."})
        # A single shared API key is only a deployment gate. Replace this with verified
        # per-user identity claims before serving multiple production users.
        return "configured-client"
    if settings.app_api_key:
        if not x_api_key or not hmac.compare_digest(settings.app_api_key, x_api_key):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "unauthorized", "message": "Valid API credentials are required."})
    return safe_user_id(x_dev_user_id or "demo-user")

