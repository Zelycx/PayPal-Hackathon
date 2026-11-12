import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from app.core.exceptions import ServiceError
from app.database.models import Account, Budget, SavingsGoal, Transaction
from app.finance.analyzer import detect_unusual_spending, recurring_candidates, trend_summary
from app.finance.calculations import ZERO, budget_status, cashflow_summary, category_totals, estimate_month_end, period_start, savings_progress, source_summary
from app.finance.categorizer import categorize
from app.finance.financial_context import user_transactions
from app.finance.purchase_advisor import evaluate_purchase

logger = logging.getLogger(__name__)


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyArgs(Args):
    pass


class CurrencyArgs(Args):
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


class TransactionArgs(Args):
    limit: int = Field(default=25, ge=1, le=100)
    days: int | None = Field(default=30, ge=1, le=365)
    category: str | None = Field(default=None, max_length=40)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


class PeriodArgs(Args):
    period: str = Field(default="this_month", pattern=r"^(this_month|this_week|last_7_days|last_30_days)$")
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


class BudgetArgs(CurrencyArgs):
    category: str | None = Field(default=None, max_length=40)


class PurchaseArgs(Args):
    price: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    category: str = Field(default="Shopping", max_length=40)


class CategoryArgs(Args):
    description: str = Field(min_length=1, max_length=250)
    merchant: str | None = Field(default=None, max_length=120)


class EstimateArgs(Args):
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class DailyArgs(Args):
    days: int = Field(default=30, ge=1, le=90)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    arguments: type[BaseModel]
    handler: Callable[[Any, str, BaseModel], Any]

    def model_definition(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.arguments.model_json_schema()}}


def _date_for_period(period: str) -> datetime:
    return period_start("monthly" if period == "this_month" else "weekly" if period == "this_week" else period)


