from collections import defaultdict
from decimal import Decimal

from app.database.models import Transaction
from app.finance.calculations import ZERO, category_totals


def detect_unusual_spending(transactions: list[Transaction]) -> list[dict[str, object]]:
    expenses = [t for t in transactions if t.status == "posted" and t.kind == "expense"]
    groups: dict[tuple[str, str], list[Transaction]] = defaultdict(list)
    for item in expenses:
        groups[(item.currency, item.category)].append(item)
    findings: list[dict[str, object]] = []
    for (currency, category), items in groups.items():
        if len(items) < 4:
            continue
        values = [Decimal(item.amount) for item in items]
        average = sum(values, ZERO) / Decimal(len(values))
        for item, value in zip(items, values):
            if average > ZERO and value >= average * Decimal("2.5"):
                findings.append({"transaction_id": item.id, "category": category, "currency": currency, "amount": value, "category_average": average.quantize(Decimal("0.01")), "label": "potentially_unusual", "note": "A relative spending pattern only; this does not imply fraud."})
    return findings


def recurring_candidates(transactions: list[Transaction]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[Transaction]] = defaultdict(list)
    for item in transactions:
        if item.status == "posted" and item.kind == "expense" and item.merchant:
            groups[(item.merchant.casefold(), item.currency)].append(item)
    results = []
    for (merchant, currency), items in groups.items():
        if len(items) >= 3:
            results.append({"merchant": merchant, "currency": currency, "occurrences": len(items), "label": "potentially_recurring", "note": "Repeated recorded payments may be recurring; verify with the account provider."})
    return results


def trend_summary(transactions: list[Transaction]) -> dict[str, object]:
    current = category_totals(transactions)
    return {"category_totals_by_currency": current, "comparison": "A prior comparable period is needed to identify a trend."}
