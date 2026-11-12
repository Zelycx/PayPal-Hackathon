"""Schemas for AI-extracted shopping data and the public API response."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


MONEY_PATTERN = r"^(?:0|[1-9][0-9]{0,29})(?:\.[0-9]{1,18})?$"
QUANTITY_PATTERN = r"^(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,6})?$"
MoneyString = Annotated[str, StringConstraints(pattern=MONEY_PATTERN, max_length=49)]
QuantityString = Annotated[str, StringConstraints(pattern=QUANTITY_PATTERN, max_length=24)]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$", min_length=3, max_length=3)]
ConfidenceValue = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class ScreenType(str, Enum):
    product_listing = "product_listing"
    product_detail = "product_detail"
    cart = "cart"
    checkout = "checkout"
    unknown = "unknown"


class ItemContext(str, Enum):
    cart_item = "cart_item"
    selected_product = "selected_product"
    listing_product = "listing_product"
    recommendation = "recommendation"
    unknown = "unknown"


class ChargeKind(str, Enum):
    shipping = "shipping"
    tax = "tax"
    service_fee = "service_fee"
    other = "other"


class DiscountKind(str, Enum):
    voucher = "voucher"
    coupon = "coupon"
    sale = "sale"
    cart = "cart"
    other = "other"


class DiscountScope(str, Enum):
    item = "item"
    cart = "cart"
    unknown = "unknown"


class VisibleTotalKind(str, Enum):
    items_subtotal = "items_subtotal"
    shipping_total = "shipping_total"
    tax_total = "tax_total"
    other_charges_total = "other_charges_total"
    discount_total = "discount_total"
    payable_total = "payable_total"


class CheckoutBreakdownStatus(str, Enum):
    not_shown = "not_shown"
    complete = "complete"
    partial = "partial"
    unknown = "unknown"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


SIGNED_MONEY_PATTERN = r"^-?(?:0|[1-9][0-9]{0,29})(?:\.[0-9]{1,18})?$"
SignedMoneyString = Annotated[str, StringConstraints(pattern=SIGNED_MONEY_PATTERN, max_length=50)]


def normalize_decimal_string(
    value: object,
    *,
    allow_zero: bool = True,
    maximum: Decimal = Decimal("1e30"),
) -> str:
    """Validate a plain decimal string and preserve its written precision."""
    if not isinstance(value, str) or not re.fullmatch(MONEY_PATTERN, value):
        raise ValueError("Amount must be a plain decimal string.")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Amount is invalid.") from exc
    if not amount.is_finite() or amount < 0 or amount >= maximum or (not allow_zero and amount == 0):
        raise ValueError("Amount must be finite and non-negative.")
    return format(amount, "f")


def normalize_quantity_string(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(QUANTITY_PATTERN, value):
        raise ValueError("Quantity must be a positive decimal string.")
    try:
        quantity = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Quantity is invalid.") from exc
    if not quantity.is_finite() or quantity <= 0:
        raise ValueError("Quantity must be finite and greater than zero.")
    return format(quantity, "f")


class ExtractionConfidence(StrictModel):
    name: ConfidenceValue | None = None
    item_context: ConfidenceValue | None = None
    unit_price: ConfidenceValue | None = None
    original_unit_price: ConfidenceValue | None = None
    quantity: ConfidenceValue | None = None
    line_total: ConfidenceValue | None = None
    currency: ConfidenceValue | None = None


class ExtractedProduct(StrictModel):
    name: str | None = Field(default=None, max_length=300)
    item_context: ItemContext = ItemContext.unknown
    unit_price: MoneyString | None = None
    original_unit_price: MoneyString | None = None
    quantity: QuantityString | None = None
    quantity_unit: str | None = Field(default=None, max_length=80)
    displayed_line_total: MoneyString | None = None
    currency: CurrencyCode | None = None
    currency_symbol: str | None = Field(default=None, max_length=16)
    confidence: ExtractionConfidence = Field(default_factory=ExtractionConfidence)
    uncertain_fields: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("unit_price", "original_unit_price", "displayed_line_total", mode="before")
    @classmethod
    def validate_money(cls, value: object) -> object:
        return None if value is None else normalize_decimal_string(value, maximum=Decimal("1e18"))

    @field_validator("quantity", mode="before")
    @classmethod
    def validate_quantity(cls, value: object) -> object:
        return None if value is None else normalize_quantity_string(value)


class ExtractedCharge(StrictModel):
    kind: ChargeKind
    amount: MoneyString | None = None
    currency: CurrencyCode | None = None
    currency_symbol: str | None = Field(default=None, max_length=16)
    description: str | None = Field(default=None, max_length=200)
    already_in_unit_prices: bool | None = None
    confidence: ConfidenceValue | None = None
    uncertain_fields: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("amount", mode="before")
    @classmethod
    def validate_money(cls, value: object) -> object:
        return None if value is None else normalize_decimal_string(value, maximum=Decimal("1e18"))


class ExtractedDiscount(StrictModel):
    kind: DiscountKind
    scope: DiscountScope = DiscountScope.unknown
    amount: MoneyString | None = None
    currency: CurrencyCode | None = None
    currency_symbol: str | None = Field(default=None, max_length=16)
    description: str | None = Field(default=None, max_length=200)
    already_reflected_in_current_prices: bool | None = None
    applies_to_checkout_total: bool | None = None
    confidence: ConfidenceValue | None = None
    uncertain_fields: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("amount", mode="before")
    @classmethod
    def validate_money(cls, value: object) -> object:
        return None if value is None else normalize_decimal_string(value, maximum=Decimal("1e18"))


class ExtractedVisibleTotal(StrictModel):
    kind: VisibleTotalKind
    amount: MoneyString | None = None
    currency: CurrencyCode | None = None
    currency_symbol: str | None = Field(default=None, max_length=16)
    confidence: ConfidenceValue | None = None
    uncertain_fields: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("amount", mode="before")
    @classmethod
    def validate_money(cls, value: object) -> object:
        return None if value is None else normalize_decimal_string(value, maximum=Decimal("1e18"))


class ShoppingExtraction(StrictModel):
    """Strictly validated model output. It contains observations, not calculations."""

    screen_type: ScreenType = ScreenType.unknown
    products: list[ExtractedProduct] = Field(default_factory=list, max_length=100)
    charges: list[ExtractedCharge] = Field(default_factory=list, max_length=100)
    discounts: list[ExtractedDiscount] = Field(default_factory=list, max_length=100)
    visible_totals: list[ExtractedVisibleTotal] = Field(default_factory=list, max_length=50)
    checkout_breakdown_status: CheckoutBreakdownStatus = CheckoutBreakdownStatus.unknown
    warnings: list[str] = Field(default_factory=list, max_length=50)


class ConfidenceScores(StrictModel):
    name: ConfidenceValue | None = None
    item_context: ConfidenceValue | None = None
    unit_price: ConfidenceValue | None = None
    original_unit_price: ConfidenceValue | None = None
    quantity: ConfidenceValue | None = None
    line_total: ConfidenceValue | None = None
    currency: ConfidenceValue | None = None


class ShoppingItem(StrictModel):
    name: str | None = Field(default=None, max_length=300)
    item_context: ItemContext
    unit_price: MoneyString | None = None
    original_unit_price: MoneyString | None = None
    quantity: QuantityString | None = None
    quantity_unit: str | None = Field(default=None, max_length=80)
    line_total: MoneyString | None = None
    displayed_line_total: MoneyString | None = None
    line_total_source: Literal["calculated", "unavailable"] = "unavailable"
    currency: CurrencyCode | None = None
    currency_symbol: str | None = Field(default=None, max_length=16)
    confidence: ConfidenceScores = Field(default_factory=ConfidenceScores)
    uncertain_fields: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("unit_price", "original_unit_price", "line_total", "displayed_line_total", mode="before")
    @classmethod
    def validate_money(cls, value: object) -> object:
        return None if value is None else normalize_decimal_string(value)

    @field_validator("quantity", mode="before")
    @classmethod
    def validate_quantity(cls, value: object) -> object:
        return None if value is None else normalize_quantity_string(value)


class ShoppingCharge(StrictModel):
    kind: ChargeKind
    amount: MoneyString | None = None
    currency: CurrencyCode | None = None
    currency_symbol: str | None = Field(default=None, max_length=16)
    description: str | None = Field(default=None, max_length=200)
    already_in_unit_prices: bool | None = None
    confidence: ConfidenceValue | None = None
    uncertain_fields: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("amount", mode="before")
    @classmethod
    def validate_money(cls, value: object) -> object:
        return None if value is None else normalize_decimal_string(value)


class ShoppingDiscount(StrictModel):
    kind: DiscountKind
    scope: DiscountScope
    amount: MoneyString | None = None
    currency: CurrencyCode | None = None
    currency_symbol: str | None = Field(default=None, max_length=16)
    description: str | None = Field(default=None, max_length=200)
    already_reflected_in_current_prices: bool | None = None
    applies_to_checkout_total: bool | None = None
    confidence: ConfidenceValue | None = None
    uncertain_fields: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("amount", mode="before")
    @classmethod
    def validate_money(cls, value: object) -> object:
        return None if value is None else normalize_decimal_string(value)


class UnassignedVisibleTotal(StrictModel):
    kind: VisibleTotalKind
    amount: MoneyString | None = None
    currency_symbol: str | None = Field(default=None, max_length=16)
    confidence: ConfidenceValue | None = None
    reason: str

    @field_validator("amount", mode="before")
    @classmethod
    def validate_money(cls, value: object) -> object:
        return None if value is None else normalize_decimal_string(value)


class CurrencyTotals(StrictModel):
    currency: CurrencyCode
    items_subtotal: MoneyString | None = None
    items_subtotal_complete: bool
    shipping_total: MoneyString | None = None
    tax_total: MoneyString | None = None
    other_charges_total: MoneyString | None = None
    discount_total: MoneyString | None = None
    calculated_payable_total: MoneyString | None = None
    payable_total_complete: bool
    displayed_items_subtotal: MoneyString | None = None
    displayed_shipping_total: MoneyString | None = None
    displayed_tax_total: MoneyString | None = None
    displayed_other_charges_total: MoneyString | None = None
    displayed_discount_total: MoneyString | None = None
    visible_checkout_total: MoneyString | None = None
    visible_checkout_total_confidence: ConfidenceValue | None = None

    @field_validator(
        "items_subtotal", "shipping_total", "tax_total", "other_charges_total",
        "discount_total", "calculated_payable_total", "displayed_items_subtotal",
        "displayed_shipping_total", "displayed_tax_total", "displayed_other_charges_total",
        "displayed_discount_total", "visible_checkout_total", mode="before"
    )
    @classmethod
    def validate_money(cls, value: object) -> object:
        return None if value is None else normalize_decimal_string(value)


class PurchaseBudget(StrictModel):
    """An optional, one-time spending limit supplied for this analysis."""

    amount: MoneyString
    currency: CurrencyCode

    @field_validator("amount", mode="before")
    @classmethod
    def validate_amount(cls, value: object) -> object:
        return normalize_decimal_string(value, maximum=Decimal("1e30"))


class SandboxBalance(StrictModel):
    currency: CurrencyCode
    available_amount: SignedMoneyString | None = None

    @field_validator("available_amount", mode="before")
    @classmethod
    def validate_available_amount(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str) or not re.fullmatch(SIGNED_MONEY_PATTERN, value):
            raise ValueError("Balance must be a decimal string.")
        amount = Decimal(value)
        if not amount.is_finite() or abs(amount) >= Decimal("1e30"):
            raise ValueError("Balance must be finite and in the supported range.")
        return format(amount, "f")


class PurchaseStatus(str, Enum):
    within_budget_and_balance = "WITHIN_BUDGET_AND_BALANCE"
    within_budget = "WITHIN_BUDGET"
    within_balance = "WITHIN_BALANCE"
    over_budget = "OVER_BUDGET"
    insufficient_balance = "INSUFFICIENT_BALANCE"
    both_limits_exceeded = "BOTH_LIMITS_EXCEEDED"
    needs_review = "NEEDS_REVIEW"
    balance_unavailable = "BALANCE_UNAVAILABLE"
    currency_mismatch = "CURRENCY_MISMATCH"


class LimitComparison(str, Enum):
    within_limit = "WITHIN_LIMIT"
    exceeded = "EXCEEDED"
    not_provided = "NOT_PROVIDED"
    unavailable = "UNAVAILABLE"
    currency_mismatch = "CURRENCY_MISMATCH"
    needs_review = "NEEDS_REVIEW"


class PurchaseEvaluation(StrictModel):
    """Deterministic comparison plus an optional, non-authoritative explanation."""

    status: PurchaseStatus
    total_amount: MoneyString | None = None
    currency: CurrencyCode | None = None
    total_source: Literal["payable_total", "visible_checkout_total", "items_subtotal"] | None = None
    total_complete: bool
    sandbox_environment: Literal["sandbox"] = "sandbox"
    sandbox_balances: list[SandboxBalance] = Field(default_factory=list, max_length=20)
    balance_available: bool
    balance_freshness: Literal["fresh", "stale", "unknown", "unavailable"]
    balance_as_of_time: str | None = None
    balance_last_refresh_time: str | None = None
    matched_balance_amount: SignedMoneyString | None = None
    matched_balance_currency: CurrencyCode | None = None
    budget_amount: MoneyString | None = None
    budget_currency: CurrencyCode | None = None
    remaining_balance: SignedMoneyString | None = None
    remaining_budget: SignedMoneyString | None = None
    balance_comparison: LimitComparison
    budget_comparison: LimitComparison
    warnings: list[str] = Field(default_factory=list, max_length=50)
    ai_opinion: str | None = Field(default=None, max_length=3000)
    ai_opinion_available: bool = False

    @field_validator("total_amount", "budget_amount", mode="before")
    @classmethod
    def validate_non_negative_amounts(cls, value: object) -> object:
        return None if value is None else normalize_decimal_string(value, maximum=Decimal("1e30"))

    @field_validator("remaining_balance", "remaining_budget", mode="before")
    @classmethod
    def validate_remaining_amounts(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str) or not re.fullmatch(SIGNED_MONEY_PATTERN, value):
            raise ValueError("Remaining amount must be a decimal string.")
        amount = Decimal(value)
        if not amount.is_finite() or abs(amount) >= Decimal("1e30"):
            raise ValueError("Remaining amount must be finite and in the supported range.")
        return format(amount, "f")


class ShoppingChatProduct(StrictModel):
    name: str | None = Field(default=None, max_length=200)
    item_context: str = Field(default="unknown", max_length=32)
    unit_price: str | None = Field(default=None, max_length=50)
    original_unit_price: str | None = Field(default=None, max_length=50)
    quantity: str | None = Field(default=None, max_length=32)
    line_total: str | None = Field(default=None, max_length=50)
    currency: str | None = Field(default=None, max_length=3)
    uncertain_fields: list[str] = Field(default_factory=list, max_length=20)


class ShoppingChatEvaluation(StrictModel):
    status: str = Field(max_length=64)
    total_amount: str | None = Field(default=None, max_length=50)
    currency: str | None = Field(default=None, max_length=3)
    total_complete: bool
    matched_balance_amount: str | None = Field(default=None, max_length=50)
    matched_balance_currency: str | None = Field(default=None, max_length=3)
    remaining_balance: str | None = Field(default=None, max_length=50)
    balance_comparison: str = Field(max_length=64)
    balance_freshness: str = Field(max_length=32)
    ai_opinion: str | None = Field(default=None, max_length=3000)
    warnings: list[str] = Field(default_factory=list, max_length=20)


class ShoppingChatContext(StrictModel):
    screen_type: str = Field(default="unknown", max_length=32)
    products: list[ShoppingChatProduct] = Field(default_factory=list, max_length=20)
    purchase_evaluation: ShoppingChatEvaluation | None = None
    warnings: list[str] = Field(default_factory=list, max_length=20)


class ShoppingChatTurn(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1200)


class ShoppingChatRequest(StrictModel):
    message: str = Field(min_length=1, max_length=1200)
    context: ShoppingChatContext = Field(default_factory=ShoppingChatContext)
    history: list[ShoppingChatTurn] = Field(default_factory=list, max_length=8)


class ShoppingChatResponse(StrictModel):
    answer: str = Field(min_length=1, max_length=3000)


class ShoppingResponse(StrictModel):
    success: Literal[True] = True
    screen_type: ScreenType
    items: list[ShoppingItem] = Field(default_factory=list, max_length=100)
    charges: list[ShoppingCharge] = Field(default_factory=list, max_length=100)
    discounts: list[ShoppingDiscount] = Field(default_factory=list, max_length=100)
    totals_by_currency: list[CurrencyTotals] = Field(default_factory=list, max_length=20)
    unassigned_visible_totals: list[UnassignedVisibleTotal] = Field(default_factory=list, max_length=50)
    checkout_breakdown_status: CheckoutBreakdownStatus
    requires_review: bool
    warnings: list[str] = Field(default_factory=list, max_length=100)
    purchase_evaluation: PurchaseEvaluation | None = None


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def _object(properties: dict[str, dict]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def extraction_json_schema() -> dict:
    """A flattened strict schema accepted by Groq's JSON Schema response mode."""
    text = {"type": "string"}
    nullable_text = _nullable(text)
    amount = _nullable({"type": "string"})
    currency = _nullable({"type": "string"})
    confidence = _nullable({"type": "number", "minimum": 0, "maximum": 1})
    nullable_bool = _nullable({"type": "boolean"})
    string_list = {"type": "array", "items": text}
    confidence_schema = _object({
        "name": confidence,
        "item_context": confidence,
        "unit_price": confidence,
        "original_unit_price": confidence,
        "quantity": confidence,
        "line_total": confidence,
        "currency": confidence,
    })
    product = _object({
        "name": nullable_text,
        "item_context": {"type": "string", "enum": [x.value for x in ItemContext]},
        "unit_price": amount,
        "original_unit_price": amount,
        "quantity": amount,
        "quantity_unit": nullable_text,
        "displayed_line_total": amount,
        "currency": currency,
        "currency_symbol": nullable_text,
        "confidence": confidence_schema,
        "uncertain_fields": string_list,
    })
    charge = _object({
        "kind": {"type": "string", "enum": [x.value for x in ChargeKind]},
        "amount": amount,
        "currency": currency,
        "currency_symbol": nullable_text,
        "description": nullable_text,
        "already_in_unit_prices": nullable_bool,
        "confidence": confidence,
        "uncertain_fields": string_list,
    })
    discount = _object({
        "kind": {"type": "string", "enum": [x.value for x in DiscountKind]},
        "scope": {"type": "string", "enum": [x.value for x in DiscountScope]},
        "amount": amount,
        "currency": currency,
        "currency_symbol": nullable_text,
        "description": nullable_text,
        "already_reflected_in_current_prices": nullable_bool,
        "applies_to_checkout_total": nullable_bool,
        "confidence": confidence,
        "uncertain_fields": string_list,
    })
    visible_total = _object({
        "kind": {"type": "string", "enum": [x.value for x in VisibleTotalKind]},
        "amount": amount,
        "currency": currency,
        "currency_symbol": nullable_text,
        "confidence": confidence,
        "uncertain_fields": string_list,
    })
    return _object({
        "screen_type": {"type": "string", "enum": [x.value for x in ScreenType]},
        "products": {"type": "array", "items": product},
        "charges": {"type": "array", "items": charge},
        "discounts": {"type": "array", "items": discount},
        "visible_totals": {"type": "array", "items": visible_total},
        "checkout_breakdown_status": {
            "type": "string",
            "enum": [x.value for x in CheckoutBreakdownStatus],
        },
        "warnings": string_list,
    })
