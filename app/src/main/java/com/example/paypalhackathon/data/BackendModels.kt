package com.example.paypalhackathon.data

import org.json.JSONArray
import org.json.JSONObject

data class ShoppingItem(
    val name: String?,
    val context: String,
    val unitPrice: String?,
    val originalUnitPrice: String?,
    val quantity: String?,
    val quantityUnit: String?,
    val lineTotal: String?,
    val lineTotalSource: String?,
    val displayedLineTotal: String?,
    val currency: String?,
    val currencySymbol: String?,
    val uncertainFields: List<String>,
)

data class ShoppingCharge(
    val kind: String,
    val description: String?,
    val amount: String?,
    val currency: String?,
    val currencySymbol: String?,
)

data class ShoppingDiscount(
    val kind: String,
    val scope: String,
    val description: String?,
    val amount: String?,
    val currency: String?,
    val currencySymbol: String?,
)

data class ShoppingCurrencyTotals(
    val currency: String,
    val itemsSubtotal: String?,
    val itemsSubtotalComplete: Boolean,
    val shippingTotal: String?,
    val taxTotal: String?,
    val otherChargesTotal: String?,
    val discountTotal: String?,
    val calculatedPayableTotal: String?,
    val payableTotalComplete: Boolean,
    val displayedItemsSubtotal: String?,
    val displayedShippingTotal: String?,
    val displayedTaxTotal: String?,
    val displayedOtherChargesTotal: String?,
    val displayedDiscountTotal: String?,
    val visibleCheckoutTotal: String?,
    val visibleCheckoutTotalConfidence: Double?,
)

data class PurchaseBudgetInput(val amount: String, val currency: String)
data class ShoppingChatTurn(val role: String, val content: String)

data class SandboxAvailableBalance(val currency: String, val availableAmount: String?)

data class PurchaseEvaluation(
    val status: String,
    val totalAmount: String?,
    val currency: String?,
    val totalSource: String?,
    val totalComplete: Boolean,
    val sandboxBalances: List<SandboxAvailableBalance>,
    val balanceAvailable: Boolean,
    val balanceFreshness: String,
    val balanceAsOfTime: String?,
    val balanceLastRefreshTime: String?,
    val matchedBalanceAmount: String?,
    val matchedBalanceCurrency: String?,
    val budgetAmount: String?,
    val budgetCurrency: String?,
    val remainingBalance: String?,
    val remainingBudget: String?,
    val balanceComparison: String,
    val budgetComparison: String,
    val warnings: List<String>,
    val aiOpinion: String?,
    val aiOpinionAvailable: Boolean,
) {
    fun displayStatus(): String = status.replace('_', ' ').lowercase().replaceFirstChar { it.uppercase() }

    fun toDisplayText(): String = buildString {
        appendLine("Purchase evaluation · PayPal Sandbox (advisory)")
        appendLine("Status: ${displayStatus()}")
        appendLine(
            "Estimated total: " + (totalAmount?.let { money(it, null, currency) } ?: "not confirmed") +
                (totalSource?.let { " · $it${if (totalComplete) "" else " (incomplete)"}" } ?: "")
        )
        appendLine("Total comparison: ${if (totalComplete) "complete" else "needs review"}")

        appendLine()
        appendLine("Sandbox available balances")
        if (sandboxBalances.isEmpty()) {
            appendLine("Unavailable")
        } else {
            sandboxBalances.forEach { row ->
                appendLine("${row.currency}: ${row.availableAmount ?: "available amount not returned"}")
            }
        }
        appendLine("Balance freshness: $balanceFreshness")
        balanceAsOfTime?.let { appendLine("Balance as of: $it") }
        balanceLastRefreshTime?.let { appendLine("Last refresh: $it") }
        matchedBalanceAmount?.let {
            appendLine("Comparison balance: ${money(it, null, matchedBalanceCurrency)}")
            remainingBalance?.let { remaining ->
                appendLine("Estimated remaining balance: ${money(remaining, null, matchedBalanceCurrency)}")
            }
        }
        appendLine("Balance comparison: ${balanceComparison.replace('_', ' ').lowercase()}")

        if (budgetAmount == null || budgetCurrency == null) {
            appendLine("Spending limit: none supplied for this analysis")
        } else {
            appendLine("One-time spending limit: ${money(budgetAmount, null, budgetCurrency)}")
            appendLine("Budget comparison: ${budgetComparison.replace('_', ' ').lowercase()}")
            remainingBudget?.let { appendLine("Estimated remaining budget: ${money(it, null, budgetCurrency)}") }
        }

        appendLine()
        appendLine("AI explanation")
        appendLine(aiOpinion ?: "Unavailable. The status and comparisons above were calculated by the backend.")
        if (warnings.isNotEmpty()) {
            appendLine()
            appendLine("Evaluation warnings")
            warnings.forEach { appendLine("• $it") }
        }
    }.trim()

    companion object {
        fun parse(json: JSONObject): PurchaseEvaluation = PurchaseEvaluation(
            status = json.string("status") ?: "NEEDS_REVIEW",
            totalAmount = json.string("total_amount"),
            currency = json.string("currency"),
            totalSource = json.string("total_source"),
            totalComplete = json.optBoolean("total_complete"),
            sandboxBalances = json.array("sandbox_balances").map { row ->
                SandboxAvailableBalance(
                    currency = row.string("currency") ?: "???",
                    availableAmount = row.string("available_amount"),
                )
            },
            balanceAvailable = json.optBoolean("balance_available"),
            balanceFreshness = json.string("balance_freshness") ?: "unknown",
            balanceAsOfTime = json.string("balance_as_of_time"),
            balanceLastRefreshTime = json.string("balance_last_refresh_time"),
            matchedBalanceAmount = json.string("matched_balance_amount"),
            matchedBalanceCurrency = json.string("matched_balance_currency"),
            budgetAmount = json.string("budget_amount"),
            budgetCurrency = json.string("budget_currency"),
            remainingBalance = json.string("remaining_balance"),
            remainingBudget = json.string("remaining_budget"),
            balanceComparison = json.string("balance_comparison") ?: "UNAVAILABLE",
            budgetComparison = json.string("budget_comparison") ?: "NOT_PROVIDED",
            warnings = json.stringList("warnings"),
            aiOpinion = json.string("ai_opinion"),
            aiOpinionAvailable = json.optBoolean("ai_opinion_available"),
        )
    }
}