class FinancialToolRegistry:
    """Only exposes registered read-only functions. Each invocation gets a scoped DB session."""

    def __init__(self, session_factory: Callable[[], Any], seed_demo: Callable[[Any, str], None], timeout_seconds: float = 3.0) -> None:
        self.session_factory = session_factory
        self.seed_demo = seed_demo
        self.timeout_seconds = timeout_seconds
        self.tools: dict[str, ToolSpec] = {}
        self._register_defaults()

    def register(self, name: str, description: str, args: type[BaseModel], handler: Callable[[Any, str, BaseModel], Any]) -> None:
        if name in self.tools:
            raise ValueError(f"Duplicate tool: {name}")
        self.tools[name] = ToolSpec(name, description, args, handler)

    def definitions(self) -> list[dict[str, Any]]:
        return [spec.model_definition() for spec in self.tools.values()]

    async def execute(self, name: str, raw_arguments: str, user_id: str) -> tuple[str, dict[str, Any]]:
        started = time.monotonic()
        spec = self.tools.get(name)
        if spec is None:
            return json.dumps({"error": "Tool is not available."}), {"tool": "unregistered", "ok": False}
        try:
            parsed_json = json.loads(raw_arguments or "{}")
            if not isinstance(parsed_json, dict):
                raise ValueError("Tool arguments must be a JSON object.")
            args = spec.arguments.model_validate(parsed_json)
        except (json.JSONDecodeError, ValueError, ValidationError):
            logger.info("tool_execution tool=%s ok=false reason=invalid_arguments", spec.name)
            return json.dumps({"error": "Tool arguments were invalid."}), {"tool": spec.name, "ok": False, "reason": "invalid_arguments"}

        def invoke() -> Any:
            db = self.session_factory()
            try:
                self.seed_demo(db, user_id)
                return spec.handler(db, user_id, args)
            finally:
                db.close()

        try:
            result = await asyncio.wait_for(asyncio.to_thread(invoke), timeout=self.timeout_seconds)
            metadata = {"tool": spec.name, "ok": True, "duration_ms": round((time.monotonic() - started) * 1000)}
            logger.info("tool_execution tool=%s ok=true duration_ms=%s", spec.name, metadata["duration_ms"])
            return json.dumps(result, default=str, ensure_ascii=False), metadata
        except asyncio.TimeoutError:
            logger.warning("tool_execution tool=%s ok=false reason=timeout", spec.name)
            return json.dumps({"error": "The financial data tool timed out."}), {"tool": spec.name, "ok": False, "reason": "timeout"}
        except Exception:
            logger.error("tool_execution tool=%s ok=false reason=internal", spec.name)
            return json.dumps({"error": "The financial data tool failed."}), {"tool": spec.name, "ok": False, "reason": "execution_failure"}

    def _register_defaults(self) -> None:
        def accounts(db, user, args):
            rows = list(db.scalars(select(Account).where(Account.user_id == user)).all())
            if args.currency:
                rows = [row for row in rows if row.currency == args.currency]
            return {**source_summary(rows), "accounts": [{"id": a.id, "name": a.name, "type": a.account_type, "currency": a.currency, "balance": a.balance, "available_balance": a.available_balance, "synced_at": a.synced_at} for a in rows]}

        def transactions(db, user, args):
            since = datetime.now(timezone.utc) - __import__("datetime").timedelta(days=args.days) if args.days else None
            rows = user_transactions(db, user, since)
            rows = [row for row in rows if (not args.category or row.category == args.category) and (not args.currency or row.currency == args.currency)]
            return {**source_summary(rows), "transactions": [{"id": t.id, "description": t.description, "merchant": t.merchant, "amount": t.amount, "currency": t.currency, "kind": t.kind, "category": t.category, "status": t.status, "occurred_at": t.occurred_at, "source": t.source} for t in rows[:args.limit]]}

        def summary(db, user, args, kinds: set[str] | None = None):
            rows = user_transactions(db, user, _date_for_period(args.period))
            if args.currency:
                rows = [t for t in rows if t.currency == args.currency]
            if kinds:
                rows = [t for t in rows if t.kind in kinds or (t.kind == "refund" and "expense" in kinds)]
            return {"period": args.period, "summary": cashflow_summary(rows), "category_totals": category_totals(rows), **source_summary(rows)}

        def budget_statuses(db, user, args):
            budgets = list(db.scalars(select(Budget).where(Budget.user_id == user)).all())
            results = []
            for budget in budgets:
                if args.currency and budget.currency != args.currency:
                    continue
                if args.category and budget.category != args.category:
                    continue
                rows = user_transactions(db, user, period_start("weekly" if budget.period == "weekly" else "monthly"))
                spent = sum((Decimal(t.amount) * (Decimal("-1") if t.kind == "refund" else Decimal("1")) for t in rows if t.kind in {"expense", "refund"} and t.status == "posted" and t.currency == budget.currency and (budget.category is None or t.category == budget.category)), ZERO)
                results.append(budget_status(budget, spent))
            return {"budgets": results, **source_summary(budgets)}

        def savings(db, user, args):
            goals = list(db.scalars(select(SavingsGoal).where(SavingsGoal.user_id == user)).all())
            if args.currency:
                goals = [goal for goal in goals if goal.currency == args.currency]
            return {"goals": [savings_progress(goal) for goal in goals], **source_summary(goals)}

        def recent_recurring(db, user, args):
            rows = user_transactions(db, user, period_start("last_30_days"))
            return {"candidates": recurring_candidates(rows), **source_summary(rows), "caution": "Patterns are candidates only; they do not prove an active subscription."}

        def trend(db, user, args):
            rows = user_transactions(db, user, period_start("last_30_days"))
            return {**trend_summary(rows), **source_summary(rows)}

        def purchase(db, user, args):
            accounts = list(db.scalars(select(Account).where(Account.user_id == user)).all())
            budgets = list(db.scalars(select(Budget).where(Budget.user_id == user, Budget.currency == args.currency, Budget.category == args.category)).all())
            budget = budgets[0] if budgets else None
            budget_period = "weekly" if budget and budget.period == "weekly" else "monthly"
            rows = user_transactions(db, user, period_start(budget_period))
            spent = sum((Decimal(t.amount) * (Decimal("-1") if t.kind == "refund" else Decimal("1")) for t in rows if t.kind in {"expense", "refund"} and t.status == "posted" and t.currency == args.currency and (budget is None or t.category == budget.category)), ZERO)
            goals = list(db.scalars(select(SavingsGoal).where(SavingsGoal.user_id == user)).all())
            upcoming_rows = list(db.scalars(select(Transaction).where(
                Transaction.user_id == user,
                Transaction.currency == args.currency,
                Transaction.kind == "expense",
                Transaction.status.in_(["pending", "scheduled"]),
                Transaction.occurred_at > datetime.now(timezone.utc),
            )).all())
            upcoming = sum((Decimal(t.amount) for t in upcoming_rows), ZERO)
            result_sources = source_summary([*accounts, *budgets, *goals, *upcoming_rows])
            return {**evaluate_purchase(args.price, args.currency, accounts, budget, spent if budget else None, goals, upcoming), **result_sources}

        def remaining(db, user, args):
            return budget_statuses(db, user, args)

        def goal_impact(db, user, args):
            rows = list(db.scalars(select(SavingsGoal).where(SavingsGoal.user_id == user, SavingsGoal.currency == args.currency)).all())
            return {"price": args.price, "currency": args.currency, "goals": [{"name": g.name, "current_amount_unchanged": g.current_amount, "remaining_to_target": max(ZERO, Decimal(g.target_amount) - Decimal(g.current_amount)), "price_as_share_of_remaining_target_percent": ((args.price / (Decimal(g.target_amount) - Decimal(g.current_amount)) * 100).quantize(Decimal("0.01")) if Decimal(g.target_amount) > Decimal(g.current_amount) else None)} for g in rows], "note": "This shows scale relative to goals; the purchase does not change saved amounts in the system."}

        def categorize_tool(db, user, args):
            category, method = categorize(args.description, args.merchant)
            return {"suggested_category": category, "method": method, "note": "Suggestion only; user corrections remain the source of truth."}

        def unusual(db, user, args):
            rows = user_transactions(db, user, datetime.now(timezone.utc) - __import__("datetime").timedelta(days=args.days))
            return {"findings": detect_unusual_spending(rows), **source_summary(rows)}

        def financial_summary(db, user, args):
            rows = user_transactions(db, user, datetime.now(timezone.utc) - __import__("datetime").timedelta(days=args.days))
            return {"cash_flow": cashflow_summary(rows), "category_totals_by_currency": category_totals(rows), "record_count": len(rows), **source_summary(rows)}

        def estimate(db, user, args):
            now = datetime.now(timezone.utc)
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            rows = [t for t in user_transactions(db, user, start) if t.currency == args.currency]
            spent = sum((Decimal(t.amount) * (Decimal("-1") if t.kind == "refund" else Decimal("1")) for t in rows if t.kind in {"expense", "refund"} and t.status == "posted"), ZERO)
            from calendar import monthrange
            return {"currency": args.currency, "month_to_date_spend": spent, **estimate_month_end(spent, now.day, monthrange(now.year, now.month)[1]), **source_summary(rows)}

        def daily_spending(db, user, args):
            from collections import defaultdict
            from datetime import timedelta
            rows = user_transactions(db, user, datetime.now(timezone.utc) - timedelta(days=args.days))
            totals = defaultdict(lambda: ZERO)
            for item in rows:
                if item.status != "posted" or item.kind not in {"expense", "refund"} or (args.currency and args.currency != item.currency):
                    continue
                totals[(item.occurred_at.date().isoformat(), item.currency)] += Decimal(item.amount) * (Decimal("-1") if item.kind == "refund" else Decimal("1"))
            return {"daily_spending": [{"date": day, "currency": currency, "amount": amount} for (day, currency), amount in sorted(totals.items())], **source_summary(rows)}

        self.register("get_all_accounts", "List accounts, balances, currencies, and sync timestamps.", EmptyArgs, accounts)
        self.register("get_account_balance", "Retrieve recorded balance(s), optionally filtered by currency.", CurrencyArgs, accounts)
        self.register("get_transactions", "Retrieve recent recorded transactions with optional filters.", TransactionArgs, transactions)
        self.register("get_recent_transactions", "Retrieve recent transactions; defaults to the last 30 days.", TransactionArgs, transactions)
        self.register("get_spending_summary", "Summarize expenses, refunds, and category totals for a period.", PeriodArgs, lambda db, user, a: summary(db, user, a, {"expense"}))
        self.register("get_income_summary", "Summarize recorded income for a period.", PeriodArgs, lambda db, user, a: summary(db, user, a, {"income"}))
        self.register("get_daily_spending", "Aggregate posted daily spending, keeping currencies separate.", DailyArgs, daily_spending)
        self.register("get_budget_status", "Show budget usage and remaining budget for this month.", BudgetArgs, budget_statuses)
        self.register("get_savings_progress", "Retrieve progress for user-recorded savings goals.", CurrencyArgs, savings)
        self.register("get_recurring_expenses", "Find potentially recurring merchants in the recent records.", EmptyArgs, recent_recurring)
        self.register("analyze_spending_trend", "Summarize recent category totals and available trend limits.", EmptyArgs, trend)
        self.register("evaluate_purchase", "Compare a proposed purchase with same-currency balances, budget, known expenses, and goals.", PurchaseArgs, purchase)
        self.register("compare_purchase_with_budget", "Compare a proposed purchase with a category budget.", PurchaseArgs, purchase)
        self.register("calculate_remaining_budget", "Calculate remaining amount for matching budgets.", BudgetArgs, remaining)
        self.register("check_savings_goal_impact", "Compare a proposed price with the remaining same-currency savings goals.", PurchaseArgs, goal_impact)
        self.register("categorize_transaction", "Suggest a transaction category from merchant and description text.", CategoryArgs, categorize_tool)
        self.register("detect_unusual_spending", "Find large relative spending outliers; never interpret them as proof of fraud.", TransactionArgs, unusual)
        self.register("generate_financial_summary", "Summarize recorded cash flow and categories, keeping currencies separate.", TransactionArgs, financial_summary)
        self.register("estimate_month_end_spending", "Project month-end recorded spend using a straight-line estimate.", EstimateArgs, estimate)


def build_registry(session_factory: Callable[[], Any], seed_demo: Callable[[Any, str], None], timeout_seconds: float = 3.0) -> FinancialToolRegistry:
    return FinancialToolRegistry(session_factory, seed_demo, timeout_seconds)
