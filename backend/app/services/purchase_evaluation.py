"""Deterministic, advisory purchase comparisons using existing shopping and Sandbox data."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
from typing import Awaitable, Callable

from app.schemas.shopping import (
    LimitComparison,
    PurchaseBudget,
    PurchaseEvaluation,
    PurchaseStatus,
    SandboxBalance,
    ShoppingResponse,
)
from app.services.paypal_service import get_paypal_balances
from app.services.shopping_service import GroqVisionProvider, ShoppingSettings


logger = logging.getLogger(__name__)
BalanceLoader = Callable[[], Awaitable[dict]]
OpinionGenerator = Callable[[dict], Awaitable[str]]
CancellationCheck = Callable[[], Awaitable[bool]]


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _money(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _shopping_total(shopping: ShoppingResponse) -> tuple[Decimal | None, str | None, str | None, bool, list[str]]:
    warnings: list[str] = []
    totals = shopping.totals_by_currency
    if len(totals) > 1:
        warnings.append("The selected purchase contains multiple currencies. No currency conversion was applied.")
        return None, None, None, False, warnings
    if not totals:
        return None, None, None, False, ["A purchase total with a confirmed currency could not be identified."]

    group = totals[0]
    if group.calculated_payable_total is not None and group.payable_total_complete:
        calculated = _decimal(group.calculated_payable_total)
        if calculated is not None:
            if group.visible_checkout_total is not None:
                displayed = _decimal(group.visible_checkout_total)
                if displayed is not None and displayed != calculated:
                    warnings.append("The visible checkout total differs from the server-calculated total; verify the amount before relying on this comparison.")
            return calculated, group.currency, "payable_total", True, warnings

    if (
        shopping.screen_type.value in {"cart", "checkout"}
        and group.visible_checkout_total is not None
        and group.visible_checkout_total_confidence is not None
        and group.visible_checkout_total_confidence >= 0.70
    ):
        displayed = _decimal(group.visible_checkout_total)
        if displayed is not None:
            warnings.append("The checkout amount is a value read from the screenshot; verify it on the merchant checkout page.")
            return displayed, group.currency, "visible_checkout_total", True, warnings

    subtotal = _decimal(group.items_subtotal)
    if subtotal is not None:
        warnings.append("This is the identified item subtotal. Checkout taxes, delivery, or other charges may not be included.")
        return subtotal, group.currency, "items_subtotal", False, warnings

    return None, group.currency, None, False, ["The purchase total is incomplete because one or more prices, quantities, or currencies are unknown."]


def _parse_balances(payload: dict | None) -> tuple[list[SandboxBalance], str | None, str | None, str]:
    if not isinstance(payload, dict):
        return [], None, None, "unavailable"
    raw_rows = payload.get("balances")
    rows = raw_rows if isinstance(raw_rows, list) else []
    parsed: list[SandboxBalance] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        available = row.get("available_balance")
        available = available if isinstance(available, dict) else {}
        currency = available.get("currency_code") or row.get("currency")
        amount = available.get("value")
        if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
            continue
        amount_text: str | None = None
        if isinstance(amount, str):
            parsed_amount = _decimal(amount)
            if parsed_amount is not None and abs(parsed_amount) < Decimal("1e30"):
                amount_text = _money(parsed_amount)
        try:
            parsed.append(SandboxBalance(currency=currency.upper(), available_amount=amount_text))
        except ValueError:
            continue

    as_of = payload.get("as_of_time") if isinstance(payload.get("as_of_time"), str) else None
    refreshed = payload.get("last_refresh_time") if isinstance(payload.get("last_refresh_time"), str) else None
    freshness_time = _timestamp(refreshed) or _timestamp(as_of)
    if not parsed or not any(balance.available_amount is not None for balance in parsed):
        freshness = "unavailable"
    elif freshness_time is None:
        freshness = "unknown"
    elif datetime.now(timezone.utc) - freshness_time > timedelta(hours=3):
        freshness = "stale"
    else:
        freshness = "fresh"
    return parsed, as_of, refreshed, freshness


def _comparison(
    amount: Decimal | None,
    currency: str | None,
    total: Decimal | None,
    total_currency: str | None,
    total_complete: bool,
) -> tuple[LimitComparison, Decimal | None]:
    if amount is None:
        return LimitComparison.not_provided, None
    if total is None or total_currency is None or currency is None or not total_complete:
        return LimitComparison.needs_review, None
    if currency != total_currency:
        return LimitComparison.currency_mismatch, None
    with localcontext() as context:
        context.prec = 80
        remaining = amount - total
    return (
        LimitComparison.exceeded if remaining < 0 else LimitComparison.within_limit,
        remaining,
    )


class PurchaseEvaluationService:
    def __init__(
        self,
        balance_loader: BalanceLoader = get_paypal_balances,
        opinion_generator: OpinionGenerator | None = None,
        settings: ShoppingSettings | None = None,
    ) -> None:
        self.balance_loader = balance_loader
        self.settings = settings or ShoppingSettings.from_environment()
        self.opinion_generator = opinion_generator or self._generate_opinion

    async def _generate_opinion(self, context: dict) -> str:
        if not self.settings.api_key:
            raise RuntimeError("AI opinion is not configured")
        return await GroqVisionProvider(self.settings.api_key).explain_purchase(
            context,
            self.settings.vision_model,
            min(self.settings.timeout_seconds, 20.0),
        )

    async def evaluate(
        self,
        shopping: ShoppingResponse,
        budget: PurchaseBudget | None,
        cancellation_check: CancellationCheck | None = None,
    ) -> PurchaseEvaluation:
        warnings = list(shopping.warnings)
        try:
            balance_payload = await self.balance_loader()
        except Exception as error:
            logger.warning("purchase_balance_unavailable type=%s", type(error).__name__)
            balance_payload = None
            warnings.append("PayPal Sandbox balance is unavailable, so balance affordability could not be checked.")

        balances, as_of, refreshed, freshness = _parse_balances(balance_payload)
        if freshness == "unknown":
            warnings.append("The Sandbox balance was returned without a usable refresh timestamp; verify its freshness.")
        elif freshness == "stale":
            warnings.append("The Sandbox balance is more than three hours old; refresh it before relying on the comparison.")
        elif freshness == "unavailable" and balance_payload is not None:
            warnings.append("PayPal Sandbox returned no usable available balance.")

        total, total_currency, total_source, total_complete, total_warnings = _shopping_total(shopping)
        mixed_purchase_currencies = len(shopping.totals_by_currency) > 1
        warnings.extend(total_warnings)
        if shopping.requires_review:
            warnings.append("Shopping extraction includes uncertain values or warnings; review the identified products and totals.")
            total_complete = False
        if any("differs" in warning.lower() for warning in total_warnings):
            total_complete = False

        budget_amount = _decimal(budget.amount) if budget else None
        budget_currency = budget.currency if budget else None
        budget_comparison, remaining_budget = _comparison(
            budget_amount, budget_currency, total, total_currency, total_complete
        )

        matched = next(
            (balance for balance in balances if balance.currency == total_currency and balance.available_amount is not None),
            None,
        )
        available_amount = _decimal(matched.available_amount) if matched else None
        matched_currency = matched.currency if matched else None
        if matched is None:
            if balances and total_currency and any(row.available_amount is not None for row in balances):
                balance_comparison = LimitComparison.currency_mismatch
            elif freshness == "unavailable":
                balance_comparison = LimitComparison.unavailable
            else:
                balance_comparison = LimitComparison.needs_review
            remaining_balance = None
        elif total is None or total_currency is None or not total_complete:
            balance_comparison = LimitComparison.needs_review
            remaining_balance = None
        else:
            with localcontext() as context:
                context.prec = 80
                remaining_balance = available_amount - total
            if freshness in {"stale", "unknown"}:
                balance_comparison = LimitComparison.needs_review
            else:
                balance_comparison = (
                    LimitComparison.exceeded if remaining_balance < 0 else LimitComparison.within_limit
                )

        both_exceeded = (
            budget_comparison == LimitComparison.exceeded
            and balance_comparison == LimitComparison.exceeded
        )
        if mixed_purchase_currencies:
            status = PurchaseStatus.currency_mismatch
        elif both_exceeded:
            status = PurchaseStatus.both_limits_exceeded
        elif budget_comparison == LimitComparison.exceeded:
            status = PurchaseStatus.over_budget
        elif balance_comparison == LimitComparison.exceeded:
            status = PurchaseStatus.insufficient_balance
        elif (
            budget_comparison == LimitComparison.currency_mismatch
            or balance_comparison == LimitComparison.currency_mismatch
        ):
            status = PurchaseStatus.currency_mismatch
        elif (
            total is None
            or not total_complete
            or shopping.requires_review
            or freshness in {"stale", "unknown"} and matched is not None
        ):
            status = PurchaseStatus.needs_review
        elif balance_comparison == LimitComparison.unavailable:
            status = PurchaseStatus.balance_unavailable
        elif budget is None:
            status = PurchaseStatus.within_balance
        elif balance_comparison == LimitComparison.within_limit:
            status = PurchaseStatus.within_budget_and_balance
        elif balance_comparison == LimitComparison.unavailable:
            status = PurchaseStatus.balance_unavailable
        else:
            status = PurchaseStatus.needs_review

        evaluation = PurchaseEvaluation(
            status=status,
            total_amount=_money(total),
            currency=total_currency,
            total_source=total_source,
            total_complete=total_complete,
            sandbox_balances=balances,
            balance_available=any(balance.available_amount is not None for balance in balances),
            balance_freshness=freshness,
            balance_as_of_time=as_of,
            balance_last_refresh_time=refreshed,
            matched_balance_amount=_money(available_amount),
            matched_balance_currency=matched_currency,
            budget_amount=budget.amount if budget else None,
            budget_currency=budget.currency if budget else None,
            remaining_balance=_money(remaining_balance),
            remaining_budget=_money(remaining_budget),
            balance_comparison=balance_comparison,
            budget_comparison=budget_comparison,
            warnings=list(dict.fromkeys(warnings))[:50],
            ai_opinion=None,
            ai_opinion_available=False,
        )

        context = {
            "screen_type": shopping.screen_type.value,
            "products": [
                {
                    "name": item.name,
                    "context": item.item_context.value,
                    "quantity": item.quantity,
                    "quantity_unit": item.quantity_unit,
                    "unit_price": item.unit_price,
                    "line_total": item.line_total,
                    "currency": item.currency,
                }
                for item in shopping.items[:30]
            ],
            "server_evaluation": {
                "status": evaluation.status.value,
                "total_amount": evaluation.total_amount,
                "currency": evaluation.currency,
                "total_source": evaluation.total_source,
                "total_complete": evaluation.total_complete,
                "balance_freshness": evaluation.balance_freshness,
                "matched_balance_amount": evaluation.matched_balance_amount,
                "matched_balance_currency": evaluation.matched_balance_currency,
                "remaining_balance": evaluation.remaining_balance,
                "budget_amount": evaluation.budget_amount,
                "budget_currency": evaluation.budget_currency,
                "remaining_budget": evaluation.remaining_budget,
                "balance_comparison": evaluation.balance_comparison.value,
                "budget_comparison": evaluation.budget_comparison.value,
                "warnings": evaluation.warnings[:30],
            },
            "other_sandbox_balance_currencies": sorted({
                row.currency for row in balances if row.currency != total_currency
            }),
            "shopping_warnings": shopping.warnings[:30],
        }
        if cancellation_check is not None:
            try:
                if await cancellation_check():
                    return evaluation
            except Exception:
                # A failed disconnect check must not discard the deterministic result.
                pass
        try:
            opinion = await self.opinion_generator(context)
            evaluation = evaluation.model_copy(update={"ai_opinion": opinion[:3000], "ai_opinion_available": True})
        except Exception as error:
            logger.warning("purchase_opinion_unavailable type=%s", type(error).__name__)
            evaluation = evaluation.model_copy(update={
                "warnings": list(dict.fromkeys([
                    *evaluation.warnings,
                    "The AI explanation is unavailable; the deterministic evaluation is shown.",
                ]))[:50]
            })
        return evaluation


_default_service: PurchaseEvaluationService | None = None


def get_purchase_evaluation_service() -> PurchaseEvaluationService:
    global _default_service
    if _default_service is None:
        _default_service = PurchaseEvaluationService()
    return _default_service