data class ShoppingResponse(
    val screenType: String,
    val items: List<ShoppingItem>,
    val charges: List<ShoppingCharge>,
    val discounts: List<ShoppingDiscount>,
    val totals: List<ShoppingCurrencyTotals>,
    val unassignedVisibleTotals: List<String>,
    val checkoutBreakdownStatus: String,
    val requiresReview: Boolean,
    val warnings: List<String>,
    val purchaseEvaluation: PurchaseEvaluation?,
) {
    /** Shares only extracted shopping fields and the relevant matched-currency comparison. */
    fun toChatContextJson(): JSONObject = JSONObject().apply {
        put("screen_type", screenType)
        put("products", JSONArray().apply {
            items.take(20).forEach { item ->
                put(JSONObject().apply {
                    put("name", item.name)
                    put("item_context", item.context)
                    put("unit_price", item.unitPrice)
                    put("original_unit_price", item.originalUnitPrice)
                    put("quantity", item.quantity)
                    put("line_total", item.lineTotal)
                    put("currency", item.currency)
                    put("uncertain_fields", JSONArray(item.uncertainFields.take(20)))
                })
            }
        })
        put("warnings", JSONArray(warnings.take(20)))
        purchaseEvaluation?.let { evaluation ->
            put("purchase_evaluation", JSONObject().apply {
                put("status", evaluation.status)
                put("total_amount", evaluation.totalAmount)
                put("currency", evaluation.currency)
                put("total_complete", evaluation.totalComplete)
                put("matched_balance_amount", evaluation.matchedBalanceAmount)
                put("matched_balance_currency", evaluation.matchedBalanceCurrency)
                put("remaining_balance", evaluation.remainingBalance)
                put("balance_comparison", evaluation.balanceComparison)
                put("balance_freshness", evaluation.balanceFreshness)
                put("ai_opinion", evaluation.aiOpinion)
                put("warnings", JSONArray(evaluation.warnings.take(20)))
            })
        }
    }

    fun toDisplayText(): String = buildString {
        appendLine("Shopping analysis · $screenType")
        if (requiresReview) appendLine("Review requested: some extracted values are uncertain or inconsistent.")

        appendLine()
        appendLine("Products (${items.size})")
        if (items.isEmpty()) {
            appendLine("No products were identified in this image.")
        }
        items.forEachIndexed { index, item ->
            appendLine()
            appendLine("${index + 1}. ${item.name ?: "Name unclear"} · ${item.context}")
            appendLine("Unit price: ${money(item.unitPrice, item.currencySymbol, item.currency) ?: "not identified"}")
            if (item.unitPrice == null) {
                item.currencySymbol?.let { appendLine("Visible currency symbol: $it") }
                item.currency?.let { appendLine("Currency code: $it") }
            }
            appendLine(
                "Quantity: " + (item.quantity?.let { quantity ->
                    listOfNotNull(quantity, item.quantityUnit).joinToString(" ")
                } ?: "unknown")
            )
            item.originalUnitPrice?.let {
                appendLine("Original price: ${money(it, item.currencySymbol, item.currency) ?: "not identified"}")
            }
            item.lineTotal?.let {
                val label = if (item.lineTotalSource == "calculated") "Calculated line total" else "Line total"
                appendLine("$label: ${money(it, item.currencySymbol, item.currency) ?: "not identified"}")
            }
            item.displayedLineTotal?.let {
                appendLine("Visible line total: ${money(it, item.currencySymbol, item.currency) ?: "not identified"}")
            }
            if (item.unitPrice == null) appendLine("Price: not identified")
            if (item.uncertainFields.isNotEmpty()) {
                appendLine("Uncertain fields: ${item.uncertainFields.joinToString()}")
            }
        }

        appendLine()
        appendLine("Totals")
        appendLine("Checkout breakdown: $checkoutBreakdownStatus")
        if (totals.isEmpty()) {
            appendLine("No currency totals could be calculated.")
        }
        totals.forEach { currencyTotals ->
            appendLine()
            appendLine("${currencyTotals.currency} totals")
            appendLine(total("Items subtotal", currencyTotals.itemsSubtotal, currencyTotals.currency))
            appendLine("Items subtotal complete: ${currencyTotals.itemsSubtotalComplete}")
            appendLine(total("Shipping", currencyTotals.shippingTotal, currencyTotals.currency))
            appendLine(total("Tax", currencyTotals.taxTotal, currencyTotals.currency))
            appendLine(total("Other charges", currencyTotals.otherChargesTotal, currencyTotals.currency))
            appendLine(total("Discount", currencyTotals.discountTotal, currencyTotals.currency))
            appendLine(
                total(
                    "Calculated payable total" + if (currencyTotals.payableTotalComplete) "" else " (incomplete)",
                    currencyTotals.calculatedPayableTotal,
                    currencyTotals.currency,
                )
            )
            appendLine(total("Visible checkout total", currencyTotals.visibleCheckoutTotal, currencyTotals.currency))
            currencyTotals.displayedItemsSubtotal?.let { appendLine("Visible items subtotal: ${money(it, null, currencyTotals.currency)}") }
            currencyTotals.displayedShippingTotal?.let { appendLine("Visible shipping: ${money(it, null, currencyTotals.currency)}") }
            currencyTotals.displayedTaxTotal?.let { appendLine("Visible tax: ${money(it, null, currencyTotals.currency)}") }
            currencyTotals.displayedOtherChargesTotal?.let { appendLine("Visible other charges: ${money(it, null, currencyTotals.currency)}") }
            currencyTotals.displayedDiscountTotal?.let { appendLine("Visible discount: ${money(it, null, currencyTotals.currency)}") }
        }

        if (charges.isNotEmpty()) {
            appendLine()
            appendLine("Charges")
            charges.forEach { charge ->
                appendLine("${charge.description ?: charge.kind}: ${money(charge.amount, charge.currencySymbol, charge.currency) ?: "not identified"}")
            }
        }
        if (discounts.isNotEmpty()) {
            appendLine()
            appendLine("Discounts")
            discounts.forEach { discount ->
                appendLine("${discount.description ?: discount.kind} (${discount.scope}): ${money(discount.amount, discount.currencySymbol, discount.currency) ?: "not identified"}")
            }
        }
        if (unassignedVisibleTotals.isNotEmpty()) {
            appendLine()
            appendLine("Unassigned visible totals")
            unassignedVisibleTotals.forEach(::appendLine)
        }
        if (warnings.isNotEmpty()) {
            appendLine()
            appendLine("Warnings")
            warnings.forEach { appendLine("• $it") }
        }
        purchaseEvaluation?.let {
            appendLine()
            appendLine(it.toDisplayText())
        }
    }.trim()

    companion object {
        fun parse(json: JSONObject): ShoppingResponse {
            require(json.optBoolean("success")) { "The backend did not return a successful shopping analysis." }
            return ShoppingResponse(
                screenType = json.string("screen_type") ?: "unknown",
                items = json.array("items").map { item ->
                    ShoppingItem(
                        name = item.string("name"),
                        context = item.string("item_context") ?: "unknown",
                        unitPrice = item.string("unit_price"),
                        originalUnitPrice = item.string("original_unit_price"),
                        quantity = item.string("quantity"),
                        quantityUnit = item.string("quantity_unit"),
                        lineTotal = item.string("line_total"),
                        lineTotalSource = item.string("line_total_source"),
                        displayedLineTotal = item.string("displayed_line_total"),
                        currency = item.string("currency"),
                        currencySymbol = item.string("currency_symbol"),
                        uncertainFields = item.stringList("uncertain_fields"),
                    )
                },
                charges = json.array("charges").map { charge ->
                    ShoppingCharge(
                        kind = charge.string("kind") ?: "unknown",
                        description = charge.string("description"),
                        amount = charge.string("amount"),
                        currency = charge.string("currency"),
                        currencySymbol = charge.string("currency_symbol"),
                    )
                },
                discounts = json.array("discounts").map { discount ->
                    ShoppingDiscount(
                        kind = discount.string("kind") ?: "unknown",
                        scope = discount.string("scope") ?: "unknown",
                        description = discount.string("description"),
                        amount = discount.string("amount"),
                        currency = discount.string("currency"),
                        currencySymbol = discount.string("currency_symbol"),
                    )
                },
                totals = json.array("totals_by_currency").map { total ->
                    ShoppingCurrencyTotals(
                        currency = total.string("currency") ?: "unknown",
                        itemsSubtotal = total.string("items_subtotal"),
                        itemsSubtotalComplete = total.optBoolean("items_subtotal_complete"),
                        shippingTotal = total.string("shipping_total"),
                        taxTotal = total.string("tax_total"),
                        otherChargesTotal = total.string("other_charges_total"),
                        discountTotal = total.string("discount_total"),
                        calculatedPayableTotal = total.string("calculated_payable_total"),
                        payableTotalComplete = total.optBoolean("payable_total_complete"),
                        displayedItemsSubtotal = total.string("displayed_items_subtotal"),
                        displayedShippingTotal = total.string("displayed_shipping_total"),
                        displayedTaxTotal = total.string("displayed_tax_total"),
                        displayedOtherChargesTotal = total.string("displayed_other_charges_total"),
                        displayedDiscountTotal = total.string("displayed_discount_total"),
                        visibleCheckoutTotal = total.string("visible_checkout_total"),
                        visibleCheckoutTotalConfidence = total.optDoubleOrNull("visible_checkout_total_confidence"),
                    )
                },
                unassignedVisibleTotals = json.array("unassigned_visible_totals").map { total ->
                    val kind = total.string("kind") ?: "visible total"
                    val amount = total.string("amount")?.let { money(it, total.string("currency_symbol"), null) }
                    val reason = total.string("reason")
                    listOfNotNull(kind, amount, reason).joinToString(" · ")
                },
                checkoutBreakdownStatus = json.string("checkout_breakdown_status") ?: "unknown",
                requiresReview = json.optBoolean("requires_review"),
                warnings = json.stringList("warnings"),
                purchaseEvaluation = json.optJSONObject("purchase_evaluation")
                    ?.let(PurchaseEvaluation::parse),
            )
        }
    }
}

