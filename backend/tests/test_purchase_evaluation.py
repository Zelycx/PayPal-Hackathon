from __future__ import annotations

import asyncio
import io
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.schemas.shopping import (
    CheckoutBreakdownStatus,
    CurrencyTotals,
    LimitComparison,
    PurchaseBudget,
    PurchaseEvaluation,
    PurchaseStatus,
    ScreenType,
    ShoppingResponse,
)
from app.services.purchase_evaluation import PurchaseEvaluationService
from app.services.session_service import create_session
from app.services.shopping_service import (
    GroqVisionProvider,
    ShoppingService,
    ShoppingSettings,
    get_shopping_service,
)
from app.services.purchase_evaluation import get_purchase_evaluation_service


def shopping(
    *,
    total: str | None = "100.00",
    currency: str = "PHP",
    complete: bool = True,
    mixed: bool = False,
    requires_review: bool = False,
) -> ShoppingResponse:
    base = CurrencyTotals(
        currency=currency,
        items_subtotal="100.00",
        items_subtotal_complete=complete,
        shipping_total="0",
        tax_total="0",
        other_charges_total="0",
        discount_total="0",
        calculated_payable_total=total if complete else None,
        payable_total_complete=complete,
    )
    totals = [base]
    if mixed:
        totals.append(CurrencyTotals(
            currency="USD",
            items_subtotal="2.00",
            items_subtotal_complete=True,
            calculated_payable_total="2.00",
            payable_total_complete=True,
        ))
    return ShoppingResponse(
        screen_type=ScreenType.checkout,
        totals_by_currency=totals,
        checkout_breakdown_status=CheckoutBreakdownStatus.complete,
        requires_review=requires_review,
    )


def balances(amount: str = "500.00", currency: str = "PHP", age: timedelta = timedelta(minutes=10)) -> dict:
    refreshed = (datetime.now(timezone.utc) - age).isoformat()
    return {
        "balances": [{
            "currency": currency,
            "available_balance": {"currency_code": currency, "value": amount},
            "total_balance": {"currency_code": currency, "value": amount},
        }],
        "as_of_time": refreshed,
        "last_refresh_time": refreshed,
    }


async def no_opinion(_context: dict) -> str:
    return "The stated limits are shown above; consider any costs not visible in the crop."


def evaluator(payload: dict | None = None, *, opinion=no_opinion, error: Exception | None = None):
    async def load():
        if error:
            raise error
        return payload if payload is not None else balances()

    return PurchaseEvaluationService(
        balance_loader=load,
        opinion_generator=opinion,
        settings=ShoppingSettings(api_key=None, vision_model="test-model"),
    )


def run(service: PurchaseEvaluationService, analysis: ShoppingResponse, budget: PurchaseBudget | None = None):
    return asyncio.run(service.evaluate(analysis, budget))


def test_decimal_purchase_and_both_remaining_amounts_use_exact_arithmetic():
    result = run(evaluator(), shopping(total="100.10"), PurchaseBudget(amount="150.50", currency="PHP"))
    assert result.status == PurchaseStatus.within_budget_and_balance
    assert result.remaining_balance == "399.90"
    assert result.remaining_budget == "50.40"
    assert result.ai_opinion_available is True


def test_large_decimal_subtractions_retain_fractional_precision():
    total = "123456789012345678901234.123456789012345678"
    budget = "123456789012345678901235.123456789012345679"
    balance = "123456789012345678901236.123456789012345678"
    result = run(
        evaluator(balances(balance)),
        shopping(total=total),
        PurchaseBudget(amount=budget, currency="PHP"),
    )
    assert result.remaining_budget == "1.000000000000000001"
    assert result.remaining_balance == "2.000000000000000000"


@pytest.mark.parametrize(
    ("total", "budget", "balance", "expected"),
    [
        ("101", "100", "500", PurchaseStatus.over_budget),
        ("101", "200", "100", PurchaseStatus.insufficient_balance),
        ("101", "100", "100", PurchaseStatus.both_limits_exceeded),
    ],
)
def test_budget_and_balance_limit_statuses(total, budget, balance, expected):
    service = evaluator(balances(balance))
    result = run(service, shopping(total=total), PurchaseBudget(amount=budget, currency="PHP"))
    assert result.status == expected


