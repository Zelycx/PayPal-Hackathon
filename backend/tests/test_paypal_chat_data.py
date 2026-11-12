from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.services import paypal_service
from app.services.paypal_chat_data import (
    _transaction_summary,
    needs_paypal_data,
    retrieve_paypal_chat_data,
)


def test_detects_balance_transactions_and_followup_domains():
    assert needs_paypal_data("What is my current PayPal balance?", []) == (True, False)
    assert needs_paypal_data("How much did I spend this week?", []) == (False, True)
    assert needs_paypal_data(
        "What about USD?", [{"role": "user", "content": "What is my balance?"}]
    ) == (True, False)


def test_balance_context_uses_fresh_multicurrency_available_total_and_withheld_values(monkeypatch):
    calls = []

    async def balances():
        calls.append("balances")
        return {
            "balances": [
                {
                    "currency_code": "USD",
                    "total_balance": {"currency_code": "USD", "value": "42.10"},
                    "available_balance": {"currency_code": "USD", "value": "40.00"},
                    "withheld_balance": {"currency_code": "USD", "value": "2.10"},
                },
                {
                    "currency_code": "PHP",
                    "total_balance": {"currency_code": "PHP", "value": "500.00"},
                    "available_balance": {"currency_code": "PHP", "value": "500.00"},
                },
            ],
            "as_of_time": "2026-11-13T00:00:00Z",
            "last_refresh_time": "2026-11-13T00:00:00Z",
        }

    monkeypatch.setattr(paypal_service, "get_paypal_balances", balances)
    result = asyncio.run(retrieve_paypal_chat_data("What is my balance?", []))

    assert calls == ["balances"]
    assert result["source"] == "configured PayPal Sandbox application account"
    assert result["balance_status"] == "returned"
    assert result["balances"][0]["available"]["amount"] == "40.00"
    assert result["balances"][0]["withheld"]["amount"] == "2.10"
    assert result["balances"][1]["currency"] == "PHP"
    assert result["pending_balance_available"] is False


def test_affordability_uses_only_explicit_currency_and_available_balance(monkeypatch):
    async def balances():
        return {"balances": [{
            "currency_code": "PHP",
            "total_balance": {"currency_code": "PHP", "value": "2500.00"},
            "available_balance": {"currency_code": "PHP", "value": "1800.00"},
            "withheld_balance": {"currency_code": "PHP", "value": "700.00"},
        }]}

    monkeypatch.setattr(paypal_service, "get_paypal_balances", balances)
    result = asyncio.run(retrieve_paypal_chat_data("Can I afford a ₱2,000 purchase?", []))

    assert result["affordability_evaluation"] == {
        "amount": "2000",
        "currency": "PHP",
        "available_balance": "1800.00",
        "status": "over_available_balance",
        "remaining_after_purchase": "-200",
    }


def test_ambiguous_currency_symbol_does_not_assume_usd(monkeypatch):
    async def balances():
        return {"balances": [{
            "currency_code": "USD",
            "available_balance": {"currency_code": "USD", "value": "100.00"},
        }]}

    monkeypatch.setattr(paypal_service, "get_paypal_balances", balances)
    result = asyncio.run(retrieve_paypal_chat_data("Can I afford a $20 purchase?", []))
    assert result["affordability_evaluation"]["status"] == "currency_required"


def test_transaction_context_fetches_all_pages_and_marks_partial_when_capped(monkeypatch):
    calls = []

    async def transactions(**kwargs):
        calls.append(kwargs)
        page = kwargs["page"]
        return {
            "page": page,
            "total_pages": 2,
            "total_items": 101,
            "transaction_details": [{
                "transaction_info": {
                    "transaction_id": f"ID{page:016d}",
                    "paypal_reference_id": "ORDER123",
                    "paypal_reference_id_type": "ODR",
                    "transaction_event_code": "T0006",
                    "transaction_type": "Payment",
                    "transaction_status": "S",
                    "transaction_initiation_date": "2026-11-12T12:00:00Z",
                    "transaction_amount": {"currency_code": "USD", "value": "-12.00"},
                    "fee_amount": {"currency_code": "USD", "value": "-0.50"},
                    "transaction_subject": "Coffee",
                },
            }],
        }

    monkeypatch.setattr(paypal_service, "get_paypal_transactions", transactions)
    result = asyncio.run(retrieve_paypal_chat_data(
        "Show transactions this week",
        [],
        now=datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc),
    ))

    assert [call["page"] for call in calls] == [1, 2]
    assert calls[0]["start_date"] == "2026-11-09T00:00:00Z"
    assert calls[0]["end_date"] == "2026-11-13T12:00:00Z"
    assert result["transaction_window"]["records_returned"] == 2
    assert result["transaction_window"]["coverage_complete"] is True
    assert result["transactions"][0]["amount"] == {"currency": "USD", "amount": "-12.00"}
    assert result["transactions"][0]["fee"] == {"currency": "USD", "amount": "-0.50"}


def test_transaction_context_fetches_up_to_ten_pages_and_marks_remaining_pages_partial(monkeypatch):
    pages = []

    async def transactions(**kwargs):
        pages.append(kwargs["page"])
        return {
            "page": kwargs["page"],
            "total_pages": 12,
            "total_items": 1200,
            "transaction_details": [],
        }

    monkeypatch.setattr(paypal_service, "get_paypal_transactions", transactions)
    result = asyncio.run(retrieve_paypal_chat_data("Show transaction history", []))

    assert pages == list(range(1, 11))
    assert result["transaction_window"]["coverage_complete"] is False
    assert result["transaction_window"]["total_pages_reported"] == 12
    assert result["transaction_summary"]["coverage_complete"] is False


def test_explicit_date_ranges_longer_than_paypal_limit_are_rejected():
    try:
        asyncio.run(retrieve_paypal_chat_data(
            "Show transactions from 2026-01-01 to 2026-02-10", []
        ))
    except ValueError as error:
        assert "up to 31 days" in str(error)
    else:
        raise AssertionError("Expected a date-range error")


def test_transaction_summary_uses_known_event_and_type_and_keeps_currencies_separate():
    result = _transaction_summary([
        {"event_code": "T0006", "type": "Express Checkout Payment", "status": "S",
         "amount": {"currency": "USD", "amount": "-12.00"}, "fee": {"currency": "USD", "amount": "-0.50"}},
        {"event_code": "T0006", "type": "Express Checkout Payment", "status": "S",
         "amount": {"currency": "EUR", "amount": "-20.00"}},
        {"event_code": "T0006", "type": "Express Checkout Payment", "status": "P",
         "amount": {"currency": "USD", "amount": "-30.00"}},
        {"event_code": "T1900", "type": "General account correction", "status": "S",
         "amount": {"currency": "USD", "amount": "-999.00"}},
    ], coverage_complete=True)

    assert result["completed_outflows"] == [
        {"currency": "EUR", "amount": "20"},
        {"currency": "USD", "amount": "12"},
    ]
    assert result["pending_transaction_amounts"] == [{"currency": "USD", "amount": "30"}]
    assert result["reported_fees"] == [{"currency": "USD", "amount": "0.5"}]
    assert result["unclassified_or_nonterminal_records"] == 1
