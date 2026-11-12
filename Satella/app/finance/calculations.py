from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable

from app.database.models import Budget, SavingsGoal, Transaction

ZERO = Decimal("0.00")


def source_summary(records: Iterable[object]) -> dict[str, object]:
    sources = sorted({str(getattr(item, "source", "recorded")) for item in records})
    return {"source": sources[0] if len(sources) == 1 else "mixed" if sources else "none", "sources": sources, "simulated": "simulated" in sources}


def amount_by_currency(transactions: Iterable[Transaction], kinds: set[str]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for item in transactions:
        if item.status != "posted":
            continue
        if item.kind in kinds:
            totals[item.currency] += Decimal(item.amount)
        elif item.kind == "refund" and "expense" in kinds:
            totals[item.currency] -= Decimal(item.amount)
    return dict(totals)


def cashflow_summary(transactions: list[Transaction]) -> dict[str, object]:
    income = amount_by_currency(transactions, {"income"})
    expenses = amount_by_currency(transactions, {"expense"})
    currencies = sorted(set(income) | set(expenses))
    return {
        "income": income,
        "expenses_net_of_refunds": expenses,
        "net_recorded_cash_flow": {currency: income.get(currency, ZERO) - expenses.get(currency, ZERO) for currency in currencies},
        "transfer_amounts_excluded": amount_by_currency(transactions, {"transfer"}),
        "currencies_kept_separate": True,
    }


def category_totals(transactions: list[Transaction], currency: str | None = None) -> dict[str, Decimal] | dict[str, dict[str, Decimal]]:
    totals: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    for item in transactions:
        if item.status != "posted" or item.kind not in {"expense", "refund"}:
            continue
        if currency and item.currency != currency:
            continue
        amount = Decimal(item.amount) * (Decimal("-1") if item.kind == "refund" else Decimal("1"))
        totals[item.currency][item.category] += amount
    if currency:
        return dict(totals.get(currency, {}))
    return {code: dict(categories) for code, categories in totals.items()}


def budget_status(budget: Budget, spent: Decimal) -> dict[str, object]:
    remaining = Decimal(budget.amount) - spent
    usage = (spent / Decimal(budget.amount) * 100) if budget.amount else ZERO
    return {
        "id": budget.id,
        "name": budget.name,
        "category": budget.category,
        "period": budget.period,
        "currency": budget.currency,
        "limit": Decimal(budget.amount),
        "spent": spent,
        "remaining": remaining,
        "usage_percent": usage.quantize(Decimal("0.01")),
        "threshold": "over_budget" if remaining < ZERO else "near_limit" if usage >= 80 else "within_limit",
    }


def savings_progress(goal: SavingsGoal) -> dict[str, object]:
    remaining = max(ZERO, Decimal(goal.target_amount) - Decimal(goal.current_amount))
    percent = (Decimal(goal.current_amount) / Decimal(goal.target_amount) * 100) if goal.target_amount else ZERO
    return {
        "id": goal.id,
        "name": goal.name,
        "currency": goal.currency,
        "target": Decimal(goal.target_amount),
        "current": Decimal(goal.current_amount),
        "remaining": remaining,
        "progress_percent": percent.quantize(Decimal("0.01")),
        "estimated_completion_date": None,
        "completion_estimate_note": "A completion date requires a recorded contribution schedule.",
    }


def period_start(period: str, now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if period == "last_7_days":
        return current - timedelta(days=7)
    if period == "last_30_days":
        return current - timedelta(days=30)
    if period == "weekly":
        return (current - timedelta(days=current.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def estimate_month_end(current_spend: Decimal, day_of_month: int, days_in_month: int) -> dict[str, Decimal | str]:
    if day_of_month < 1 or days_in_month < day_of_month:
        return {"estimate": ZERO, "method": "unavailable", "note": "Calendar period is invalid."}
    estimate = (current_spend / Decimal(day_of_month) * Decimal(days_in_month)).quantize(Decimal("0.01"))
    return {"estimate": estimate, "method": "straight_line_extrapolation", "note": "A simple estimate from recorded month-to-date spending; not a prediction."}