def test_missing_budget_is_explicit_and_balance_comparison_still_works():
    result = run(evaluator(), shopping())
    assert result.status == PurchaseStatus.within_balance
    assert result.budget_amount is None
    assert result.budget_comparison == LimitComparison.not_provided


def test_currency_mismatch_never_converts_or_compares():
    result = run(evaluator(balances("500", "USD")), shopping(), PurchaseBudget(amount="150", currency="EUR"))
    assert result.status == PurchaseStatus.currency_mismatch
    assert result.remaining_balance is None
    assert result.remaining_budget is None
    assert result.balance_comparison == LimitComparison.currency_mismatch
    assert result.budget_comparison == LimitComparison.currency_mismatch


def test_multiple_purchase_currencies_are_not_summed_or_converted():
    result = run(evaluator(), shopping(mixed=True))
    assert result.status == PurchaseStatus.currency_mismatch
    assert result.total_amount is None
    assert result.currency is None


def test_unknown_prices_or_missing_total_require_review():
    result = run(evaluator(), shopping(total=None, complete=False), PurchaseBudget(amount="200", currency="PHP"))
    assert result.status == PurchaseStatus.needs_review
    assert result.total_complete is False
    assert result.remaining_budget is None
    assert result.budget_comparison == LimitComparison.needs_review


def test_items_subtotal_is_not_misrepresented_as_complete_checkout_total():
    analysis = shopping(total=None, complete=False).model_copy(update={"screen_type": ScreenType.cart})
    result = run(evaluator(), analysis)
    assert result.total_amount == "100.00"
    assert result.total_source == "items_subtotal"
    assert result.total_complete is False
    assert result.status == PurchaseStatus.needs_review
    assert any("taxes, delivery" in warning for warning in result.warnings)


def test_clear_visible_payable_total_on_cart_is_used_before_incomplete_subtotal():
    group = CurrencyTotals(
        currency="PHP",
        items_subtotal="100.00",
        items_subtotal_complete=True,
        payable_total_complete=False,
        visible_checkout_total="110.00",
        visible_checkout_total_confidence=0.95,
    )
    analysis = shopping(total=None, complete=False).model_copy(update={
        "screen_type": ScreenType.cart,
        "totals_by_currency": [group],
    })

    result = run(evaluator(), analysis)

    assert result.total_amount == "110.00"
    assert result.total_source == "visible_checkout_total"
    assert result.total_complete is True
    assert result.remaining_balance == "390.00"


def test_unavailable_sandbox_balance_preserves_budget_result_and_ai_opinion():
    result = run(evaluator(error=RuntimeError("do not expose provider detail")), shopping(), PurchaseBudget(amount="200", currency="PHP"))
    assert result.status == PurchaseStatus.balance_unavailable
    assert result.balance_available is False
    assert result.budget_comparison == LimitComparison.within_limit
    assert result.remaining_budget == "100.00"
    assert result.ai_opinion_available is True
    assert "do not expose" not in " ".join(result.warnings)


def test_stale_sandbox_balance_requires_review():
    result = run(evaluator(balances(age=timedelta(hours=4))), shopping())
    assert result.balance_freshness == "stale"
    assert result.balance_comparison == LimitComparison.needs_review
    assert result.status == PurchaseStatus.needs_review


def test_ai_failure_does_not_remove_deterministic_result():
    async def fail(_context: dict) -> str:
        raise RuntimeError("sensitive provider error")

    result = run(evaluator(opinion=fail), shopping())
    assert result.status == PurchaseStatus.within_balance
    assert result.remaining_balance == "400.00"
    assert result.ai_opinion is None
    assert result.ai_opinion_available is False
    assert any("AI explanation is unavailable" in warning for warning in result.warnings)


def test_disconnect_after_evaluation_keeps_numeric_result_and_skips_optional_ai():
    called = False

    async def opinion(_context: dict) -> str:
        nonlocal called
        called = True
        return "Should not be called after disconnect."

    async def disconnected() -> bool:
        return True

    result = asyncio.run(evaluator(opinion=opinion).evaluate(
        shopping(), None, cancellation_check=disconnected
    ))
    assert result.status == PurchaseStatus.within_balance
    assert result.remaining_balance == "400.00"
    assert result.ai_opinion is None
    assert called is False


