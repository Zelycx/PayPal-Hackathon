from decimal import Decimal

from app.database.models import Account, Budget, SavingsGoal
from app.finance.calculations import ZERO


def evaluate_purchase(
    price: Decimal,
    currency: str,
    accounts: list[Account],
    matching_budget: Budget | None,
    budget_spent: Decimal | None,
    savings_goals: list[SavingsGoal],
    upcoming_expenses: Decimal = ZERO,
) -> dict[str, object]:
    same_currency = [account for account in accounts if account.currency == currency]
    available = sum((Decimal(account.available_balance if account.available_balance is not None else account.balance) for account in same_currency), ZERO)
    budget_remaining = Decimal(matching_budget.amount) - (budget_spent or ZERO) if matching_budget else None
    missing = []
    if not same_currency:
        missing.append(f"No account balance is recorded in {currency}.")
    if matching_budget is None:
        missing.append("No matching budget is available to judge discretionary affordability.")
    if missing:
        verdict = "insufficient_information"
    elif price > budget_remaining or price > available - upcoming_expenses:
        verdict = "outside_recorded_limits"
    else:
        verdict = "within_recorded_budget"
    goal_context = []
    for goal in savings_goals:
        if goal.currency == currency:
            remaining = max(ZERO, Decimal(goal.target_amount) - Decimal(goal.current_amount))
            goal_context.append({"goal": goal.name, "remaining_to_target": remaining, "purchase_as_share_of_remaining_goal": ((price / remaining * 100).quantize(Decimal("0.01")) if remaining > ZERO else None)})
    return {
        "verdict": verdict,
        "price": price,
        "currency": currency,
        "recorded_available_balance": available if same_currency else None,
        "recorded_upcoming_expenses": upcoming_expenses,
        "budget_remaining": budget_remaining,
        "savings_goal_context": goal_context,
        "missing_information": missing,
        "source_note": "This is a comparison against recorded data, not a guarantee of affordability. Account balance alone does not establish affordability.",
    }
