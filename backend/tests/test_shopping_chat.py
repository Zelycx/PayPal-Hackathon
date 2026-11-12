from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.services.shopping_service import GroqVisionProvider


def authorized_headers(client: TestClient) -> dict[str, str]:
    response = client.post("/session/start", json={"display_name": "Chat test"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_contextual_chat_uses_validated_purchase_summary(monkeypatch):
    captured = {}

    class FakeProvider:
        def __init__(self, api_key: str):
            assert api_key == "test-groq-key"

        async def answer_purchase_question(
            self, question, purchase_context, history, model, timeout_seconds,
            paypal_context=None, max_output_tokens=650,
        ):
            captured.update(
                question=question,
                context=purchase_context,
                history=history,
                model=model,
                timeout=timeout_seconds,
                paypal=paypal_context,
            )
            return "The Sandbox balance covers the extracted total, but this does not establish overall affordability."

    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setattr("app.api.shopping.GroqVisionProvider", FakeProvider)
    monkeypatch.setattr(
        "app.api.shopping.retrieve_paypal_chat_data",
        lambda question, history: asyncio.sleep(0, result=None),
    )
    with TestClient(app) as client:
        response = client.post(
            "/shopping/chat",
            headers=authorized_headers(client),
            json={
                "message": "Can I afford this?",
                "context": {
                    "screen_type": "checkout",
                    "products": [{
                        "name": "Desk lamp",
                        "item_context": "cart_item",
                        "unit_price": "45.00",
                        "currency": "PHP",
                        "uncertain_fields": [],
                    }],
                    "purchase_evaluation": {
                        "status": "WITHIN_BALANCE",
                        "total_amount": "45.00",
                        "currency": "PHP",
                        "total_complete": True,
                        "matched_balance_amount": "100.00",
                        "matched_balance_currency": "PHP",
                        "remaining_balance": "55.00",
                        "balance_comparison": "WITHIN_LIMIT",
                        "balance_freshness": "fresh",
                        "warnings": [],
                    },
                    "warnings": [],
                },
                "history": [
                    {"role": "user", "content": "I selected a lamp."},
                    {"role": "assistant", "content": "The selected crop is ready."},
                ],
            },
        )

    assert response.status_code == 200
    assert response.json()["answer"].startswith("The Sandbox balance")
    assert captured["question"] == "Can I afford this?"
    assert captured["context"]["purchase_evaluation"]["matched_balance_amount"] == "100.00"
    assert captured["history"][0]["content"] == "I selected a lamp."
    assert "transactions" not in captured["context"]


def test_contextual_chat_requires_guest_session():
    with TestClient(app) as client:
        response = client.post("/shopping/chat", json={"message": "Can I afford it?"})
    assert response.status_code == 401


def test_contextual_chat_reports_missing_groq_configuration(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with TestClient(app) as client:
        response = client.post(
            "/shopping/chat",
            headers=authorized_headers(client),
            json={"message": "Can I afford it?"},
        )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "assistant_not_configured"


def test_contextual_chat_rejects_unmodeled_financial_data():
    with TestClient(app) as client:
        response = client.post(
            "/shopping/chat",
            headers=authorized_headers(client),
            json={
                "message": "Can I afford it?",
                "context": {"transactions": [{"transaction_id": "private"}]},
            },
        )
    assert response.status_code == 422


def test_groq_chat_adapter_sends_context_without_image_or_transaction_data(monkeypatch):
    captured = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content="Review the displayed total before deciding.")
            )])

    class FakeGroq:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def close(self):
            captured["closed"] = True

    monkeypatch.setattr("groq.AsyncGroq", FakeGroq)
    answer = asyncio.run(GroqVisionProvider("test-key").answer_purchase_question(
        question="What should I verify?",
        purchase_context={"screen_type": "checkout", "products": [{"name": "Lamp"}]},
        history=[{"role": "user", "content": "I selected a lamp."}],
        model="test-model",
        timeout_seconds=5,
            paypal_context={"balances": []},
    ))

    assert answer.startswith("Review the displayed")
    assert captured["closed"] is True
    messages = captured["messages"]
    assert "general budgeting" in messages[0]["content"]
    assert "Do not perform financial arithmetic" in messages[0]["content"]
    assert "individual PayPal identity links" in messages[0]["content"]
    payload = json.loads(messages[-1]["content"])
    assert payload["question"] == "What should I verify?"
    assert payload["purchase_context"]["products"][0]["name"] == "Lamp"
    assert "transactions" not in messages[-1]["content"]
    assert all("image_url" not in str(message) for message in messages)


def test_chat_route_supplies_fresh_balance_context_to_groq(monkeypatch):
    captured = {}

    class FakeProvider:
        def __init__(self, api_key):
            pass

        async def answer_purchase_question(self, **kwargs):
            captured.update(kwargs)
            return "The configured Sandbox account reports a USD available balance of 42.10."

    async def fake_data(question, history):
        assert question == "What is the PayPal balance?"
        return {
            "source": "configured PayPal Sandbox application account",
            "retrieved_at": "2026-11-13T00:00:00Z",
            "balance_status": "returned",
            "balances": [{
                "currency": "USD",
                "total": {"currency": "USD", "amount": "42.10"},
                "available": {"currency": "USD", "amount": "40.00"},
                "withheld": {"currency": "USD", "amount": "2.10"},
            }],
            "pending_balance_available": False,
        }

    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setattr("app.api.shopping.GroqVisionProvider", FakeProvider)
    monkeypatch.setattr("app.api.shopping.retrieve_paypal_chat_data", fake_data)
    with TestClient(app) as client:
        response = client.post(
            "/shopping/chat",
            headers=authorized_headers(client),
            json={"message": "What is the PayPal balance?"},
        )

    assert response.status_code == 200
    assert captured["paypal_context"]["balances"][0]["available"]["amount"] == "40.00"
    assert captured["paypal_context"]["balances"][0]["total"]["amount"] == "42.10"


def test_chat_route_does_not_call_groq_when_paypal_data_cannot_be_retrieved(monkeypatch):
    async def fail_data(question, history):
        raise RuntimeError("provider details must not reach logs")

    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setattr("app.api.shopping.retrieve_paypal_chat_data", fail_data)
    with TestClient(app) as client:
        response = client.post(
            "/shopping/chat",
            headers=authorized_headers(client),
            json={"message": "What is my current balance?"},
        )
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "paypal_data_unavailable"
