from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Account, Budget, SavingsGoal, Transaction
from app.finance.calculations import budget_status, category_totals, cashflow_summary, period_start, savings_progress, source_summary


def user_transactions(db: Session, user_id: str, since: datetime | None = None) -> list[Transaction]:
    query = select(Transaction).where(Transaction.user_id == user_id).order_by(Transaction.occurred_at.desc())
    if since:
        query = query.where(Transaction.occurred_at >= since)
    return list(db.scalars(query).all())


def overview(db: Session, user_id: str) -> dict[str, object]:
    accounts = list(db.scalars(select(Account).where(Account.user_id == user_id)).all())
    transactions = user_transactions(db, user_id, period_start("monthly"))
    sources = source_summary([*accounts, *transactions])
    currencies: dict[str, Decimal] = {}
    for account in accounts:
        currencies[account.currency] = currencies.get(account.currency, Decimal("0.00")) + Decimal(account.balance)
    return {
        **sources,
        "account_count": len(accounts),
        "balances_by_currency": currencies,
        "month_to_date_cash_flow": cashflow_summary(transactions),
        "month_to_date_category_totals": category_totals(transactions),
        "balance_freshness": [{"account_id": a.id, "currency": a.currency, "synced_at": a.synced_at, "stale": (datetime.now(timezone.utc) - (a.synced_at.replace(tzinfo=timezone.utc) if a.synced_at.tzinfo is None else a.synced_at)).total_seconds() > 24 * 3600} for a in accounts],
    }


def budgets_view(db: Session, user_id: str) -> list[dict[str, object]]:
    budgets = list(db.scalars(select(Budget).where(Budget.user_id == user_id)).all())
    result = []
    for budget in budgets:
        budget_transactions = user_transactions(db, user_id, period_start("weekly" if budget.period == "weekly" else "monthly"))
        spent = sum((Decimal(t.amount) * (Decimal("-1") if t.kind == "refund" else Decimal("1")) for t in budget_transactions if t.kind in {"expense", "refund"} and (budget.category is None or t.category == budget.category) and t.currency == budget.currency and t.status == "posted"), Decimal("0.00"))
        result.append(budget_status(budget, spent))
    return result


def savings_view(db: Session, user_id: str) -> list[dict[str, object]]:
    goals = db.scalars(select(SavingsGoal).where(SavingsGoal.user_id == user_id)).all()
    return [savings_progress(goal) for goal in goals]
