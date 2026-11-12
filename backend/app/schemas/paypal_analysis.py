"""Validated response models for Sandbox PayPal financial observations."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictAnalysisModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CurrencyInsight(StrictAnalysisModel):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    observation: str = Field(min_length=1, max_length=500)
    transaction_numbers: list[int] = Field(max_length=100)

    @field_validator("observation")
    @classmethod
    def observation_has_no_unverified_numbers(cls, value: str) -> str:
        if re.search(r"\d", value):
            raise ValueError("AI observations must not introduce numeric financial claims.")
        return value


class TransactionObservation(StrictAnalysisModel):
    transaction_number: int = Field(ge=1, le=100)
    currency: str | None = Field(pattern=r"^[A-Z]{3}$")
    classification: Literal[
        "spending",
        "income",
        "transfer",
        "fee",
        "refund",
        "opening_balance",
        "other",
        "uncertain",
    ]
    event_code_evidence: str = Field(max_length=40)
    description_evidence: str = Field(max_length=240)
    observation: str = Field(min_length=1, max_length=500)

    @field_validator("observation")
    @classmethod
    def observation_has_no_unverified_numbers(cls, value: str) -> str:
        if re.search(r"\d", value):
            raise ValueError("AI observations must not introduce numeric financial claims.")
        return value


class PayPalAnalysisContent(StrictAnalysisModel):
    spending_insights: list[CurrencyInsight] = Field(max_length=20)
    income_insights: list[CurrencyInsight] = Field(max_length=20)
    transaction_observations: list[TransactionObservation] = Field(max_length=100)
    recommendations: list[str] = Field(max_length=20)

    @field_validator("recommendations")
    @classmethod
    def recommendations_are_bounded_and_nonnumeric(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value.strip() or len(value) > 300 or re.search(r"\d", value):
                raise ValueError("Recommendations must be concise and contain no numeric financial claims.")
        return values


class PayPalAnalysisResponse(PayPalAnalysisContent):
    summary: str = Field(min_length=1, max_length=800)
    success: Literal[True]
    environment: Literal["sandbox"]
    data_label: Literal["PayPal Sandbox demo data"]
    analysis_disclaimer: Literal[
        "AI-generated observations from Sandbox demo data; not verified financial facts or personal-account data."
    ]
    data_scope: dict[str, int | str | bool | None]

    @field_validator("summary")
    @classmethod
    def summary_has_no_unverified_numbers(cls, value: str) -> str:
        if re.search(r"\d", value):
            raise ValueError("Summary must not introduce numeric financial claims.")
        return value
