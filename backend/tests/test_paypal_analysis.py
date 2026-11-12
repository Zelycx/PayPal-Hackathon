from __future__ import annotations

import asyncio
import inspect

import pytest
from fastapi import HTTPException, params

from app.api.paypal import analyze_paypal_transactions
from app.api.session import require_session
from app.schemas.paypal_analysis import PayPalAnalysisContent
from app.services import paypal_analysis_service as analysis_service
from app.services import paypal_service
from app.services.shopping_service import ShoppingSettings


def analysis_content() -> PayPalAnalysisContent:
    return PayPalAnalysisContent.model_validate({
        "spending_insights": [{
            "currency": "USD",
            "observation": "The transaction description indicates a purchase.",
            "transaction_numbers": [1],
        }],
        "income_insights": [],
        "transaction_observations": [
            {
                "transaction_number": 1,
                "currency": "USD",
                "classification": "spending",
                "event_code_evidence": "T0006",
                "description_evidence": "Cafe purchase",
                "observation": "The event code and description indicate a purchase.",
            },
            {
                "transaction_number": 2,
                "currency": "EUR",
                "classification": "opening_balance",
                "event_code_evidence": "T0000",
                "description_evidence": "Opening balance",
                "observation": "The source description identifies an opening balance.",
            },
        ],
        "recommendations": ["Review purchase entries if they are unfamiliar."],
    })


def test_analysis_uses_existing_paypal_services_and_sends_minimized_payload(monkeypatch):
    calls = []
    balance_data = {
        "account_id": "must-not-be-sent",
        "balances": [{
            "currency_code": "USD",
            "total_balance": {"currency_code": "USD", "value": "42.10"},
        }],
    }
    transaction_data = {
        "total_items": 2,
        "total_pages": 1,
        "page": 1,
        "transaction_details": [
            {"transaction_info": {
                "transaction_id": "must-not-be-sent",
                "transaction_event_code": "T0006",
                "transaction_type": "Payment",
                "transaction_status": "S",
                "transaction_amount": {"currency_code": "USD", "value": "-12.00"},
                "transaction_subject": "Cafe purchase",
            }},
            {"transaction_info": {
                "transaction_event_code": "T0000",
                "transaction_type": "Opening balance",
                "transaction_amount": {"currency_code": "EUR", "value": "20.00"},
                "transaction_subject": "Opening balance",
            }},
        ],
    }

    async def balances():
        calls.append("balances")
        return balance_data

    async def transactions(**kwargs):
        calls.append(("transactions", kwargs))
        return transaction_data

    async def groq(payload, settings):
        calls.append(("groq", payload, settings.vision_model))
        return analysis_content()

    monkeypatch.setattr(paypal_service, "get_paypal_balances", balances)
    monkeypatch.setattr(paypal_service, "get_paypal_transactions", transactions)
    monkeypatch.setattr(analysis_service.ShoppingSettings, "from_environment", classmethod(
        lambda cls: ShoppingSettings("fake-groq-key", "configured-existing-model")
    ))
    monkeypatch.setattr(analysis_service, "_request_groq_analysis", groq)

    result = asyncio.run(analysis_service.analyze_paypal_data())

    assert calls[0] == "balances"
    assert calls[1] == ("transactions", {"days": 30, "page": 1, "page_size": 100})
    assert calls[2][0] == "groq"
    payload = calls[2][1]
    assert calls[2][2] == "configured-existing-model"
    assert payload["balances"][0]["value"] == "42.10"
    assert "account_id" not in repr(payload)
    assert "transaction_id" not in repr(payload)
    assert "must-not-be-sent" not in repr(payload)
    assert result.environment == "sandbox"
    assert result.data_label == "PayPal Sandbox demo data"
    assert result.transaction_observations[1].classification == "opening_balance"
    assert "Transaction records were returned" in result.summary


