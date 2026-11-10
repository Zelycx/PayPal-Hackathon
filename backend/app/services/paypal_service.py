
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Load backend/.env
BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")

PAYPAL_BASE_URL = os.getenv(
    "PAYPAL_BASE_URL",
    "https://api-m.sandbox.paypal.com"
)

PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET")

# Cache the application access token until shortly before expiry.
_cached_token = None
_token_expires_at = 0


async def get_access_token():
    global _cached_token, _token_expires_at

    if not PAYPAL_CLIENT_ID or not PAYPAL_CLIENT_SECRET:
        raise RuntimeError("PayPal credentials are not configured.")

    if _cached_token and time.monotonic() < _token_expires_at:
        return _cached_token

    url = f"{PAYPAL_BASE_URL}/v1/oauth2/token"

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            url,
            auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET),
            headers={
                "Accept": "application/json",
                "Accept-Language": "en_US",
            },
            data={
                "grant_type": "client_credentials"
            },
        )

    if response.status_code != 200:
        raise RuntimeError(
            f"PayPal authentication failed "
            f"(HTTP {response.status_code}). "
            "Check your Sandbox credentials."
        )

    data = response.json()

    access_token = data.get("access_token")
    expires_in = int(data.get("expires_in", 0))

    if not access_token:
        raise RuntimeError("PayPal did not return an access token.")

    _cached_token = access_token
    _token_expires_at = time.monotonic() + max(expires_in - 60, 0)

    return access_token


async def test_paypal_connection():
    token = await get_access_token()

    return {
        "connected": True,
        "environment": "sandbox",
        "message": "PayPal OAuth authentication successful."
    }



async def get_paypal_balances():
    token = await get_access_token()

    url = f"{PAYPAL_BASE_URL}/v1/reporting/balances"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )

    if response.status_code == 403:
        raise RuntimeError(
            "PayPal denied balance access. "
            "The application may not have the required "
            "reporting/balances/read permission."
        )

    if response.status_code != 200:
        raise RuntimeError(
            f"PayPal balance request failed "
            f"(HTTP {response.status_code})."
        )

    data = response.json()

    return {
        "balances": data.get("balances", []),
        "account_id": data.get("account_id"),
        "as_of_time": data.get("as_of_time"),
        "last_refresh_time": data.get("last_refresh_time"),
    }
