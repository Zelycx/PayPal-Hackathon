
import secrets
import hashlib
import uuid

from datetime import datetime, timedelta, timezone


# Temporary session storage
SESSIONS = {}

SESSION_DURATION_HOURS = 12


def create_session(display_name: str):

    session_id = str(uuid.uuid4())

    # Generate a secure random token
    token = secrets.token_urlsafe(32)

    # Store only the token hash
    token_hash = hashlib.sha256(
        token.encode()
    ).hexdigest()

    expires_at = datetime.now(timezone.utc) + timedelta(
        hours=SESSION_DURATION_HOURS
    )

    SESSIONS[token_hash] = {
        "session_id": session_id,
        "display_name": display_name,
        "expires_at": expires_at
    }

    return session_id, token, expires_at


def get_session(token: str):

    token_hash = hashlib.sha256(
        token.encode()
    ).hexdigest()

    session = SESSIONS.get(token_hash)

    if session is None:
        return None

    if datetime.now(timezone.utc) >= session["expires_at"]:
        SESSIONS.pop(token_hash, None)
        return None

    return session


def delete_session(token: str):

    token_hash = hashlib.sha256(
        token.encode()
    ).hexdigest()

    return SESSIONS.pop(token_hash, None) is not None