data class WalletDashboard(
    val connection: JSONObject,
    val balances: JSONObject,
    val transactions: JSONObject,
) {
    /** Returns actual Sandbox balance values for compact navigation summaries. */
    fun balanceSummary(): String {
        val rows = balances.optJSONObject("data")?.array("balances").orEmpty()
        if (rows.isEmpty()) return "No balances returned"

        return rows.joinToString(" · ") { row ->
            val total = row.optJSONObject("total_balance")
            val value = total?.string("value")
            val currency = total?.string("currency_code") ?: row.string("currency")
            if (value == null) {
                row.toString()
            } else {
                listOfNotNull(currency, value).joinToString(" ")
            }
        }
    }

    fun toDisplayText(): String = buildString {
        appendLine("PayPal Sandbox")
        val connected = connection.optBoolean("connected")
        appendLine("Connection: ${if (connected) "Connected" else "Unavailable"}")
        connection.string("message")?.let { appendLine(it) }

        appendLine()
        appendLine("Balances")
        val balanceData = balances.optJSONObject("data")
        val balanceRows = balanceData?.array("balances").orEmpty()
        if (balanceRows.isEmpty()) {
            appendLine("No balances were returned.")
        } else {
            balanceRows.forEachIndexed { index, row ->
                appendLine("${index + 1}. ${row.toString(2)}")
            }
        }
        balanceData?.string("as_of_time")?.let { appendLine("As of: $it") }
        balanceData?.string("last_refresh_time")?.let { appendLine("Last refresh: $it") }

        appendLine()
        appendLine("Transactions · last 30 days")
        val transactionData = transactions.optJSONObject("data")
        val transactionRows = transactionData?.array("transaction_details").orEmpty()
        val totalItems = transactionData?.optInt("total_items", transactionRows.size) ?: transactionRows.size
        appendLine("Returned: ${transactionRows.size}; total reported: $totalItems")
        if (transactionRows.isEmpty()) {
            appendLine("No transactions were returned for this period.")
        } else {
            transactionRows.forEachIndexed { index, row ->
                val info = row.optJSONObject("transaction_info") ?: row
                val fields = listOf(
                    "transaction_id" to "ID",
                    "transaction_status" to "Status",
                    "transaction_event_code" to "Event",
                    "transaction_initiation_date" to "Date",
                    "transaction_updated_date" to "Updated",
                    "transaction_subject" to "Subject",
                ).mapNotNull { (key, label) -> info.string(key)?.let { "$label: $it" } }
                val amount = info.optJSONObject("transaction_amount")
                val amountText = amount?.let {
                    val value = it.string("value")
                    val currency = it.string("currency_code")
                    if (value != null) "Amount: ${money(value, null, currency)}" else null
                }
                appendLine()
                appendLine("${index + 1}. ${fields.plusIfPresent(amountText).joinToString(" · ").ifBlank { row.toString(2) }}")
            }
        }
    }.trim()
}