def test_opening_balance_cannot_be_reported_as_income(monkeypatch):
    content = analysis_content().model_copy(update={
        "income_insights": [],
        "spending_insights": [],
        "transaction_observations": [
            analysis_content().transaction_observations[0].model_copy(update={
                "transaction_number": 1,
                "classification": "uncertain",
            }),
            analysis_content().transaction_observations[1].model_copy(update={
                "transaction_number": 2,
                "classification": "income",
            }),
        ],
    })
    balances = []
    transactions = [
        {"transaction_number": 1, "currency": "USD", "event_code": "T0006", "transaction_type": "Payment", "description": "Cafe purchase"},
        {"transaction_number": 2, "currency": "EUR", "event_code": "T0000", "transaction_type": "Opening balance", "description": "Opening balance"},
    ]

    grounded = analysis_service._validate_grounding(content, balances, transactions)
    assert grounded.transaction_observations[1].classification == "opening_balance"
    assert "not treated as income" in grounded.transaction_observations[1].observation


def test_general_account_correction_is_not_inferred_as_opening_balance_or_income():
    content = PayPalAnalysisContent.model_validate({
        "spending_insights": [],
        "income_insights": [],
        "transaction_observations": [{
            "transaction_number": 1,
            "currency": "PHP",
            "classification": "income",
            "event_code_evidence": "T1900",
            "description_evidence": "Initial balance",
            "observation": "The transaction may be income.",
        }],
        "recommendations": [],
    })
    transaction = {
        "transaction_number": 1,
        "currency": "PHP",
        "event_code": "T1900",
        "transaction_type": "General account correction",
        "description": "Initial balance",
    }
    grounded = analysis_service._validate_grounding(content, [], [transaction])
    assert grounded.transaction_observations[0].classification == "uncertain"
    assert "not establish income or spending" in grounded.transaction_observations[0].observation


def test_uncertain_transaction_recommendation_is_not_ai_inferred(monkeypatch):
    async def balances():
        return {"balances": []}

    async def transactions(**kwargs):
        return {"transaction_details": [{"transaction_info": {
            "transaction_event_code": "T1900",
            "transaction_type": "General account correction",
            "transaction_amount": {"currency_code": "PHP", "value": "10.00"},
            "transaction_subject": "Initial balance",
        }}], "total_pages": 1, "page": 1}

    async def groq(payload, settings):
        return PayPalAnalysisContent.model_validate({
            "spending_insights": [],
            "income_insights": [],
            "transaction_observations": [{
                "transaction_number": 1,
                "currency": "PHP",
                "classification": "income",
                "event_code_evidence": "T1900",
                "description_evidence": "Initial balance",
                "observation": "The row might be income.",
            }],
            "recommendations": ["Treat this initial balance as income."],
        })

    monkeypatch.setattr(paypal_service, "get_paypal_balances", balances)
    monkeypatch.setattr(paypal_service, "get_paypal_transactions", transactions)
    monkeypatch.setattr(analysis_service.ShoppingSettings, "from_environment", classmethod(
        lambda cls: ShoppingSettings("fake-groq-key", "configured-existing-model")
    ))
    monkeypatch.setattr(analysis_service, "_request_groq_analysis", groq)
    result = asyncio.run(analysis_service.analyze_paypal_data())

    assert result.transaction_observations[0].classification == "uncertain"
    assert result.recommendations == [
        "Review records marked uncertain against their original PayPal Sandbox details before categorizing them."
    ]


def test_currency_insight_cannot_combine_currencies():
    content = analysis_content().model_copy(update={
        "spending_insights": [analysis_content().spending_insights[0].model_copy(update={
            "currency": "EUR",
            "transaction_numbers": [1],
        })],
    })
    transactions = [
        {"transaction_number": 1, "currency": "USD", "event_code": "T0006", "transaction_type": "Payment", "description": "Cafe purchase"},
        {"transaction_number": 2, "currency": "EUR", "event_code": "T0000", "transaction_type": "Opening balance", "description": "Opening balance"},
    ]
    with pytest.raises(analysis_service.PayPalAnalysisError, match="same-currency"):
        analysis_service._validate_grounding(content, [], transactions)


