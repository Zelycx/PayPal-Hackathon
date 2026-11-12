
import os
import re
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv

# Load backend/.env
BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")

PAYPAL_BASE_URL = os.getenv(
    "PAYPAL_BASE_URL",
    "https://api-m.sandbox.paypal.com"
).rstrip("/")

if PAYPAL_BASE_URL != "https://api-m.sandbox.paypal.com":
    raise RuntimeError("This integration is restricted to the PayPal Sandbox API.")

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

async def get_paypal_transactions(
    days: int = 30,
    page: int = 1,
    page_size: int = 100,
    start_date: str | None = None,
    end_date: str | None = None,
    transaction_id: str | None = None,
    include_payer_info: bool = False,
    balance_affecting_records_only: bool = True,
):
    if (start_date is None) != (end_date is None):
        raise ValueError("Both start_date and end_date are required for a date range.")
    if start_date is not None and end_date is not None:
        try:
            start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("Transaction dates must use RFC3339 format.") from error
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("Transaction dates must include a timezone.")
        if end <= start:
            raise ValueError("Transaction date range end must be later than start.")
        if end - start > timedelta(days=31):
            raise ValueError("Transaction date range cannot exceed 31 days.")
        start_string = start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_string = end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        if not 1 <= days <= 31:
            raise ValueError("Days must be between 1 and 31.")
        end_date_value = datetime.now(timezone.utc)
        start_date_value = end_date_value - timedelta(days=days)
        start_string = start_date_value.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_string = end_date_value.strftime("%Y-%m-%dT%H:%M:%SZ")

    if transaction_id is not None and not (
        len(transaction_id) in {17, 19} and re.fullmatch(r"[A-Za-z0-9]+", transaction_id)
    ):
        raise ValueError("PayPal transaction IDs must contain 17 or 19 letters or numbers.")

    if page < 1:
        raise ValueError("Page must be at least 1.")

    if not 1 <= page_size <= 500:
        raise ValueError("Page size must be between 1 and 500.")

    token = await get_access_token()

    url = f"{PAYPAL_BASE_URL}/v1/reporting/transactions"

    params = {
        "start_date": start_string,
        "end_date": end_string,
        "fields": "transaction_info",
        "page_size": page_size,
        "page": page,
        "balance_affecting_records_only": "Y" if balance_affecting_records_only else "N",
    }
    if transaction_id:
        params["transaction_id"] = transaction_id
    if include_payer_info:
        params["fields"] = "transaction_info,payer_info"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            params=params,
        )

    if response.status_code == 401:
        raise RuntimeError(
            "PayPal rejected the access token for transaction search."
        )

    if response.status_code == 403:
        raise RuntimeError(
            "PayPal denied transaction search access. "
            "Check the reporting/search/read permission."
        )

    if response.status_code != 200:
        raise RuntimeError(
            f"PayPal transaction request failed "
            f"(HTTP {response.status_code})."
        )

    data = response.json()

    return {
        "transaction_details": data.get("transaction_details", []),
        "total_items": data.get("total_items", 0),
        "total_pages": data.get("total_pages", 0),
        "page": data.get("page", page),
        "start_date": data.get("start_date", start_string),
        "end_date": data.get("end_date", end_string),
        "last_refreshed_datetime": data.get(
            "last_refreshed_datetime"
        ),
    }
