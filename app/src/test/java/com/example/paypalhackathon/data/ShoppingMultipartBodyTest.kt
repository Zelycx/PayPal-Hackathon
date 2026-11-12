package com.example.paypalhackathon.data

import java.io.ByteArrayOutputStream
import java.nio.charset.StandardCharsets
import org.junit.Assert.assertTrue
import org.junit.Test

class ShoppingMultipartBodyTest {
    @Test
    fun purchaseRequestContainsSelectedImageAndOptionalBudgetFields() {
        val output = ByteArrayOutputStream()
        writeShoppingMultipart(
            output = output,
            boundary = "test-boundary",
            imageBytes = byteArrayOf(1, 2, 3, 4),
            mimeType = "image/jpeg",
            includePurchaseEvaluation = true,
            budget = PurchaseBudgetInput("125.50", "PHP"),
        )

        val body = output.toByteArray().toString(StandardCharsets.ISO_8859_1)
        assertTrue(body.contains("name=\"image\"; filename=\"shopping-screenshot.jpg\""))
        assertTrue(body.contains("Content-Type: image/jpeg"))
        assertTrue(body.contains("name=\"include_purchase_evaluation\"\r\n\r\ntrue"))
        assertTrue(body.contains("name=\"budget_amount\"\r\n\r\n125.50"))
        assertTrue(body.contains("name=\"budget_currency\"\r\n\r\nPHP"))
        assertTrue(body.endsWith("--test-boundary--\r\n"))
    }

    @Test
    fun savedImageRequestRetainsOnlyExistingImageField() {
        val output = ByteArrayOutputStream()
        writeShoppingMultipart(
            output = output,
            boundary = "saved-image",
            imageBytes = byteArrayOf(9),
            mimeType = "image/png",
            includePurchaseEvaluation = false,
            budget = null,
        )

        val body = output.toByteArray().toString(StandardCharsets.ISO_8859_1)
        assertTrue(body.contains("name=\"image\"; filename=\"shopping-screenshot.png\""))
        assertTrue(!body.contains("include_purchase_evaluation"))
        assertTrue(!body.contains("budget_amount"))
    }
}