def test_empty_transaction_page_stays_explicitly_empty(monkeypatch):
    async def balances():
        return {"balances": []}

    async def transactions(**kwargs):
        return {"transaction_details": [], "total_items": 0, "total_pages": 0, "page": 1}

    async def groq(payload, settings):
        assert payload["transaction_history_status"] == "no_records_returned_in_fetched_page"
        return PayPalAnalysisContent.model_validate({
            "spending_insights": [],
            "income_insights": [],
            "transaction_observations": [],
            "recommendations": ["Review PayPal again when transaction records become available."],
        })

    monkeypatch.setattr(paypal_service, "get_paypal_balances", balances)
    monkeypatch.setattr(paypal_service, "get_paypal_transactions", transactions)
    monkeypatch.setattr(analysis_service.ShoppingSettings, "from_environment", classmethod(
        lambda cls: ShoppingSettings("fake-groq-key", "configured-existing-model")
    ))
    monkeypatch.setattr(analysis_service, "_request_groq_analysis", groq)
    result = asyncio.run(analysis_service.analyze_paypal_data())
    assert result.data_scope["balances_status"] == "no_records_returned"
    assert result.data_scope["transaction_history_status"] == "no_records_returned_in_fetched_page"
    assert result.transaction_observations == []


def test_groq_adapter_reuses_configured_model_and_sends_no_paypal_credentials(monkeypatch):
    captured = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return type("Response", (), {
                "choices": [type("Choice", (), {
                    "message": type("Message", (), {
                        "content": analysis_content().model_dump_json(),
                    })(),
                })()],
            })()

    class FakeGroq:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

        async def close(self):
            captured["closed"] = True

    monkeypatch.setattr("groq.AsyncGroq", FakeGroq)
    settings = ShoppingSettings("fake-groq-key", "configured-existing-model")
    payload = {
        "data_label": "PayPal Sandbox demo data",
        "balances": [{"currency": "USD", "value": "12.00"}],
        "transactions": [],
    }
    result = asyncio.run(analysis_service._request_groq_analysis(payload, settings))
    messages = repr(captured["messages"])
    assert result.transaction_observations
    assert captured["model"] == "configured-existing-model"
    assert captured["client"]["api_key"] == "fake-groq-key"
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert "fake-groq-key" not in messages
    assert "must-not-be-sent" not in messages
    assert captured["closed"] is True


def test_paypal_analysis_route_retains_guest_session_dependency():
    dependency = inspect.signature(analyze_paypal_transactions).parameters["session"].default
    assert isinstance(dependency, params.Depends)
    assert dependency.dependency is require_session
    with pytest.raises(HTTPException) as error:
        require_session(None)
    assert error.value.status_code == 401


def test_paypal_analysis_route_returns_structured_json(monkeypatch):
    result = analysis_service.PayPalAnalysisResponse(
        **analysis_content().model_dump(),
        summary="Transaction records were returned in the fetched PayPal Sandbox page.",
        success=True,
        environment="sandbox",
        data_label="PayPal Sandbox demo data",
        analysis_disclaimer=analysis_service.ANALYSIS_DISCLAIMER,
        data_scope={
            "balances_status": "records_returned",
            "balance_amounts_returned": 1,
            "transaction_records_returned": 2,
            "transaction_history_status": "records_returned",
            "transactions_analyzed_page": 1,
            "transactions_total_pages": 1,
            "transaction_history_may_be_partial": False,
        },
    )

    async def analyze():
        return result

    monkeypatch.setattr("app.api.paypal.analyze_paypal_data", analyze)
    body = asyncio.run(analyze_paypal_transactions(session={"session_id": "test"}))
    encoded = body.model_dump()
    assert encoded["success"] is True
    assert encoded["environment"] == "sandbox"
    assert encoded["transaction_observations"][1]["classification"] == "opening_balance"
    assert encoded["data_label"] == "PayPal Sandbox demo data"


def test_paypal_analysis_route_maps_service_errors_to_http_errors(monkeypatch):
    async def fail():
        raise analysis_service.PayPalAnalysisError("groq_timeout", "Groq analysis timed out.", 504)

    monkeypatch.setattr("app.api.paypal.analyze_paypal_data", fail)
    with pytest.raises(HTTPException) as error:
        asyncio.run(analyze_paypal_transactions(session={"session_id": "test"}))
    assert error.value.status_code == 504
    assert error.value.detail["code"] == "groq_timeout"
