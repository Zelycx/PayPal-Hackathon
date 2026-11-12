package com.example.paypalhackathon.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class PurchaseBudgetParserTest {
    @Test
    fun bothBlankMeansNoBudget() {
        assertNull(PurchaseBudgetParser.parse("", ""))
    }

    @Test
    fun validOneTimeBudgetIsPreserved() {
        assertEquals(PurchaseBudgetInput("125.50", "PHP"), PurchaseBudgetParser.parse("125.50", "PHP"))
    }

    @Test
    fun amountAndCurrencyMustBeProvidedTogether() {
        assertThrows(IllegalArgumentException::class.java) {
            PurchaseBudgetParser.parse("125", "")
        }
    }

    @Test
    fun budgetRejectsExponentAndNegativeAmounts() {
        assertThrows(IllegalArgumentException::class.java) {
            PurchaseBudgetParser.parse("1e3", "PHP")
        }
        assertThrows(IllegalArgumentException::class.java) {
            PurchaseBudgetParser.parse("-10", "PHP")
        }
    }

    @Test
    fun currencyMustBeAnIsoStyleThreeLetterCode() {
        assertThrows(IllegalArgumentException::class.java) {
            PurchaseBudgetParser.parse("10", "P")
        }
    }
}