private fun List<String>.plusIfPresent(value: String?): List<String> = if (value == null) this else this + value

private fun total(label: String, amount: String?, currency: String): String =
    "$label: ${money(amount, null, currency) ?: "not available"}"

private fun money(amount: String?, symbol: String?, currency: String?): String? {
    amount ?: return null
    val prefix = when {
        !symbol.isNullOrBlank() && !currency.isNullOrBlank() -> "$symbol "
        !symbol.isNullOrBlank() -> "$symbol "
        !currency.isNullOrBlank() -> "$currency "
        else -> ""
    }
    val suffix = when {
        !symbol.isNullOrBlank() && !currency.isNullOrBlank() -> " ($currency)"
        !symbol.isNullOrBlank() -> " (currency code unknown)"
        currency.isNullOrBlank() -> " (currency unknown)"
        else -> ""
    }
    return "$prefix$amount$suffix"
}

private fun JSONObject.string(key: String): String? =
    if (isNull(key)) null else optString(key).takeIf { it.isNotBlank() && it != "null" }

private fun JSONObject.optDoubleOrNull(key: String): Double? =
    if (isNull(key) || !has(key)) null else optDouble(key).takeIf(Double::isFinite)

private fun JSONObject.array(key: String): List<JSONObject> {
    val value: JSONArray = optJSONArray(key) ?: return emptyList()
    return (0 until value.length()).mapNotNull { value.optJSONObject(it) }
}

private fun JSONObject.stringList(key: String): List<String> {
    val value = optJSONArray(key) ?: return emptyList()
    return (0 until value.length()).mapNotNull { index ->
        if (value.isNull(index)) null else value.optString(index).takeIf(String::isNotBlank)
    }
}
