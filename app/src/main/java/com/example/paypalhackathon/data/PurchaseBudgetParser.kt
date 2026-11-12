package com.example.paypalhackathon.data

/** Validates the optional per-analysis spending limit before the multipart request is sent. */
object PurchaseBudgetParser {
    private val amountPattern = Regex("^(?:0|[1-9][0-9]{0,29})(?:\\.[0-9]{1,18})?$")
    private val currencyPattern = Regex("^[A-Z]{3}$")

    fun parse(amount: String, currency: String): PurchaseBudgetInput? {
        if (amount.isBlank() && currency.isBlank()) return null
        require(amount.isNotBlank() && currency.isNotBlank()) {
            "Enter both the spending limit amount and its three-letter currency code, or leave both blank."
        }
        require(amountPattern.matches(amount)) {
            "Enter a non-negative amount using digits and an optional decimal point."
        }
        require(currencyPattern.matches(currency)) {
            "Enter a three-letter currency code such as PHP or USD."
        }
        return PurchaseBudgetInput(amount, currency)
    }
}
