from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.finance.analyzer import detect_unusual_spending, recurring_candidates
from app.finance.calculations import budget_status, cashflow_summary, category_totals, estimate_month_end, savings_progress
from app.finance.purchase_advisor import evaluate_purchase


def tx(amount, currency="PHP", kind="expense", category="Food", status="posted", merchant="Cafe", day=1):
    return SimpleNamespace(amount=Decimal(amount), currency=currency, kind=kind, category=category, status=status, merchant=merchant, id=day, occurred_at=datetime(2026, 1, day, tzinfo=timezone.utc))


def test_cashflow_refund_transfer_and_currency_separation():
    rows = [tx("100.00", kind="income"), tx("50.00"), tx("10.00", kind="refund"), tx("500.00", kind="transfer"), tx("20.00", currency="USD", kind="expense")]
    result = cashflow_summary(rows)
    assert result["income"] == {"PHP": Decimal("100.00")}
    assert result["expenses_net_of_refunds"] == {"PHP": Decimal("40.00"), "USD": Decimal("20.00")}
    assert result["net_recorded_cash_flow"] == {"PHP": Decimal("60.00"), "USD": Decimal("-20.00")}
    assert result["transfer_amounts_excluded"] == {"PHP": Decimal("500.00")}


def test_category_totals_keep_currency_separate():
    rows = [tx("8.00", currency="PHP"), tx("2.00", currency="USD"), tx("1.00", kind="refund", currency="PHP")]
    assert category_totals(rows) == {"PHP": {"Food": Decimal("7.00")}, "USD": {"Food": Decimal("2.00")}}
    assert category_totals(rows, "PHP") == {"Food": Decimal("7.00")}


def test_budget_and_savings_calculations_use_decimal():
    budget = SimpleNamespace(id=1, name="Food", category="Food", period="monthly", currency="PHP", amount=Decimal("1000.00"))
    assert budget_status(budget, Decimal("850.00"))["remaining"] == Decimal("150.00")
    goal = SimpleNamespace(id=2, name="Emergency fund", currency="PHP", target_amount=Decimal("10000"), current_amount=Decimal("2500"), target_date=None)
    assert savings_progress(goal)["remaining"] == Decimal("7500")
    assert savings_progress(goal)["progress_percent"] == Decimal("25.00")


def test_purchase_requires_budget_and_same_currency_balance():
    accounts = [SimpleNamespace(currency="PHP", balance=Decimal("10000"), available_balance=Decimal("9000"))]
    budget = SimpleNamespace(amount=Decimal("5000"))
    assert evaluate_purchase(Decimal("1000"), "PHP", accounts, budget, Decimal("2000"), [], Decimal("500"))["verdict"] == "within_recorded_budget"
    assert evaluate_purchase(Decimal("1000"), "USD", accounts, budget, Decimal("2000"), [])["verdict"] == "insufficient_information"
    assert evaluate_purchase(Decimal("1000"), "PHP", accounts, None, None, [])["verdict"] == "insufficient_information"


def test_estimate_and_unusual_patterns_are_labeled():
    assert estimate_month_end(Decimal("300"), 10, 30)["estimate"] == Decimal("900.00")
    rows = [tx("10", day=1), tx("10", day=2), tx("10", day=3), tx("100", day=4)]
    findings = detect_unusual_spending(rows)
    assert len(findings) == 1 and findings[0]["label"] == "potentially_unusual"
    assert recurring_candidates(rows) == [{"merchant": "cafe", "currency": "PHP", "occurrences": 4, "label": "potentially_recurring", "note": "Repeated recorded payments may be recurring; verify with the account provider."}]
