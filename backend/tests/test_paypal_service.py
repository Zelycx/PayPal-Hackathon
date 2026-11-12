from __future__ import annotations

import asyncio

import pytest

from app.services import paypal_service


class FakeResponse:
    status_code = 200

    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def fake_client(monkeypatch, response_data, captured):
    class FakeClient:
        def __init__(self, **kwargs):
            captured["timeout"] = kwargs["timeout"]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            captured.update(url=url, **kwargs)
            return FakeResponse(response_data)

    monkeypatch.setattr(paypal_service.httpx, "AsyncClient", FakeClient)
    async def token():
        return "test-access-token"
    monkeypatch.setattr(paypal_service, "get_access_token", token)


def test_balance_service_calls_paypal_reporting_and_preserves_currency_fields(monkeypatch):
    captured = {}
    fake_client(monkeypatch, {
        "account_id": "account",
        "as_of_time": "2026-11-13T01:00:00Z",
        "last_refresh_time": "2026-11-13T01:00:00Z",
        "balances": [{
            "currency": "USD",
            "total_balance": {"currency_code": "USD", "value": "42.10"},
            "available_balance": {"currency_code": "USD", "value": "40.00"},
            "withheld_balance": {"currency_code": "USD", "value": "2.10"},
        }],
    }, captured)

    result = asyncio.run(paypal_service.get_paypal_balances())

    assert captured["url"].endswith("/v1/reporting/balances")
    assert captured["headers"]["Authorization"] == "Bearer test-access-token"
    assert result["balances"][0]["available_balance"]["value"] == "40.00"
    assert result["balances"][0]["withheld_balance"]["value"] == "2.10"
    assert result["as_of_time"] == "2026-11-13T01:00:00Z"


def test_transaction_service_supports_date_window_id_and_payer_fields(monkeypatch):
    captured = {}
    fake_client(monkeypatch, {
        "page": 1,
        "total_pages": 1,
        "total_items": 1,
        "transaction_details": [{"transaction_info": {"transaction_id": "A" * 17}}],
    }, captured)

    result = asyncio.run(paypal_service.get_paypal_transactions(
        start_date="2026-11-06T00:00:00Z",
        end_date="2026-11-13T00:00:00Z",
        page=1,
        page_size=100,
        transaction_id="A" * 17,
        include_payer_info=True,
    ))

    assert captured["url"].endswith("/v1/reporting/transactions")
    assert captured["params"]["start_date"] == "2026-11-06T00:00:00Z"
    assert captured["params"]["end_date"] == "2026-11-13T00:00:00Z"
    assert captured["params"]["transaction_id"] == "A" * 17
    assert captured["params"]["fields"] == "transaction_info,payer_info"
    assert captured["params"]["balance_affecting_records_only"] == "Y"
    assert result["transaction_details"][0]["transaction_info"]["transaction_id"] == "A" * 17


@pytest.mark.parametrize("start,end", [
    ("2026-01-01T00:00:00Z", "2026-02-02T00:00:00Z"),
    ("2026-01-02T00:00:00", "2026-01-03T00:00:00Z"),
    ("2026-01-03T00:00:00Z", "2026-01-02T00:00:00Z"),
])
def test_transaction_service_rejects_invalid_date_ranges_before_network(start, end):
    with pytest.raises(ValueError):
        asyncio.run(paypal_service.get_paypal_transactions(start_date=start, end_date=end))
