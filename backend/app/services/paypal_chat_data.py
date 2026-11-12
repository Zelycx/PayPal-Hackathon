"""Fresh, bounded PayPal Sandbox data retrieval for finance chat."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services import paypal_service

TRANSACTION_PAGE_SIZE = 100
MAX_CHAT_TRANSACTION_PAGES = 10
_PAYMENT_EVENT_CODES = {f"T{number:04d}" for number in range(0, 24)} - {"T0017"}
_WITHDRAWAL_EVENT_CODES = {"T0015", "T0400", "T0401", "T0402", "T0403", "T1700", "T1701"}
_REFUND_EVENT_CODES = {"T1107", "T1109", "T1115", "T1120"}
_CURRENCY_CODES = "USD|PHP|EUR|GBP|JPY|CNY|CAD|AUD|SGD|NZD|HKD|CHF|INR|KRW|THB|MYR|IDR|TWD"

_BALANCE_TERMS = re.compile(
    r"\b(balance|balances|wallet|funds|afford|how much money|money do i have|how much do i have)\b"
    r"|\bhow much\s+[a-z]{3}\s+do i have\b",
    re.I,
)
_TRANSACTION_TERMS = re.compile(
    r"\b(transaction|transactions|spent|spend|spending|expense|expenses|"
    r"received|receive|payment|payments|refund|refunds|fee|fees|transfer|activity|history|"
    r"pending|failed|reversed|biggest|lost money)\b", re.I
)


def _safe_text(value: Any, limit: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    value = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[redacted]", value, flags=re.I)
    value = re.sub(r"(?<!\w)(?:\+?\d[ .()-]*){8,}(?!\w)", "[redacted]", value)
    return value[:limit] if value else None


def _needs_for_text(text: str) -> tuple[bool, bool]:
    return bool(_BALANCE_TERMS.search(text)), bool(_TRANSACTION_TERMS.search(text))


def needs_paypal_data(message: str, history: list[dict[str, str]]) -> tuple[bool, bool]:
    needs_balance, needs_transactions = _needs_for_text(message)
    if needs_balance or needs_transactions:
        return needs_balance, needs_transactions

    # Carry the prior request's data domain into short follow-ups such as
    # "what about USD?" without attaching PayPal data to unrelated messages.
    prior_questions = [turn.get("content", "") for turn in history if turn.get("role") == "user"]
    if prior_questions and len(message.split()) <= 8:
        return _needs_for_text(prior_questions[-1])
    return False, False


def _window(message: str, now: datetime) -> tuple[datetime, datetime]:
    text = message.casefold()
    end = now
    if "yesterday" in text:
        day = (now - timedelta(days=1)).date()
        return datetime.combine(day, datetime.min.time(), timezone.utc), datetime.combine(
            day, datetime.max.time(), timezone.utc
        )
    if "today" in text:
        day = now.date()
        return datetime.combine(day, datetime.min.time(), timezone.utc), now
    if "last week" in text:
        start_of_week = now.date() - timedelta(days=now.weekday())
        start = start_of_week - timedelta(days=7)
        return datetime.combine(start, datetime.min.time(), timezone.utc), datetime.combine(
            start_of_week, datetime.min.time(), timezone.utc
        )
    if "this week" in text or "this past week" in text:
        start = now.date() - timedelta(days=now.weekday())
        return datetime.combine(start, datetime.min.time(), timezone.utc), now
    if "last month" in text:
        this_month = now.date().replace(day=1)
        previous_month_end = this_month - timedelta(days=1)
        previous_month_start = previous_month_end.replace(day=1)
        return datetime.combine(previous_month_start, datetime.min.time(), timezone.utc), datetime.combine(
            this_month, datetime.min.time(), timezone.utc
        )
    if "this month" in text or "month to date" in text:
        start = now.date().replace(day=1)
        return datetime.combine(start, datetime.min.time(), timezone.utc), now

    explicit = re.search(r"(\d{4}-\d{2}-\d{2})\s+(?:to|through|until)\s+(\d{4}-\d{2}-\d{2})", text)
    if explicit:
        start_day = datetime.strptime(explicit.group(1), "%Y-%m-%d").date()
        end_day = datetime.strptime(explicit.group(2), "%Y-%m-%d").date()
        if end_day < start_day:
            raise ValueError("The PayPal transaction date range ends before it starts.")
        start = datetime.combine(start_day, datetime.min.time(), timezone.utc)
        finish = datetime.combine(end_day, datetime.max.time(), timezone.utc)
        if finish - start > timedelta(days=31):
            raise ValueError("PayPal transaction search supports date ranges up to 31 days.")
        return start, finish

    days = 7 if "week" in text else 31 if "month" in text else 30
    return now - timedelta(days=days), now


def _paypal_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _affordability_input(message: str) -> tuple[str, str | None] | None:
    if not re.search(r"\bafford\b", message, re.I):
        return None
    match = re.search(
        rf"(?:(?P<prefix>{_CURRENCY_CODES})\s*)?(?P<symbol>[₱€£$])?\s*"
        rf"(?P<amount>\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?|\d+(?:\.\d+)?)"
        rf"\s*(?P<suffix>{_CURRENCY_CODES})?\b",
        message,
        re.I,
    )
    if not match:
        return None
    amount = match.group("amount").replace(",", "")
    currency = match.group("prefix") or match.group("suffix")
    symbol = match.group("symbol")
    symbol_codes = {"₱": "PHP", "€": "EUR", "£": "GBP"}
    if not currency and symbol:
        currency = symbol_codes.get(symbol)
    try:
        value = Decimal(amount)
    except InvalidOperation:
        return None
    if not value.is_finite() or value < 0:
        return None
    return _decimal_string(value), currency.upper() if currency else None


def _compare_available_balance(
    purchase: tuple[str, str | None] | None,
    balances: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if purchase is None:
        return None
    amount, currency = purchase
    if currency is None:
        return {"amount": amount, "currency": None, "status": "currency_required"}
    row = next((item for item in balances if item.get("currency") == currency), None)
    available = _decimal_money(row.get("available")) if row else None
    if available is None:
        return {"amount": amount, "currency": currency, "status": "available_balance_unavailable"}
    _, available_amount = available
    purchase_amount = Decimal(amount)
    remaining = available_amount - purchase_amount
    return {
        "amount": amount,
        "currency": currency,
        "available_balance": (row.get("available") or {}).get("amount"),
        "status": "within_available_balance" if remaining >= 0 else "over_available_balance",
        "remaining_after_purchase": _decimal_string(remaining),
    }


def _amount(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    currency = value.get("currency_code") or value.get("currency")
    amount = value.get("value")
    if isinstance(currency, str) and isinstance(amount, str):
        return {"currency": currency, "amount": amount}
    return None


def _transaction_context(row: dict[str, Any], include_payer_info: bool) -> dict[str, Any]:
    info = row.get("transaction_info")
    if not isinstance(info, dict):
        info = row
    context = {
        "transaction_id": info.get("transaction_id"),
        "reference_id": info.get("paypal_reference_id"),
        "reference_id_type": info.get("paypal_reference_id_type"),
        "event_code": info.get("transaction_event_code"),
        "type": info.get("transaction_type"),
        "status": info.get("transaction_status"),
        "date": info.get("transaction_initiation_date"),
        "updated_date": info.get("transaction_updated_date"),
        "amount": _amount(info.get("transaction_amount")),
        "fee": _amount(info.get("fee_amount")),
        "subject": _safe_text(info.get("transaction_subject")),
        "note": _safe_text(info.get("transaction_note")),
        "invoice_id": _safe_text(info.get("invoice_id"), 80),
    }
    if include_payer_info:
        payer = row.get("payer_info")
        payer = payer if isinstance(payer, dict) else {}
        name = payer.get("payer_name")
        name = name if isinstance(name, dict) else {}
        context["payer"] = {
            "name": _safe_text(name.get("full_name") or name.get("alternate_full_name"), 100),
            "country": _safe_text(payer.get("country_code"), 2),
            "status": _safe_text(payer.get("payer_status"), 24),
        }
    return context


def _decimal_money(value: Any) -> tuple[str, Decimal] | None:
    if not isinstance(value, dict):
        return None
    currency = value.get("currency")
    raw_amount = value.get("amount")
    if not isinstance(currency, str) or not isinstance(raw_amount, str):
        return None
    try:
        amount = Decimal(raw_amount)
    except InvalidOperation:
        return None
    if not amount.is_finite():
        return None
    return currency, amount


def _decimal_string(amount: Decimal) -> str:
    normalized = format(amount.normalize(), "f")
    return "0" if normalized in {"-0", ""} else normalized


def _transaction_summary(rows: list[dict[str, Any]], coverage_complete: bool) -> dict[str, Any]:
    """Calculate bounded currency-separated totals only for recognized event/type pairs."""
    outflows: dict[str, Decimal] = {}
    inflows: dict[str, Decimal] = {}
    pending: dict[str, Decimal] = {}
    fees: dict[str, Decimal] = {}
    refunds: dict[str, Decimal] = {}
    biggest_outflows: dict[str, tuple[Decimal, dict[str, Any]]] = {}
    uncertain_rows = 0

    for row in rows:
        code = row.get("event_code")
        transaction_type = (row.get("type") or "").casefold()
        status = row.get("status")
        money = _decimal_money(row.get("amount"))
        is_payment = code in _PAYMENT_EVENT_CODES and any(
            word in transaction_type for word in ("payment", "checkout", "purchase")
        )
        is_withdrawal = code in _WITHDRAWAL_EVENT_CODES and any(
            word in transaction_type for word in ("withdrawal", "withdraw", "sweep", "payout")
        )
        is_refund = code in _REFUND_EVENT_CODES and "refund" in transaction_type
        if money and (is_payment or is_withdrawal):
            currency, amount = money
            if status == "P":
                pending[currency] = pending.get(currency, Decimal(0)) + abs(amount)
            elif status == "S":
                if amount < 0:
                    outflows[currency] = outflows.get(currency, Decimal(0)) + abs(amount)
                    if is_payment and (currency not in biggest_outflows or abs(amount) > biggest_outflows[currency][0]):
                        biggest_outflows[currency] = (abs(amount), row)
                elif amount > 0:
                    inflows[currency] = inflows.get(currency, Decimal(0)) + amount
            else:
                uncertain_rows += 1
        elif money and is_refund:
            currency, amount = money
            if status == "S" and amount > 0:
                refunds[currency] = refunds.get(currency, Decimal(0)) + amount
            elif status not in {"P", "S"}:
                uncertain_rows += 1
        elif status in {"P", "S"}:
            uncertain_rows += 1

        fee = _decimal_money(row.get("fee"))
        # Fee fields on a payment row are the detailed fee amount; standalone
        # T01xx fee events can also appear in an all-record search, so summing
        # both forms would risk counting the same fee twice.
        if fee and status == "S" and (is_payment or is_withdrawal):
            currency, amount = fee
            fees[currency] = fees.get(currency, Decimal(0)) + abs(amount)

    def totals(values: dict[str, Decimal]) -> list[dict[str, str]]:
        return [
            {"currency": currency, "amount": _decimal_string(values[currency])}
            for currency in sorted(values)
        ]

    largest = []
    for currency, (amount, row) in sorted(biggest_outflows.items()):
        largest.append({
            "currency": currency,
            "amount": _decimal_string(amount),
            "date": row.get("date"),
            "type": row.get("type"),
            "subject": row.get("subject"),
            "transaction_id": row.get("transaction_id"),
        })
    return {
        "completed_outflows": totals(outflows),
        "completed_inflows": totals(inflows),
        "pending_transaction_amounts": totals(pending),
        "reported_fees": totals(fees),
        "completed_refunds_received": totals(refunds),
        "largest_completed_payment_outflow_by_currency": largest,
        "unclassified_or_nonterminal_records": uncertain_rows,
        "coverage_complete": coverage_complete,
        "method": "Decimal sums of PayPal signed amounts only where event code and transaction type identify a payment or withdrawal; currencies are kept separate.",
    }


async def retrieve_paypal_chat_data(
    message: str,
    history: list[dict[str, str]],
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Fetch only the financial records relevant to a chat turn, without caching."""
    needs_balance, needs_transactions = needs_paypal_data(message, history)
    if not needs_balance and not needs_transactions:
        return None

    retrieved_at = datetime.now(timezone.utc)
    context: dict[str, Any] = {
        "source": "configured PayPal Sandbox application account",
        "retrieved_at": _paypal_timestamp(retrieved_at),
    }

    if needs_balance:
        payload = await paypal_service.get_paypal_balances()
        raw_balances = payload.get("balances") if isinstance(payload, dict) else None
        if not isinstance(raw_balances, list):
            raw_balances = []
        context["balances"] = []
        for row in raw_balances:
            if not isinstance(row, dict):
                continue
            total = _amount(row.get("total_balance"))
            available = _amount(row.get("available_balance"))
            withheld = _amount(row.get("withheld_balance"))
            context["balances"].append({
                "currency": row.get("currency_code") or row.get("currency")
                or (total or available or withheld or {}).get("currency"),
                "total": total,
                "available": available,
                "withheld": withheld,
            })
        context["balance_status"] = "returned" if context["balances"] else "no_balance_records_returned"
        context["balance_as_of_time"] = payload.get("as_of_time")
        context["balance_last_refresh_time"] = payload.get("last_refresh_time")
        context["pending_balance_available"] = False
        comparison = _compare_available_balance(
            _affordability_input(message), context["balances"]
        )
        if comparison is not None:
            context["affordability_evaluation"] = comparison

    if needs_transactions:
        start, end = _window(message, now or retrieved_at)
        id_match = re.search(r"(?<![A-Z0-9])(?:[A-Z0-9]{17}|[A-Z0-9]{19})(?![A-Z0-9])", message, re.I)
        transaction_id = id_match.group(0) if id_match else None
        include_payer_info = bool(re.search(r"\b(who sent|sender|who paid|payer)\b", message, re.I))
        first_page = await paypal_service.get_paypal_transactions(
            start_date=_paypal_timestamp(start),
            end_date=_paypal_timestamp(end),
            page=1,
            page_size=TRANSACTION_PAGE_SIZE,
            transaction_id=transaction_id,
            include_payer_info=include_payer_info,
            balance_affecting_records_only=False,
        )
        reported_pages = first_page.get("total_pages")
        pages_known = isinstance(reported_pages, int) and reported_pages >= 0
        total_pages = reported_pages if pages_known and reported_pages > 0 else 1
        pages_to_fetch = min(total_pages, MAX_CHAT_TRANSACTION_PAGES)
        rows = list(first_page.get("transaction_details", []))
        for page in range(2, pages_to_fetch + 1):
            result = await paypal_service.get_paypal_transactions(
                start_date=_paypal_timestamp(start),
                end_date=_paypal_timestamp(end),
                page=page,
                page_size=TRANSACTION_PAGE_SIZE,
                transaction_id=transaction_id,
                include_payer_info=include_payer_info,
                balance_affecting_records_only=False,
            )
            rows.extend(result.get("transaction_details", []))

        coverage_complete = pages_known and total_pages <= MAX_CHAT_TRANSACTION_PAGES
        context["transaction_window"] = {
            "start_date": _paypal_timestamp(start),
            "end_date": _paypal_timestamp(end),
            "records_returned": len(rows),
            "total_items_reported": first_page.get("total_items"),
            "pages_fetched": pages_to_fetch,
            "total_pages_reported": reported_pages if pages_known else None,
            "coverage_complete": coverage_complete,
        }
        context["transactions"] = [
            _transaction_context(row, include_payer_info) for row in rows if isinstance(row, dict)
        ]
        context["transaction_summary"] = _transaction_summary(
            context["transactions"], coverage_complete
        )

    return context