def test_groq_purchase_explanation_uses_configured_model_and_closes_client(monkeypatch):
    captured = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return type("Response", (), {
                "choices": [type("Choice", (), {
                    "message": type("Message", (), {"content": "The identified amount is within the supplied limit."})()
                })()]
            })()

    class FakeGroq:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

        async def close(self):
            captured["closed"] = True

    monkeypatch.setattr("groq.AsyncGroq", FakeGroq)
    context = {"server_evaluation": {"status": "WITHIN_BALANCE", "total_amount": "10.00"}}
    opinion = asyncio.run(GroqVisionProvider("fake-key").explain_purchase(
        context, "configured-text-model", 8.0
    ))

    assert opinion == "The identified amount is within the supplied limit."
    assert captured["model"] == "configured-text-model"
    assert captured["client"]["max_retries"] == 0
    assert "messages" in captured
    assert "transaction" not in repr(captured["messages"]).lower()
    assert captured["closed"] is True


def test_application_import_registers_authenticated_paypal_routes():
    with TestClient(app) as client:
        paths = app.openapi()["paths"]
        assert "/shopping/analyze" in paths
        assert "/paypal/connection" in paths
        assert "/paypal/balances" in paths
        assert "/paypal/transactions" in paths
        assert "/paypal/analyze" in paths
        assert client.get("/paypal/balances").status_code == 401
        assert client.post("/paypal/analyze").status_code == 401


def test_authenticated_multipart_route_is_backward_compatible_and_accepts_budget():
    class FakeVision:
        async def analyze_image(self, *args):
            return '{"screen_type":"cart","products":[],"charges":[],"discounts":[],"visible_totals":[],"checkout_breakdown_status":"unknown","warnings":[]}'

    class FixedEvaluator:
        def __init__(self):
            self.budget = "not called"

        async def evaluate(self, analysis, budget, cancellation_check=None):
            self.budget = budget
            return PurchaseEvaluation(
                status=PurchaseStatus.balance_unavailable,
                total_complete=False,
                balance_available=False,
                balance_freshness="unavailable",
                balance_comparison=LimitComparison.unavailable,
                budget_comparison=LimitComparison.not_provided if budget is None else LimitComparison.needs_review,
            )

    vision = ShoppingService(
        vision_provider=FakeVision(),
        settings=ShoppingSettings(api_key=None, vision_model="test-model"),
    )
    fixed = FixedEvaluator()
    app.dependency_overrides[get_shopping_service] = lambda: vision
    app.dependency_overrides[get_purchase_evaluation_service] = lambda: fixed
    try:
        with TestClient(app) as client:
            session_id, token, _ = create_session("route test")
            headers = {"Authorization": f"Bearer {token}"}
            image_stream = io.BytesIO()
            Image.new("RGB", (4, 4)).save(image_stream, format="PNG")
            image_data = image_stream.getvalue()

            old_contract = client.post(
                "/shopping/analyze",
                headers=headers,
                files={"image": ("cart.png", image_data, "image/png")},
            )
            assert old_contract.status_code == 200
            assert old_contract.json()["purchase_evaluation"] is None

            response = client.post(
                "/shopping/analyze",
                headers=headers,
                data={
                    "include_purchase_evaluation": "true",
                    "budget_amount": "125.50",
                    "budget_currency": "php",
                },
                files={"image": ("cart.png", image_data, "image/png")},
            )
            assert response.status_code == 200
            assert response.json()["purchase_evaluation"]["status"] == "BALANCE_UNAVAILABLE"
            assert fixed.budget == PurchaseBudget(amount="125.50", currency="PHP")

            no_session = client.post(
                "/shopping/analyze",
                data={"include_purchase_evaluation": "true"},
                files={"image": ("cart.png", image_data, "image/png")},
            )
            assert no_session.status_code == 401
    finally:
        app.dependency_overrides.pop(get_shopping_service, None)
        app.dependency_overrides.pop(get_purchase_evaluation_service, None)
