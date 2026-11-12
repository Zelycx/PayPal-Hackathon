package com.example.paypalhackathon.data

import java.io.OutputStream
import java.io.OutputStreamWriter
import java.nio.charset.StandardCharsets

/** Writes the existing shopping image field plus optional purchase-evaluation form fields. */
internal fun writeShoppingMultipart(
    output: OutputStream,
    boundary: String,
    imageBytes: ByteArray,
    mimeType: String,
    includePurchaseEvaluation: Boolean,
    budget: PurchaseBudgetInput?,
) {
    val extension = when (mimeType) {
        "image/jpeg" -> "jpg"
        "image/png" -> "png"
        "image/webp" -> "webp"
        else -> throw BackendApiException(null, "Choose a JPEG, PNG, or WebP screenshot.")
    }
    val writer = OutputStreamWriter(output, StandardCharsets.UTF_8)
    writer.append("--$boundary\r\n")
    writer.append("Content-Disposition: form-data; name=\"image\"; filename=\"shopping-screenshot.$extension\"\r\n")
    writer.append("Content-Type: $mimeType\r\n\r\n")
    writer.flush()
    output.write(imageBytes)
    writer.append("\r\n")
    if (includePurchaseEvaluation) {
        writeField(writer, boundary, "include_purchase_evaluation", "true")
    }
    if (budget != null) {
        writeField(writer, boundary, "budget_amount", budget.amount)
        writeField(writer, boundary, "budget_currency", budget.currency)
    }
    writer.append("--$boundary--\r\n")
    writer.flush()
}

private fun writeField(writer: OutputStreamWriter, boundary: String, name: String, value: String) {
    writer.append("--$boundary\r\n")
    writer.append("Content-Disposition: form-data; name=\"$name\"\r\n\r\n")
    writer.append(value)
    writer.append("\r\n")
}
