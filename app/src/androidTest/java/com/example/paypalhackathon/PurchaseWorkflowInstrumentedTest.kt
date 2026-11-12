package com.example.paypalhackathon

import android.graphics.Bitmap
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.example.paypalhackathon.data.ShoppingResponse
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PurchaseWorkflowInstrumentedTest {
    @Test
    fun mainActivityInflatesItsBackendAndPurchaseControls() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                assertNotNull(activity.findViewById<android.view.View>(R.id.main))
                assertNotNull(activity.findViewById<android.view.View>(R.id.api_status))
                assertNotNull(activity.findViewById<android.view.View>(R.id.purchase_section))
                assertNotNull(activity.findViewById<android.view.View>(R.id.analyze_purchase_button))
            }
        }
    }

    @Test
    fun confirmedCropOwnershipTransfersAndCanBeReleasedByCaller() {
        val crop = Bitmap.createBitmap(8, 6, Bitmap.Config.ARGB_8888)
        SelectedScreenRegion.replace(crop)

        val transferred = SelectedScreenRegion.takeConfirmedBitmap()
        assertSame(crop, transferred)
        assertNull(SelectedScreenRegion.takeConfirmedBitmap())
        assertFalse(crop.isRecycled)

        crop.recycle()
        assertTrue(crop.isRecycled)
    }

    @Test
    fun clearingRegionReleasesAnUnclaimedCrop() {
        val crop = Bitmap.createBitmap(4, 4, Bitmap.Config.ARGB_8888)
        SelectedScreenRegion.replace(crop)

        SelectedScreenRegion.clear()

        assertTrue(crop.isRecycled)
        assertNull(SelectedScreenRegion.takeConfirmedBitmap())
    }

    @Test
    fun backendShoppingAndFinancialResponseRendersActualEvaluationFields() {
        val evaluation = JSONObject()
            .put("status", "WITHIN_BUDGET_AND_BALANCE")
            .put("total_amount", "250.00")
            .put("currency", "PHP")
            .put("total_source", "payable_total")
            .put("total_complete", true)
            .put("sandbox_environment", "sandbox")
            .put("sandbox_balances", JSONArray().put(JSONObject()
                .put("currency", "PHP")
                .put("available_amount", "1000.00")))
            .put("balance_available", true)
            .put("balance_freshness", "fresh")
            .put("matched_balance_amount", "1000.00")
            .put("matched_balance_currency", "PHP")
            .put("budget_amount", "300.00")
            .put("budget_currency", "PHP")
            .put("remaining_balance", "750.00")
            .put("remaining_budget", "50.00")
            .put("balance_comparison", "WITHIN_LIMIT")
            .put("budget_comparison", "WITHIN_LIMIT")
            .put("warnings", JSONArray())
            .put("ai_opinion", "The amount is within the stated limit; this does not assess other expenses.")
            .put("ai_opinion_available", true)
        val response = JSONObject()
            .put("success", true)
            .put("screen_type", "checkout")
            .put("items", JSONArray())
            .put("charges", JSONArray())
            .put("discounts", JSONArray())
            .put("totals_by_currency", JSONArray())
            .put("unassigned_visible_totals", JSONArray())
            .put("checkout_breakdown_status", "complete")
            .put("requires_review", false)
            .put("warnings", JSONArray())
            .put("purchase_evaluation", evaluation)

        val shopping = ShoppingResponse.parse(response)
        val display = shopping.toDisplayText()

        assertNotNull(shopping.purchaseEvaluation)
        assertEquals("WITHIN_BUDGET_AND_BALANCE", shopping.purchaseEvaluation?.status)
        assertTrue(display.contains("PHP 250.00"))
        assertTrue(display.contains("PayPal Sandbox"))
        assertTrue(display.contains("Estimated remaining balance: PHP 750.00"))
        assertTrue(display.contains("Estimated remaining budget: PHP 50.00"))
        assertTrue(display.contains("The amount is within the stated limit"))
    }

    @Test
    fun oldShoppingResponseWithoutEvaluationStillParses() {
        val response = JSONObject()
            .put("success", true)
            .put("screen_type", "cart")
            .put("items", JSONArray())
            .put("charges", JSONArray())
            .put("discounts", JSONArray())
            .put("totals_by_currency", JSONArray())
            .put("unassigned_visible_totals", JSONArray())
            .put("checkout_breakdown_status", "unknown")
            .put("requires_review", false)
            .put("warnings", JSONArray())

        val shopping = ShoppingResponse.parse(response)

        assertNull(shopping.purchaseEvaluation)
        assertTrue(shopping.toDisplayText().contains("Shopping analysis"))
    }

    @Test
    fun contextualChatPayloadContainsOnlyExtractedPurchaseSummary() {
        val response = JSONObject()
            .put("success", true)
            .put("screen_type", "checkout")
            .put("items", JSONArray().put(JSONObject()
                .put("name", "Desk lamp")
                .put("item_context", "cart_item")
                .put("unit_price", "45.00")
                .put("currency", "PHP")
                .put("uncertain_fields", JSONArray())))
            .put("charges", JSONArray())
            .put("discounts", JSONArray())
            .put("totals_by_currency", JSONArray())
            .put("unassigned_visible_totals", JSONArray())
            .put("checkout_breakdown_status", "complete")
            .put("requires_review", false)
            .put("warnings", JSONArray())
            .put("purchase_evaluation", JSONObject()
                .put("status", "WITHIN_BALANCE")
                .put("total_amount", "45.00")
                .put("currency", "PHP")
                .put("total_complete", true)
                .put("matched_balance_amount", "100.00")
                .put("matched_balance_currency", "PHP")
                .put("remaining_balance", "55.00")
                .put("balance_comparison", "WITHIN_LIMIT")
                .put("balance_freshness", "fresh")
                .put("warnings", JSONArray()))

        val context = ShoppingResponse.parse(response).toChatContextJson()
        val product = context.getJSONArray("products").getJSONObject(0)
        val evaluation = context.getJSONObject("purchase_evaluation")

        assertEquals("Desk lamp", product.getString("name"))
        assertEquals("45.00", evaluation.getString("total_amount"))
        assertEquals("100.00", evaluation.getString("matched_balance_amount"))
        assertFalse(context.has("transactions"))
        assertFalse(evaluation.has("sandbox_balances"))
    }
}
