
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.schemas.session import SessionStartRequest

from app.services.session_service import (
    create_session,
    get_session,
    delete_session
)

router = APIRouter(
    prefix="/session",
    tags=["Guest Sessions"]
)

security = HTTPBearer(auto_error=False)


def require_session(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Session token required"
        )

    session = get_session(credentials.credentials)

    if session is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session"
        )

    return session


@router.post("/start")
def start_session(request: SessionStartRequest):

    display_name = request.display_name.strip()

    if not display_name:
        raise HTTPException(
            status_code=422,
            detail="Display name cannot be empty"
        )

    session_id, token, expires_at = create_session(
        display_name
    )

    return {
        "message": "Guest session created successfully",
        "session_id": session_id,
        "access_token": token,
        "token_type": "bearer",
        "display_name": display_name,
        "expires_at": expires_at
    }


@router.get("/me")
def get_current_session(
    session: dict = Depends(require_session)
):

    return {
        "session_id": session["session_id"],
        "display_name": session["display_name"],
        "expires_at": session["expires_at"]
    }


@router.post("/end")
def end_session(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Session token required"
        )

    deleted = delete_session(credentials.credentials)

    if not deleted:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session"
        )

    return {
        "message": "Guest session ended successfully"
    }
